import os
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta
from iris_core import IRIS_DIR, log

# Tenta usar Argon2id (padrão recomendado para senhas — resistente a GPUs/ASICs).
# Se argon2-cffi não estiver instalado, cai silenciosamente para PBKDF2-SHA256
# (ainda seguro, só mais vulnerável a força bruta com hardware especializado).
try:
    from argon2 import PasswordHasher as _ArgonHasher
    from argon2.exceptions import VerifyMismatchError as _VerifyMismatchError
    _ARGON = _ArgonHasher(time_cost=2, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)
    _ARGON_AVAILABLE = True
    log("INFO", "Argon2id disponível — usando para hashing de senhas.")
except ImportError:
    _ARGON_AVAILABLE = False
    log("WARN", "argon2-cffi não encontrado. Usando PBKDF2-SHA256. "
                "Instale com: pip install argon2-cffi --break-system-packages")

DB_PATH = os.path.join(IRIS_DIR, "iris_users.db")

def get_db():
    """Retorna conexão com o banco de dados."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=15000;")
    return conn

def init_db():
    """Inicializa o banco de dados com as tabelas necessárias."""
    conn = get_db()
    c = conn.cursor()
    
    # Tabela de usuários
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabela de créditos
    c.execute('''
        CREATE TABLE IF NOT EXISTS credits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            balance INTEGER DEFAULT 500,
            monthly_limit INTEGER DEFAULT 500,
            last_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    
    # Tabela de assinaturas (planos)
    c.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            plan_type TEXT DEFAULT 'free',
            status TEXT DEFAULT 'active',
            mercado_pago_id TEXT,
            start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            end_date TIMESTAMP,
            auto_renew INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    
    # Tabela de histórico de consumo de créditos
    c.execute('''
        CREATE TABLE IF NOT EXISTS credit_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            reason TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    
    # Tabela de transações Mercado Pago
    c.execute('''
        CREATE TABLE IF NOT EXISTS mp_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            mp_payment_id TEXT UNIQUE,
            plan_type TEXT,
            amount REAL,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    # Tabela de tokens de recuperação de senha
    c.execute('''
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    # Tabela de tentativas de login (proteção contra força bruta)
    c.execute('''
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            ip_address TEXT,
            success INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_login_attempts_username ON login_attempts(username, created_at)')
    
    conn.commit()
    conn.close()
    log("INFO", "Banco de dados inicializado com sucesso.")

def hash_password(password: str) -> str:
    """Gera hash seguro da senha.
    
    Usa Argon2id se disponível (preferido — resiste a ataques de GPU).
    Caso contrário, usa PBKDF2-SHA256 com 200.000 iterações como fallback.
    O prefixo do hash indica o algoritmo usado, permitindo migração gradual.
    """
    if _ARGON_AVAILABLE:
        return _ARGON.hash(password)  # começa com '$argon2id$'
    else:
        salt = secrets.token_hex(16)
        pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200_000)
        return f"pbkdf2${salt}${pwd_hash.hex()}"

def verify_password(password: str, password_hash: str) -> bool:
    """Verifica senha contra o hash armazenado.
    
    Detecta automaticamente o algoritmo pelo prefixo do hash,
    permitindo que usuários com hash antigo (PBKDF2) façam login
    enquanto novos hashes já usam Argon2id.
    Usa comparação em tempo constante para evitar timing attacks.
    """
    try:
        if password_hash.startswith('$argon2'):
            if not _ARGON_AVAILABLE:
                log("ERROR", "Hash Argon2id no banco mas argon2-cffi não instalado.")
                return False
            try:
                return _ARGON.verify(password_hash, password)
            except _VerifyMismatchError:
                return False
        elif password_hash.startswith('pbkdf2$'):
            _, salt, stored = password_hash.split('$')
            new_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200_000)
            return secrets.compare_digest(new_hash.hex(), stored)
        else:
            # Hash legado (formato antigo 'salt$hash' sem prefixo)
            salt, stored = password_hash.split('$')
            new_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100_000)
            return secrets.compare_digest(new_hash.hex(), stored)
    except Exception:
        return False

def create_user(username, email, password):
    """Cria novo usuário."""
    try:
        conn = get_db()
        c = conn.cursor()
        
        password_hash = hash_password(password)
        
        c.execute('''
            INSERT INTO users (username, email, password_hash)
            VALUES (?, ?, ?)
        ''', (username, email, password_hash))
        
        user_id = c.lastrowid
        
        # Cria registro de créditos
        c.execute('''
            INSERT INTO credits (user_id, balance, monthly_limit)
            VALUES (?, ?, ?)
        ''', (user_id, 500, 500))
        
        # Cria registro de assinatura
        c.execute('''
            INSERT INTO subscriptions (user_id, plan_type, status)
            VALUES (?, ?, ?)
        ''', (user_id, 'free', 'active'))
        
        conn.commit()
        conn.close()
        log("INFO", f"Usuário criado: {username}")
        return {"success": True, "user_id": user_id}
    except sqlite3.IntegrityError as e:
        log("WARN", f"Erro ao criar usuário: {str(e)}")
        return {"success": False, "error": "Usuário ou email já existe"}
    except Exception as e:
        log("ERROR", f"Erro ao criar usuário: {str(e)}")
        return {"success": False, "error": str(e)}

def authenticate_user(username, password, ip_address=None):
    """Autentica usuário e retorna dados se válido.

    Implementa proteção contra força bruta: após várias tentativas
    falhas seguidas para o mesmo username, bloqueia novas tentativas
    por um período crescente, mesmo que a senha esteja correta."""
    MAX_ATTEMPTS = 5
    LOCKOUT_MINUTES = 15
    WINDOW_MINUTES = 15

    try:
        conn = get_db()
        c = conn.cursor()

        # Conta tentativas falhas recentes para este username
        c.execute('''
            SELECT COUNT(*) as cnt FROM login_attempts
            WHERE username = ? AND success = 0
            AND created_at > datetime('now', ?)
        ''', (username, f'-{WINDOW_MINUTES} minutes'))
        recent_failures = c.fetchone()['cnt']

        if recent_failures >= MAX_ATTEMPTS:
            conn.close()
            log("WARN", f"Login bloqueado por excesso de tentativas: {username}")
            return {"success": False, "error": f"Muitas tentativas falhas. Tente novamente em {LOCKOUT_MINUTES} minutos."}

        c.execute('SELECT * FROM users WHERE username = ?', (username,))
        user = c.fetchone()

        is_valid = user and verify_password(password, user['password_hash'])

        # Registra a tentativa (sucesso ou falha) para controle de força bruta
        c.execute('''
            INSERT INTO login_attempts (username, ip_address, success)
            VALUES (?, ?, ?)
        ''', (username, ip_address, 1 if is_valid else 0))
        conn.commit()
        conn.close()

        if is_valid:
            return {
                "success": True,
                "user_id": user['id'],
                "username": user['username'],
                "email": user['email']
            }
        else:
            return {"success": False, "error": "Usuário ou senha inválidos"}
    except Exception as e:
        log("ERROR", f"Erro ao autenticar: {str(e)}")
        return {"success": False, "error": str(e)}

def get_user_by_email(email):
    """Busca usuário pelo email."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE email = ?', (email,))
        user = c.fetchone()
        conn.close()
        return dict(user) if user else None
    except Exception as e:
        log("ERROR", f"Erro ao buscar usuário por email: {str(e)}")
        return None

def create_password_reset_token(email):
    """Gera um token de recuperação de senha válido por 1 hora."""
    try:
        user = get_user_by_email(email)
        if not user:
            # Não revela se o email existe ou não (segurança)
            return {"success": True}

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(hours=1)

        conn = get_db()
        c = conn.cursor()
        c.execute('''
            INSERT INTO password_resets (user_id, token, expires_at)
            VALUES (?, ?, ?)
        ''', (user['id'], token, expires_at))
        conn.commit()
        conn.close()

        log("INFO", f"Token de recuperação gerado para: {email}")
        return {"success": True, "token": token, "username": user['username']}
    except Exception as e:
        log("ERROR", f"Erro ao gerar token de recuperação: {str(e)}")
        return {"success": False, "error": str(e)}

def validate_reset_token(token):
    """Verifica se um token de recuperação é válido e não expirou."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            SELECT pr.*, u.username, u.email FROM password_resets pr
            JOIN users u ON u.id = pr.user_id
            WHERE pr.token = ? AND pr.used = 0
        ''', (token,))
        row = c.fetchone()
        conn.close()

        if not row:
            return {"valid": False, "error": "Token inválido ou já utilizado"}

        expires_at = datetime.fromisoformat(str(row['expires_at']))
        if datetime.now() > expires_at:
            return {"valid": False, "error": "Token expirado. Solicite uma nova recuperação"}

        return {"valid": True, "user_id": row['user_id'], "username": row['username']}
    except Exception as e:
        log("ERROR", f"Erro ao validar token: {str(e)}")
        return {"valid": False, "error": str(e)}

def reset_password_with_token(token, new_password):
    """Redefine a senha do usuário usando um token válido."""
    try:
        check = validate_reset_token(token)
        if not check.get("valid"):
            return {"success": False, "error": check.get("error", "Token inválido")}

        password_hash = hash_password(new_password)

        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                  (password_hash, check['user_id']))
        c.execute('UPDATE password_resets SET used = 1 WHERE token = ?', (token,))
        conn.commit()
        conn.close()

        log("INFO", f"Senha redefinida para usuário: {check['username']}")
        return {"success": True}
    except Exception as e:
        log("ERROR", f"Erro ao redefinir senha: {str(e)}")
        return {"success": False, "error": str(e)}

def get_user_by_id(user_id):
    """Retorna dados do usuário."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        user = c.fetchone()
        conn.close()
        return dict(user) if user else None
    except:
        return None

def get_user_credits(user_id):
    """Retorna saldo de créditos do usuário."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM credits WHERE user_id = ?', (user_id,))
        credits = c.fetchone()
        conn.close()
        return dict(credits) if credits else None
    except:
        return None

def consume_credits(user_id, amount, reason="consulta_agente"):
    """Consome créditos do usuário."""
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Verifica saldo
        c.execute('SELECT balance FROM credits WHERE user_id = ?', (user_id,))
        credits = c.fetchone()
        
        if not credits or credits['balance'] < amount:
            conn.close()
            return {"success": False, "error": "Créditos insuficientes"}
        
        # Deduz créditos
        c.execute('''
            UPDATE credits 
            SET balance = balance - ? 
            WHERE user_id = ?
        ''', (amount, user_id))
        
        # Registra no histórico
        c.execute('''
            INSERT INTO credit_history (user_id, amount, reason)
            VALUES (?, ?, ?)
        ''', (user_id, -amount, reason))
        
        conn.commit()
        conn.close()
        
        log("INFO", f"Usuário {user_id}: {amount} créditos consumidos ({reason})")
        return {"success": True, "new_balance": credits['balance'] - amount}
    except Exception as e:
        log("ERROR", f"Erro ao consumir créditos: {str(e)}")
        return {"success": False, "error": str(e)}

def add_credits(user_id, amount, reason="compra_plano"):
    """Adiciona créditos ao usuário."""
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('''
            UPDATE credits 
            SET balance = balance + ? 
            WHERE user_id = ?
        ''', (amount, user_id))
        
        c.execute('''
            INSERT INTO credit_history (user_id, amount, reason)
            VALUES (?, ?, ?)
        ''', (user_id, amount, reason))
        
        conn.commit()
        conn.close()
        
        log("INFO", f"Usuário {user_id}: {amount} créditos adicionados ({reason})")
        return {"success": True}
    except Exception as e:
        log("ERROR", f"Erro ao adicionar créditos: {str(e)}")
        return {"success": False, "error": str(e)}

def reset_monthly_credits(user_id):
    """Reseta créditos mensais se necessário."""
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('''
            SELECT last_reset, monthly_limit FROM credits WHERE user_id = ?
        ''', (user_id,))
        credits = c.fetchone()
        
        if not credits:
            conn.close()
            return False
        
        last_reset = datetime.fromisoformat(credits['last_reset'])
        now = datetime.now()
        
        # Se passou mais de 30 dias, reseta
        if (now - last_reset).days >= 30:
            c.execute('''
                UPDATE credits 
                SET balance = ?, last_reset = CURRENT_TIMESTAMP
                WHERE user_id = ?
            ''', (credits['monthly_limit'], user_id))
            
            conn.commit()
            conn.close()
            log("INFO", f"Créditos mensais resetados para usuário {user_id}")
            return True
        
        conn.close()
        return False
    except Exception as e:
        log("ERROR", f"Erro ao resetar créditos: {str(e)}")
        return False

def get_user_subscription(user_id):
    """Retorna dados da assinatura do usuário."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM subscriptions WHERE user_id = ?', (user_id,))
        sub = c.fetchone()
        conn.close()
        return dict(sub) if sub else None
    except:
        return None

def update_subscription(user_id, plan_type, mp_payment_id=None):
    """Atualiza assinatura do usuário."""
    try:
        conn = get_db()
        c = conn.cursor()
        
        if plan_type == "monthly":
            end_date = datetime.now() + timedelta(days=30)
        elif plan_type == "annual":
            end_date = datetime.now() + timedelta(days=365)
        else:
            end_date = None
        
        c.execute('''
            UPDATE subscriptions 
            SET plan_type = ?, status = 'active', end_date = ?, mercado_pago_id = ?
            WHERE user_id = ?
        ''', (plan_type, end_date, mp_payment_id, user_id))
        
        conn.commit()
        conn.close()
        
        log("INFO", f"Assinatura atualizada para usuário {user_id}: {plan_type}")
        return {"success": True}
    except Exception as e:
        log("ERROR", f"Erro ao atualizar assinatura: {str(e)}")
        return {"success": False, "error": str(e)}

def payment_already_processed(mp_payment_id):
    """Verifica se um payment_id do Mercado Pago já foi processado antes,
    evitando que o mesmo pagamento seja usado mais de uma vez para gerar
    créditos (replay attack / reuso de payment_id)."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM mp_transactions WHERE mp_payment_id = ?', (mp_payment_id,))
        row = c.fetchone()
        conn.close()
        return row is not None
    except Exception as e:
        log("ERROR", f"Erro ao checar transação existente: {str(e)}")
        # Em caso de erro, trata como "já processado" por segurança
        # (evita creditar em caso de falha na checagem)
        return True

def create_mp_transaction(user_id, mp_payment_id, plan_type, amount, status):
    """Registra transação do Mercado Pago."""
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO mp_transactions (user_id, mp_payment_id, plan_type, amount, status)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, mp_payment_id, plan_type, amount, status))
        
        conn.commit()
        conn.close()
        
        log("INFO", f"Transação MP registrada: {mp_payment_id} para usuário {user_id}")
        return {"success": True}
    except Exception as e:
        log("ERROR", f"Erro ao registrar transação MP: {str(e)}")
        return {"success": False, "error": str(e)}

def get_credit_history(user_id, limit=50):
    """Retorna histórico de consumo de créditos."""
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('''
            SELECT * FROM credit_history 
            WHERE user_id = ? 
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (user_id, limit))
        
        history = [dict(row) for row in c.fetchall()]
        conn.close()
        return history
    except:
        return []

# Inicializa banco de dados na importação
if not os.path.exists(DB_PATH):
    init_db()
