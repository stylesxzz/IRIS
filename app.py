
import os
import re
import subprocess
import json
import time
import secrets
import html
import shlex
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, abort
from flask_session import Session
from iris_core import (
    init_dirs, detect_env, check_internet, generate_tools_conf,
    get_all_tools, cmd_exists, get_bin_version, check_and_update_tool, log, IRIS_LOG, TOOLS_CONF, IRIS_DIR
)
from database import (
    init_db, create_user, authenticate_user, get_user_by_id, get_user_credits,
    consume_credits, add_credits, get_user_subscription, update_subscription,
    reset_monthly_credits, create_mp_transaction, get_credit_history,
    create_password_reset_token, validate_reset_token, reset_password_with_token,
    payment_already_processed
)
from mercado_pago import create_preference, verify_payment, process_webhook, get_plan_info, PLANS

app = Flask(__name__)

# ── Segurança de sessão ────────────────────────────────────────────────────
# SECRET_KEY: nunca usa fallback hardcoded em produção. Se a variável de
# ambiente não estiver definida, gera uma chave aleatória nova a cada start
# (o que invalida sessões antigas, mas evita uma chave previsível/pública).
_secret_key = os.environ.get('SECRET_KEY')
if not _secret_key:
    import secrets as _secrets
    _secret_key = _secrets.token_hex(32)
    print("⚠️  AVISO: SECRET_KEY não definida no ambiente. Usando chave aleatória "
          "temporária (sessões serão invalidadas a cada reinício). Defina "
          "SECRET_KEY no .env para produção.")

app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 7  # 7 dias
app.config['SECRET_KEY'] = _secret_key

# Cookies de sessão protegidos contra roubo via JS (HttpOnly), contra
# vazamento em conexão não criptografada (Secure) e contra CSRF cross-site
# (SameSite=Lax permite navegação normal mas bloqueia POST cross-site)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'

Session(app)

# ── CSRF Protection ────────────────────────────────────────────────────────────
def generate_csrf_token():
    """Gera ou retorna o token CSRF da sessão atual."""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

def validate_csrf():
    """Valida o token CSRF enviado na requisição.
    
    Levanta 403 se o token estiver ausente ou inválido.
    Deve ser chamado em toda rota POST que modifica estado.
    """
    token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not token or not secrets.compare_digest(token, session.get('csrf_token', '')):
        log("WARN", f"CSRF inválido para {session.get('username','anon')} em {request.path}")
        abort(403, description="Token CSRF inválido ou ausente.")

# Disponibiliza o token CSRF em todos os templates Jinja2
app.jinja_env.globals['csrf_token'] = generate_csrf_token

# ── Validação de força de senha ────────────────────────────────────────────────
def validate_password_strength(password: str) -> tuple[bool, str]:
    """Verifica se a senha atende aos requisitos mínimos de segurança.
    
    Returns:
        (True, '') se válida, (False, mensagem_de_erro) se inválida.
    """
    if len(password) < 8:
        return False, "A senha deve ter pelo menos 8 caracteres."
    if not re.search(r'[A-Z]', password):
        return False, "A senha deve conter pelo menos uma letra maiúscula."
    if not re.search(r'[0-9]', password):
        return False, "A senha deve conter pelo menos um número."
    return True, ''

# ── Sanitização de argumentos de linha de comando ─────────────────────────────
_DANGEROUS_ARG_RE = re.compile(r'[;&|`$<>]')

def sanitize_command_args(raw_args: str) -> list[str]:
    """Usa shlex para tokenizar args e remove caracteres de injeção de shell.
    
    Mesmo com shell=False no subprocess, args maliciosos podem abusar de
    features de ferramentas (ex: nmap --script-args permite execução de Lua).
    Essa camada extra de defesa bloqueia os casos mais óbvios.
    """
    try:
        parts = shlex.split(raw_args)
    except ValueError:
        parts = raw_args.split()
    # Remove qualquer token que contenha caracteres de injeção de shell
    clean = [p for p in parts if not _DANGEROUS_ARG_RE.search(p)]
    if len(clean) != len(parts):
        removed = [p for p in parts if _DANGEROUS_ARG_RE.search(p)]
        log("WARN", f"Argumentos suspeitos removidos: {removed}")
    return clean
init_dirs()
detect_env()
check_internet()
init_db()

# Força regeração do tools.conf se a versão estiver desatualizada
def _conf_version():
    if not os.path.exists(TOOLS_CONF):
        return None
    with open(TOOLS_CONF, 'r') as f:
        first = f.readline()
    m = re.search(r'v(\d+\.\d+)', first)
    return m.group(1) if m else None

CURRENT_CONF_VERSION = "3.3"
if _conf_version() != CURRENT_CONF_VERSION:
    generate_tools_conf()

# Configurar PATH para que as ferramentas instaladas sejam encontradas
os.environ["PATH"] = f"{os.path.expanduser("~/.local/bin")}:{os.path.expanduser("~/go/bin")}:{os.path.join(IRIS_DIR, "tools", "bin")}:{os.environ.get("PATH")}"

# ── Decoradores de autenticação ───────────────────────────────────────────────

def login_required(f):
    """Decorador para proteger rotas que requerem autenticação."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

def check_credits_required(credits_needed=5):
    """Decorador para verificar se o usuário tem créditos suficientes."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return jsonify({"error": "Não autenticado"}), 401
            
            user_credits = get_user_credits(session['user_id'])
            if not user_credits or user_credits['balance'] < credits_needed:
                return jsonify({"error": "Créditos insuficientes"}), 402
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ── Rotas de Autenticação ─────────────────────────────────────────────────────

@app.route("/")
def index():
    if 'user_id' in session:
        return redirect(url_for('agent_page'))
    return redirect(url_for('login_page'))

@app.route("/login")
def login_page():
    if 'user_id' in session:
        return redirect(url_for('agent_page'))
    return render_template("login.html")

@app.route("/auth/register", methods=["POST"])
def register():
    """Registra novo usuário."""
    # CSRF: para JSON + fetch com header customizado, validamos via header X-CSRF-Token
    validate_csrf()
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""

    if not re.match(r'^[a-zA-Z0-9_-]{3,32}$', username):
        return jsonify({"success": False, "error": "Usuário deve ter 3-32 caracteres (letras, números, _ ou -)"}), 400

    if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
        return jsonify({"success": False, "error": "Email inválido"}), 400

    # Usa validação de força de senha
    valid, msg = validate_password_strength(password)
    if not valid:
        return jsonify({"success": False, "error": msg}), 400

    result = create_user(username, email, password)
    if result.get("success"):
        return jsonify({"success": True, "message": "Conta criada com sucesso"})
    else:
        return jsonify({"success": False, "error": result.get("error", "Erro ao criar conta")}), 400

@app.route("/auth/login", methods=["POST"])
def login():
    """Autentica usuário."""
    validate_csrf()
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip:
        client_ip = client_ip.split(',')[0].strip()  # pega só o primeiro IP em caso de proxy chain

    result = authenticate_user(username, password, ip_address=client_ip)

    if result.get("success"):
        # SESSION FIXATION FIX: regenera o ID de sessão após login bem-sucedido
        # para que um token de sessão obtido antes do login não funcione depois
        old_data = dict(session)
        session.clear()
        session.update(old_data)
        session['user_id'] = result['user_id']
        session['username'] = result['username']
        session['email'] = result['email']
        session['login_ip'] = client_ip
        session['login_at'] = time.time()
        # Gera novo CSRF token para a nova sessão
        session.pop('csrf_token', None)
        log("INFO", f"Usuário autenticado: {username} (IP: {client_ip})")
        return jsonify({"success": True, "message": "Login realizado"})
    else:
        log("WARN", f"Tentativa de login falhou: {username} (IP: {client_ip})")
        return jsonify({"success": False, "error": result.get("error", "Erro ao fazer login")}), 401

@app.route("/auth/logout", methods=["POST"])
def logout():
    """Faz logout do usuário."""
    validate_csrf()
    username = session.get('username', 'desconhecido')
    session.clear()
    log("INFO", f"Usuário desconectado: {username}")
    return jsonify({"success": True})

@app.route("/auth/forgot-password", methods=["POST"])
def forgot_password():
    """Gera um link de recuperação de senha para o email informado."""
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip()

    if not email:
        return jsonify({"success": False, "error": "Informe um email"}), 400

    result = create_password_reset_token(email)

    if not result.get("success"):
        return jsonify({"success": False, "error": result.get("error", "Erro ao gerar recuperação")}), 400

    response = {"success": True, "message": "Se o email existir, um link de recuperação foi gerado."}

    # Sem SMTP configurado ainda: exibe o link diretamente na resposta.
    # Quando configurar um servidor de email, troque isso por um envio real
    # e remova o campo 'reset_link' da resposta.
    if result.get("token"):
        reset_link = url_for('reset_password_page', token=result['token'], _external=True)
        response["reset_link"] = reset_link
        log("INFO", f"Link de recuperação gerado: {reset_link}")

    return jsonify(response)

@app.route("/reset-password")
def reset_password_page():
    """Exibe a tela para definir uma nova senha a partir do token."""
    token = request.args.get("token", "")
    check = validate_reset_token(token)
    if not check.get("valid"):
        return render_template("reset_password.html", valid=False, error=check.get("error"), token=token)
    return render_template("reset_password.html", valid=True, token=token, username=check.get("username"))

@app.route("/auth/reset-password", methods=["POST"])
def reset_password_submit():
    """Define a nova senha a partir de um token válido."""
    data = request.get_json(force=True)
    token = data.get("token") or ""
    new_password = data.get("password") or ""

    if not token or not new_password or len(new_password) < 6:
        return jsonify({"success": False, "error": "Dados inválidos. A senha deve ter ao menos 6 caracteres."}), 400

    result = reset_password_with_token(token, new_password)

    if result.get("success"):
        return jsonify({"success": True, "message": "Senha redefinida com sucesso"})
    else:
        return jsonify({"success": False, "error": result.get("error", "Erro ao redefinir senha")}), 400

# ── Rotas de Usuário ──────────────────────────────────────────────────────────

@app.route("/user/info")
@login_required
def user_info():
    """Retorna informações do usuário autenticado."""
    user = get_user_by_id(session['user_id'])
    credits = get_user_credits(session['user_id'])
    subscription = get_user_subscription(session['user_id'])
    
    return jsonify({
        "success": True,
        "user": {
            "id": user['id'],
            "username": user['username'],
            "email": user['email']
        },
        "credits": {
            "balance": credits['balance'],
            "monthly_limit": credits['monthly_limit'],
            "last_reset": credits['last_reset']
        },
        "subscription": {
            "plan_type": subscription['plan_type'],
            "status": subscription['status'],
            "start_date": subscription['start_date'],
            "end_date": subscription['end_date']
        }
    })

@app.route("/user/subscription")
@login_required
def user_subscription():
    """Retorna dados da assinatura do usuário."""
    subscription = get_user_subscription(session['user_id'])
    
    return jsonify({
        "success": True,
        "subscription": {
            "plan_type": subscription['plan_type'],
            "status": subscription['status'],
            "start_date": subscription['start_date'],
            "end_date": subscription['end_date']
        }
    })

# ── Rotas de Créditos ─────────────────────────────────────────────────────────

@app.route("/credits/balance")
@login_required
def credits_balance():
    """Retorna saldo de créditos."""
    # Reseta créditos mensais se necessário
    reset_monthly_credits(session['user_id'])
    
    credits = get_user_credits(session['user_id'])
    
    return jsonify({
        "success": True,
        "balance": credits['balance'],
        "monthly_limit": credits['monthly_limit'],
        "last_reset": credits['last_reset']
    })

@app.route("/credits/history")
@login_required
def credits_history():
    """Retorna histórico de consumo de créditos."""
    history = get_credit_history(session['user_id'], limit=50)
    
    return jsonify({
        "success": True,
        "history": history
    })

# ── Rotas de Pagamento (Mercado Pago) ─────────────────────────────────────────

@app.route("/payment/create-preference", methods=["POST"])
@login_required
def create_payment_preference():
    """Cria preferência de pagamento no Mercado Pago."""
    data = request.get_json(force=True)
    plan_type = data.get("plan_type", "").strip()
    
    if plan_type not in PLANS:
        return jsonify({"success": False, "error": "Plano inválido"}), 400
    
    user = get_user_by_id(session['user_id'])
    
    result = create_preference(session['user_id'], plan_type, user['email'])
    
    return jsonify(result)

@app.route("/payment/success")
@login_required
def payment_success():
    """Callback de sucesso do Mercado Pago."""
    payment_id = request.args.get('payment_id')

    if payment_id:
        # ── Idempotência: se este payment_id já foi processado antes (por
        # qualquer usuário), não credita de novo. Isso impede que alguém
        # reutilize um payment_id (próprio ou de terceiros) recarregando a
        # página ou compartilhando o link para ganhar créditos repetidamente. ──
        if payment_already_processed(payment_id):
            log("WARN", f"[{session['username']}] Tentativa de reprocessar payment_id já usado: {payment_id}")
            return render_template("payment_success.html")

        # Verifica o pagamento direto na API do Mercado Pago (fonte da verdade,
        # não confia em nada que vier só da URL/query string)
        payment_info = verify_payment(payment_id)

        if payment_info.get("success") and payment_info.get("status") == "approved":
            # Extrai informações do pagamento
            external_ref = payment_info.get("external_reference", "")

            # Parse: iris_user_{user_id}_{plan_type}
            if external_ref.startswith("iris_user_"):
                parts = external_ref.split("_")
                if len(parts) >= 4:
                    ref_user_id = parts[2]
                    plan_type = parts[3]

                    # ── Confirma que o pagamento pertence ao usuário logado.
                    # Sem isso, qualquer pessoa logada poderia colar o
                    # payment_id de um pagamento aprovado de OUTRA conta na
                    # URL e roubar os créditos dela. ──
                    if str(ref_user_id) != str(session['user_id']):
                        log("WARN", f"[{session['username']}] Tentativa de usar payment_id de outro usuário: {payment_id}")
                        return render_template("payment_success.html")

                    # Atualiza assinatura
                    update_subscription(session['user_id'], plan_type, payment_id)

                    # Adiciona créditos
                    plan = get_plan_info(plan_type)
                    if plan:
                        add_credits(session['user_id'], plan['credits'], f"compra_plano_{plan_type}")

                    # Registra transação (com mp_payment_id UNIQUE — segunda
                    # camada de proteção contra duplicidade no nível do banco)
                    create_mp_transaction(
                        session['user_id'],
                        payment_id,
                        plan_type,
                        payment_info.get("amount", 0),
                        "approved"
                    )

                    log("INFO", f"Pagamento aprovado para usuário {session['user_id']}: {payment_id}")

    return render_template("payment_success.html")

@app.route("/payment/failure")
@login_required
def payment_failure():
    """Callback de falha do Mercado Pago."""
    return render_template("payment_failure.html")

@app.route("/payment/pending")
@login_required
def payment_pending():
    """Callback de pagamento pendente do Mercado Pago."""
    return render_template("payment_pending.html")

@app.route("/payment/webhook", methods=["POST"])
def payment_webhook():
    """Webhook do Mercado Pago."""
    try:
        data = request.get_json(force=True)
        result = process_webhook(data)
        
        if result.get("success"):
            log("INFO", f"Webhook processado: {result.get('payment_id')}")
            return jsonify({"success": True}), 200
        else:
            return jsonify({"success": False, "error": result.get("error")}), 400
    except Exception as e:
        log("ERROR", f"Erro ao processar webhook: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

# ── Rotas de Planos ───────────────────────────────────────────────────────────

@app.route("/plans")
def plans():
    """Página de planos e preços."""
    return render_template("plans.html")

# ── Rotas do Menu e Ferramentas ───────────────────────────────────────────────

@app.route("/menu")
@login_required
def menu():
    return render_template("menu.html", active="menu")

@app.route("/category/<category_name>")
@login_required
def category(category_name):
    all_tools = get_all_tools()
    category_tools = [tool for tool in all_tools if tool["category"] == category_name]
    
    descriptions = {
        "nmap": "Scanner de redes e portas",
        "theHarvester": "Coleta e-mails e subdomínios",
        "recon-ng": "Framework OSINT modular",
        "amass": "Enumeração de superfície",
        "subfinder": "Descoberta de subdomínios",
        "sqlmap": "Injeção SQL automatizada",
        "nikto": "Scanner de vulnerabilidades web",
        "gobuster": "Brute-force de diretórios",
        "ffuf": "Fuzzer web rápido",
        "hydra": "Brute-force multi-protocolo",
        "aircrack-ng": "Suíte de auditoria Wi-Fi",
        "msfconsole": "Metasploit Framework",
        "wireshark": "Analisador de protocolos GUI",
        "tcpdump": "Captura de tráfego CLI",
        "adb": "Android Debug Bridge",
        "setoolkit": "Social-Engineer Toolkit",
        "binwalk": "Análise de firmware",
        "hashcat": "Quebra de hashes GPU",
        "john": "John the Ripper",
        "tmux": "Multiplexador de terminal",
        "htop": "Monitor de processos"
    }
    
    tools_info = []
    for tool in category_tools:
        status = "Instalado" if cmd_exists(tool["bin"]) else "Ausente"
        version = get_bin_version(tool["bin"]) if status == "Instalado" else "n/a"
        tools_info.append({
            "name": tool["bin"],
            "pkg": tool["pkg"],
            "method": tool["method"],
            "status": status,
            "version": version,
            "description": descriptions.get(tool["bin"], "Ferramenta de segurança e análise.")
        })
    return render_template("category.html", category_name=category_name, tools=tools_info, active="menu")

@app.route("/execute_tool", methods=["POST"])
@login_required
def execute_tool():
    validate_csrf()
    tool_name = request.form.get("tool_name")
    raw_args = request.form.get("command_args", "")

    if not tool_name:
        return jsonify({"status": "error", "output": "Nome da ferramenta não fornecido."})

    # Whitelist: só ferramentas cadastradas no tools.conf
    allowed_tools = {t['bin'] for t in get_all_tools()}
    if tool_name not in allowed_tools:
        log("WARN", f"[{session['username']}] Tentativa de executar ferramenta fora da whitelist: '{tool_name}'")
        return jsonify({"status": "error", "output": "Ferramenta não permitida."}), 403

    if not cmd_exists(tool_name):
        return jsonify({"status": "error", "output": f"Ferramenta '{tool_name}' não encontrada. Tente instalá-la primeiro."})

    # Sanitiza argumentos para remover caracteres de injeção de shell
    command_args = sanitize_command_args(raw_args)
    full_command = [tool_name] + command_args
    log("INFO", f"[{session['username']}] Executando: {shlex.join(full_command)}")

    try:
        result = subprocess.run(
            full_command, capture_output=True, text=True, check=True,
            env=os.environ, timeout=120, stdin=subprocess.DEVNULL
        )
        log("OK", f"Comando '{tool_name}' concluído com sucesso.")
        return jsonify({"status": "success", "output": result.stdout + result.stderr})
    except subprocess.TimeoutExpired:
        log("ERROR", f"Comando '{tool_name}' excedeu 120s.")
        return jsonify({"status": "error", "output": "Tempo limite excedido (120s). Tente um scan mais específico ou use -T4."})
    except subprocess.CalledProcessError as e:
        log("ERROR", f"Erro em '{tool_name}': {e.stderr[:200]}")
        return jsonify({"status": "error", "output": e.stdout + e.stderr})
    except FileNotFoundError:
        log("ERROR", f"'{tool_name}' não encontrado no PATH.")
        return jsonify({"status": "error", "output": f"Comando '{tool_name}' não encontrado. Verifique a instalação."})

@app.route("/install_tool", methods=["POST"])
@login_required
def install_tool():
    tool_name = request.form.get("tool_name")
    pkg_name = request.form.get("pkg_name")
    method = request.form.get("method")

    if not tool_name or not pkg_name or not method:
        return jsonify({"status": "error", "output": "Dados incompletos para instalação."})
    
    log("INFO", f"[{session['username']}] Solicitação de instalação: {tool_name} (pkg: {pkg_name}, method: {method})")
    result_code = check_and_update_tool(tool_name, pkg_name, method)
    
    if result_code == 0:
        return jsonify({"status": "success", "output": f"Ferramenta {tool_name} instalada/atualizada com sucesso!"})
    elif result_code == 2:
        return jsonify({"status": "warning", "output": f"Ferramenta {tool_name} não suportada ou já atualizada."})
    else:
        return jsonify({"status": "error", "output": f"Falha ao instalar/atualizar {tool_name}. Verifique o log."})

@app.route("/add_tool", methods=["POST"])
@login_required
def add_tool():
    tool_name = request.form.get("tool_name", "").strip()
    pkg        = request.form.get("pkg", "").strip()
    method     = request.form.get("method", "pkg").strip()
    category   = request.form.get("category", "recon").strip()
    install_now = request.form.get("install_now", "false") == "true"

    if not tool_name or not pkg:
        return jsonify({"status": "error", "output": "Nome e pacote/URL são obrigatórios."})

    if method not in ("pkg", "pip", "go", "git"):
        return jsonify({"status": "error", "output": f"Método inválido: {method}"})

    with open(TOOLS_CONF, "r") as f:
        content = f.read()

    if re.search(rf'^{re.escape(tool_name)}:', content, re.MULTILINE):
        return jsonify({"status": "warning", "output": f"'{tool_name}' já existe no tools.conf."})

    cat_marker = f"# -- {category.upper().replace('_', ' ')}"
    lines = content.splitlines()
    insert_idx = None
    for i, line in enumerate(lines):
        if cat_marker in line.upper():
            j = i + 1
            while j < len(lines) and not (lines[j].startswith("# --") and j != i+1):
                if lines[j].startswith("# --") and j > i:
                    break
                j += 1
            insert_idx = j
            break

    new_line = f"{tool_name}:{pkg}:{method}:{category}"
    if insert_idx is not None:
        lines.insert(insert_idx, new_line)
        new_content = "\n".join(lines) + "\n"
    else:
        new_content = content.rstrip() + f"\n\n# -- {category.upper()} ----\n{new_line}\n"

    with open(TOOLS_CONF, "w") as f:
        f.write(new_content)

    log("INFO", f"[{session['username']}] Ferramenta adicionada ao tools.conf: {new_line}")

    output = f"'{tool_name}' adicionado à categoria '{category}'."
    if install_now:
        result_code = check_and_update_tool(tool_name, pkg, method)
        if result_code == 0:
            output += f"\nInstalação concluída com sucesso!"
        else:
            output += f"\nFalha na instalação — verifique o log."

    return jsonify({"status": "success", "output": output})

@app.route("/tool_status")
@login_required
def tool_status():
    all_tools = get_all_tools()
    status_info = {}
    for tool in all_tools:
        category = tool["category"]
        if category not in status_info:
            status_info[category] = []
        
        tool_status = "Instalado" if cmd_exists(tool["bin"]) else "Ausente"
        tool_version = get_bin_version(tool["bin"]) if tool_status == "Instalado" else "n/a"
        status_info[category].append({"name": tool["bin"], "status": tool_status, "version": tool_version})
    
    online_status = "ONLINE" if os.environ.get("ONLINE") == "1" else "OFFLINE"
    return render_template("status.html", status_info=status_info, online_status=online_status, active="status")

@app.route("/view_log")
@login_required
def view_log():
    if os.path.exists(IRIS_LOG):
        with open(IRIS_LOG, "r") as f:
            log_content = f.read()
        log_content = re.sub(r"\x1b\[[0-9;]*m", "", log_content)
    else:
        log_content = "Nenhum log encontrado."
    return render_template("log.html", log_content=log_content, active="log")

# ── Rotas do Agente ───────────────────────────────────────────────────────────

@app.route("/agent")
@login_required
def agent_page():
    return render_template("agent.html", active="agent")

@app.route("/agent/chat", methods=["POST"])
@login_required
@check_credits_required(5)
def agent_chat():
    """
    Proxy para o Hermes Agent via subprocess.
    Consome 5 créditos por consulta.
    Mantém histórico em ~/.iris/agent_history_{user_id}.json
    """
    data     = request.get_json(force=True)
    message  = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Mensagem vazia."}), 400

    user_id = session['user_id']
    history_path = os.path.join(IRIS_DIR, f"agent_history_{user_id}.json")

    # Carrega histórico
    if os.path.exists(history_path):
        with open(history_path) as f:
            history = json.load(f)
    else:
        history = []

    # Monta contexto: últimas 12 trocas (24 mensagens)
    recent = history[-24:]

    # Chama o Hermes via CLI — v0.16 usa 'chat --query' (não existe 'ask' nem '-z')
    hermes_bin = os.path.expanduser("~/.hermes/bin/hermes")
    if not os.path.exists(hermes_bin):
        hermes_bin = "hermes"  # fallback se estiver no PATH

    env = os.environ.copy()
    env["HERMES_HISTORY_JSON"] = json.dumps(recent)

    cmd = [hermes_bin, "chat", "-p", "iris-agent", "--query", message]

    reply = None
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        reply = out or err or "Sem resposta."
    except FileNotFoundError:
        return jsonify({"error": "Hermes não instalado. Execute o setup_hermes.sh primeiro."}), 503
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Tempo esgotado. Tente uma pergunta mais curta."}), 504

    if reply is None:
        return jsonify({"error": "Erro ao chamar o Hermes."}), 503


    # Consome créditos
    consume_result = consume_credits(user_id, 5, "consulta_agente")
    if not consume_result.get("success"):
        return jsonify({"error": "Erro ao consumir créditos"}), 500

    # Salva no histórico
    history.append({"role": "user",      "content": message, "ts": int(time.time())})
    history.append({"role": "assistant", "content": reply,   "ts": int(time.time())})
    # Mantém apenas os últimos 200 pares
    if len(history) > 400:
        history = history[-400:]
    with open(history_path, "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    log("INFO", f"[{session['username']}] [Agent] Consulta realizada. Créditos restantes: {consume_result.get('new_balance', 'N/A')}")
    return jsonify({
        "reply": reply,
        "history_len": len(history) // 2,
        "credits_remaining": consume_result.get('new_balance', 0)
    })

@app.route("/agent/history")
@login_required
def agent_history():
    user_id = session['user_id']
    history_path = os.path.join(IRIS_DIR, f"agent_history_{user_id}.json")
    if os.path.exists(history_path):
        with open(history_path) as f:
            history = json.load(f)
    else:
        history = []
    return jsonify(history[-40:])  # últimas 20 trocas

@app.route("/agent/clear", methods=["POST"])
@login_required
def agent_clear():
    user_id = session['user_id']
    history_path = os.path.join(IRIS_DIR, f"agent_history_{user_id}.json")
    with open(history_path, "w") as f:
        json.dump([], f)
    log("INFO", f"[{session['username']}] Histórico do agente apagado")
    return jsonify({"status": "ok"})


# ── Headers de segurança HTTP (aplicados a toda resposta) ──────────────────
@app.after_request
def set_security_headers(response):
    # Evita que a página seja carregada dentro de um <iframe> de outro site (clickjacking)
    response.headers['X-Frame-Options'] = 'DENY'
    # Impede o navegador de "adivinhar" o tipo de conteúdo (mitiga certos XSS)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # Controla quanta informação de origem é enviada em requisições para outros sites
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    # Content-Security-Policy: restringe de onde scripts/estilos podem ser carregados.
    # 'unsafe-inline' é necessário pois os templates atuais usam <script> e style inline;
    # idealmente isso deve ser migrado para arquivos externos no futuro.
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    # HSTS: força HTTPS em todas as próximas visitas (só faz sentido se o site
    # já estiver servido via HTTPS — habilitar apenas em produção)
    if os.environ.get('FLASK_ENV') == 'production':
        response.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains'
    return response


if __name__ == "__main__":
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    if debug_mode:
        print("⚠️  Rodando em modo DEBUG. Nunca use isso em produção (exposição de RCE via debugger).")
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)
