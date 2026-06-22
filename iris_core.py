
import os
import subprocess
import platform
import re
import logging
import json
import datetime

# Configuração de logging
IRIS_DIR = os.path.expanduser("~/.iris")
IRIS_LOG = os.path.join(IRIS_DIR, "iris.log")
IRIS_AUDIT_LOG = os.path.join(IRIS_DIR, "iris_audit.jsonl")  # log estruturado JSON Lines
TOOLS_CONF = os.path.join(IRIS_DIR, "tools.conf")

# Garante que a pasta ~/.iris (e o arquivo de log) existam ANTES do logging
os.makedirs(IRIS_DIR, exist_ok=True)
if not os.path.exists(IRIS_LOG):
    open(IRIS_LOG, 'a').close()
if not os.path.exists(IRIS_AUDIT_LOG):
    open(IRIS_AUDIT_LOG, 'a').close()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(IRIS_LOG),
        logging.StreamHandler()
    ]
)

# Níveis de segurança que disparam entrada no audit log estruturado (JSON Lines)
_SECURITY_LEVELS = {"WARN", "ERROR", "AUDIT"}

def log(level, message, extra: dict | None = None):
    """Log combinado: texto legível + JSON Lines para níveis de segurança.
    
    O arquivo iris_audit.jsonl contém uma linha JSON por evento de segurança,
    facilitando ingestão por ferramentas como jq, Grafana Loki, ELK, etc.
    """
    if level == "INFO":
        logging.info(message)
    elif level == "WARN":
        logging.warning(message)
    elif level == "ERROR":
        logging.error(message)
    elif level == "OK":
        logging.info(f"[OK] {message}")
    elif level == "SKIP":
        logging.info(f"[SKIP] {message}")
    elif level == "AUDIT":
        logging.warning(f"[AUDIT] {message}")
    else:
        logging.info(message)

    # Grava evento de segurança no audit log estruturado
    if level in _SECURITY_LEVELS:
        entry = {
            "ts": datetime.datetime.utcnow().isoformat() + "Z",
            "level": level,
            "msg": message,
        }
        if extra:
            entry.update(extra)
        try:
            with open(IRIS_AUDIT_LOG, 'a') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass  # Não deixa falha de log quebrar o fluxo principal

def init_dirs():
    os.makedirs(IRIS_DIR, exist_ok=True)
    os.makedirs(os.path.join(IRIS_DIR, "cache"), exist_ok=True)
    os.makedirs(os.path.join(IRIS_DIR, "tools"), exist_ok=True)
    os.makedirs(os.path.expanduser("~/.local/bin"), exist_ok=True)
    if not os.path.exists(IRIS_LOG):
        open(IRIS_LOG, 'a').close()
    log("INFO", "Diretórios IRIS inicializados.")

def cmd_exists(cmd):
    # Usa shutil.which em vez de "shell=True" com interpolação de string:
    # which() não passa por um shell, então não há risco de shell injection
    # mesmo que 'cmd' contenha caracteres como ; | & $() etc.
    import shutil
    return shutil.which(cmd) is not None

def run_priv(command_args):
    if os.geteuid() == 0 or os.environ.get("ENV_TYPE") == "termux":
        return subprocess.run(command_args, capture_output=True, text=True)
    elif cmd_exists("sudo"):
        return subprocess.run(["sudo"] + command_args, capture_output=True, text=True)
    else:
        return subprocess.run(command_args, capture_output=True, text=True)

def detect_env():
    if os.path.isdir("/data/data/com.termux") or os.environ.get("TERMUX_VERSION"):
        os.environ["ENV_TYPE"] = "termux"
        os.environ["PKG_MGR"] = "pkg"
        os.environ["SUDO"] = ""
        log("INFO", "Ambiente detectado: Termux.")
        return

    if cmd_exists("apt"):
        os.environ["ENV_TYPE"] = "debian"
        os.environ["PKG_MGR"] = "apt"
        os.environ["SUDO"] = "sudo"
        log("INFO", "Ambiente detectado: Debian/Ubuntu.")
    elif cmd_exists("pacman"):
        os.environ["ENV_TYPE"] = "arch"
        os.environ["PKG_MGR"] = "pacman"
        os.environ["SUDO"] = "sudo"
        log("INFO", "Ambiente detectado: Arch Linux.")
    elif cmd_exists("dnf"):
        os.environ["ENV_TYPE"] = "fedora"
        os.environ["PKG_MGR"] = "dnf"
        os.environ["SUDO"] = "sudo"
        log("INFO", "Ambiente detectado: Fedora.")
    else:
        os.environ["ENV_TYPE"] = "unknown"
        os.environ["PKG_MGR"] = "apt" # Default to apt as a fallback
        os.environ["SUDO"] = "sudo"
        log("WARN", "Ambiente desconhecido. Usando apt como gerenciador de pacotes padrão.")

def check_internet():
    try:
        subprocess.check_output(["curl", "-fsI", "--max-time", "5", "https://google.com"], stderr=subprocess.PIPE)
        os.environ["ONLINE"] = "1"
        log("INFO", "Conexão com a internet: ONLINE.")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        try:
            subprocess.check_output(["ping", "-c", "1", "-W", "3", "8.8.8.8"], stderr=subprocess.PIPE)
            os.environ["ONLINE"] = "1"
            log("INFO", "Conexão com a internet: ONLINE (via ping).")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            os.environ["ONLINE"] = "0"
            log("ERROR", "Conexão com a internet: OFFLINE.")
            return False

def repo_has_pkg(pkg_name):
    pkg_mgr = os.environ.get("PKG_MGR")
    if pkg_mgr == "apt":
        return subprocess.call(["apt-cache", "show", pkg_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE) == 0
    elif pkg_mgr == "pkg":
        return subprocess.call(["pkg", "show", pkg_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE) == 0
    elif pkg_mgr == "pacman":
        return subprocess.call(["pacman", "-Si", pkg_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE) == 0
    elif pkg_mgr == "dnf":
        return subprocess.call(["dnf", "info", pkg_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE) == 0
    return False

def get_pkg_version(pkg_name):
    pkg_mgr = os.environ.get("PKG_MGR")
    version = "n/a"
    if pkg_mgr in ["apt", "pkg"]:
        result = subprocess.run(["dpkg-query", "-W", "-f=${Version}\n", pkg_name], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout:
            version = result.stdout.strip().split('\n')[0]
    elif pkg_mgr == "pacman":
        result = subprocess.run(["pacman", "-Q", pkg_name], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout:
            version = result.stdout.strip().split()[1]
    elif pkg_mgr == "dnf":
        result = subprocess.run(["rpm", "-q", "--qf", "%{VERSION}\n", pkg_name], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout:
            version = result.stdout.strip()
    return version

def get_repo_version(pkg_name):
    pkg_mgr = os.environ.get("PKG_MGR")
    version = "n/a"
    if pkg_mgr == "apt":
        result = subprocess.run(["apt-cache", "policy", pkg_name], capture_output=True, text=True)
        match = re.search(r"Candidate:\s*(\S+)", result.stdout)
        if match: version = match.group(1)
    elif pkg_mgr == "pkg":
        result = subprocess.run(["pkg", "show", pkg_name], capture_output=True, text=True)
        match = re.search(r"Version:\s*(\S+)", result.stdout)
        if match: version = match.group(1)
    elif pkg_mgr == "pacman":
        result = subprocess.run(["pacman", "-Si", pkg_name], capture_output=True, text=True)
        match = re.search(r"Version\s*:\s*(\S+)", result.stdout)
        if match: version = match.group(1)
    elif pkg_mgr == "dnf":
        result = subprocess.run(["dnf", "info", pkg_name], capture_output=True, text=True)
        match = re.search(r"Version\s*:\s*(\S+)", result.stdout)
        if match: version = match.group(1)
    return version

def get_bin_version(tool):
    for flag in ["--version", "-version", "-V", "version"]:
        try:
            result = subprocess.run([tool, flag], capture_output=True, text=True, timeout=5)
            match = re.search(r'\d+\.\d+(\.\d+)?', result.stdout + result.stderr)
            if match: return match.group(0)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return "n/a"

def make_wrapper(tool, repo_dir):
    wrapper_path = os.path.join(os.path.expanduser("~/.local/bin"), tool)
    # Prioridade: executável direto
    if os.path.exists(os.path.join(repo_dir, tool)) and os.access(os.path.join(repo_dir, tool), os.X_OK):
        os.symlink(os.path.join(repo_dir, tool), wrapper_path)
        os.chmod(wrapper_path, 0o755)
        return True

    # Prioridade: scripts Python/Bash
    for ext in [".py", ".sh", ""]:
        script_path = os.path.join(repo_dir, f"{tool}{ext}")
        if os.path.exists(script_path):
            with open(wrapper_path, "w") as f:
                if ext == ".py":
                    f.write(f"#!/usr/bin/env bash\ncd \"{repo_dir}\" && python3 \"{tool}{ext}\" \"$@\"\n")
                else:
                    f.write(f"#!/usr/bin/env bash\ncd \"{repo_dir}\" && ./{tool}{ext} \"$@\"\n")
            os.chmod(wrapper_path, 0o755)
            return True

    # Última tentativa: qualquer executável na raiz ou subdiretório
    for root, _, files in os.walk(repo_dir):
        for f in files:
            full_path = os.path.join(root, f)
            if os.access(full_path, os.X_OK) and tool in f:
                os.symlink(full_path, wrapper_path)
                os.chmod(wrapper_path, 0o755)
                return True
    return False

def _do_install(tool, pkg_name, method):
    log("INFO", f"Tentando instalar {tool} via {method}...")
    home_local_bin = os.path.expanduser("~/.local/bin")
    os.makedirs(home_local_bin, exist_ok=True)

    pkg_mgr = os.environ.get("PKG_MGR")
    sudo_cmd = [os.environ.get("SUDO")] if os.environ.get("SUDO") else []

    if method == "pkg":
        if not repo_has_pkg(pkg_name):
            log("WARN", f"'{pkg_name}' não existe no {pkg_mgr}. Ignorando.")
            return 2
        if pkg_mgr == "apt":
            result = run_priv(sudo_cmd + ["apt-get", "install", "-y", "--no-install-recommends", pkg_name])
        elif pkg_mgr == "pkg":
            result = run_priv(["pkg", "install", "-y", pkg_name])
        elif pkg_mgr == "pacman":
            result = run_priv(sudo_cmd + ["pacman", "-S", "--noconfirm", pkg_name])
        elif pkg_mgr == "dnf":
            result = run_priv(sudo_cmd + ["dnf", "install", "-y", pkg_name])
        else:
            log("ERROR", f"Gerenciador de pacotes '{pkg_mgr}' não suportado para instalação de '{tool}'.")
            return 1
        if result.returncode != 0:
            log("ERROR", f"Falha ao instalar {tool} via {pkg_mgr}: {result.stderr}")
            return 1

    elif method == "pip":
        if not (cmd_exists("pip3") or cmd_exists("pip")):
            log("WARN", "pip/pip3 não encontrado. Tentando instalar...")
            if pkg_mgr == "apt":
                run_priv(sudo_cmd + ["apt-get", "install", "-y", "python3-pip"])
            elif pkg_mgr == "pkg":
                run_priv(["pkg", "install", "-y", "python-pip"])
            else:
                log("ERROR", "Não foi possível instalar pip/pip3 automaticamente.")
                return 1
        
        pip_cmd = "pip3" if cmd_exists("pip3") else "pip"
        if not cmd_exists(pip_cmd):
            log("ERROR", "pip/pip3 ainda não disponível após tentativa de instalação.")
            return 1

        if cmd_exists("pipx"):
            result = subprocess.run(["pipx", "install", pkg_name], capture_output=True, text=True) or \
                     subprocess.run(["pipx", "upgrade", pkg_name], capture_output=True, text=True)
        else:
            result = subprocess.run([pip_cmd, "install", "--user", "--upgrade", "--break-system-packages", pkg_name], capture_output=True, text=True) or \
                     subprocess.run([pip_cmd, "install", "--user", "--upgrade", pkg_name], capture_output=True, text=True)
        
        if result.returncode != 0:
            log("ERROR", f"Falha ao instalar {tool} via pip: {result.stderr}")
            return 1
        os.environ["PATH"] = f"{home_local_bin}:{os.environ.get("PATH")}"

    elif method == "go":
        if not cmd_exists("go"):
            log("WARN", "Go não encontrado. Tentando instalar...")
            if pkg_mgr == "apt":
                run_priv(sudo_cmd + ["apt-get", "install", "-y", "golang"])
            elif pkg_mgr == "pkg":
                run_priv(["pkg", "install", "-y", "golang"])
            elif pkg_mgr == "pacman":
                run_priv(sudo_cmd + ["pacman", "-S", "--noconfirm", "go"])
            elif pkg_mgr == "dnf":
                run_priv(sudo_cmd + ["dnf", "install", "-y", "golang"])
            else:
                log("ERROR", "Não foi possível instalar Go.")
                return 1
        if not cmd_exists("go"):
            log("ERROR", "Go ainda não disponível após tentativa de instalação.")
            return 1
        
        os.environ["GOPATH"] = os.path.expanduser("~/go")
        os.environ["PATH"] = f"{os.path.expanduser("~/go/bin")}:{os.environ.get("PATH")}"
        result = subprocess.run(["go", "install", f"{pkg_name}@latest"], capture_output=True, text=True)
        if result.returncode != 0:
            log("ERROR", f"Falha ao instalar {tool} via go: {result.stderr}")
            return 1

    elif method == "git":
        repo_dir = os.path.join(IRIS_DIR, "tools", os.path.basename(pkg_name).replace(".git", ""))
        os.makedirs(os.path.join(IRIS_DIR, "tools"), exist_ok=True)

        if os.path.isdir(os.path.join(repo_dir, ".git")):
            log("INFO", f"Atualizando repositório: {os.path.basename(repo_dir)}")
            result = subprocess.run(["git", "-C", repo_dir, "pull", "--ff-only"], capture_output=True, text=True)
        else:
            log("INFO", f"Clonando: {pkg_name}")
            result = subprocess.run(["git", "clone", "--depth", "1", pkg_name, repo_dir], capture_output=True, text=True)
        
        if result.returncode != 0:
            log("ERROR", f"Falha ao clonar/atualizar {tool} via git: {result.stderr}")
            return 1

        # Instalar dependências Python se houver requirements.txt
        pip_cmd = "pip3" if cmd_exists("pip3") else "pip"
        for req_file in [os.path.join(repo_dir, "requirements.txt"), os.path.join(repo_dir, "requirements", "base.txt")]:
            if os.path.exists(req_file):
                log("INFO", f"Instalando dependências Python para {tool} de {os.path.basename(req_file)}...")
                subprocess.run([pip_cmd, "install", "--user", "--break-system-packages", "-r", req_file], capture_output=True, text=True) or \
                subprocess.run([pip_cmd, "install", "--user", "-r", req_file], capture_output=True, text=True)

        make_wrapper(tool, repo_dir)
        os.environ["PATH"] = f"{home_local_bin}:{os.environ.get("PATH")}"

    else:
        log("ERROR", f"Método de instalação '{method}' não suportado para '{tool}'.")
        return 1
    
    # Atualizar PATH após instalação
    os.environ["PATH"] = f"{home_local_bin}:{os.path.expanduser("~/go/bin")}:{IRIS_DIR}/tools/bin:{os.environ.get("PATH")}"
    return 0

def check_and_update_tool(tool, pkg_name=None, method="pkg"):
    pkg_name = pkg_name or tool
    
    if cmd_exists(tool):
        log("INFO", f"Ferramenta {tool} já instalada. Verificando atualizações...")
        current_version = get_bin_version(tool)

        if method == "pkg":
            repo_version = get_repo_version(pkg_name)
            installed_pkg_version = get_pkg_version(pkg_name)
            if installed_pkg_version != "n/a" and installed_pkg_version == repo_version:
                log("SKIP", f"{tool} (v{current_version}) já atualizado.")
                return 0
        
        log("INFO", f"Atualizando {tool}...")
        result = _do_install(tool, pkg_name, method)
        if result == 0 and cmd_exists(tool):
            log("OK", f"{tool} atualizado (v{get_bin_version(tool)}).")
            return 0
        else:
            log("ERROR", f"Falha ao atualizar: {tool}.")
            return 1
    else:
        log("INFO", f"Instalando {tool} ({method})...")
        result = _do_install(tool, pkg_name, method)
        
        os.environ["PATH"] = f"{os.path.expanduser("~/.local/bin")}:{os.path.expanduser("~/go/bin")}:{IRIS_DIR}/tools/bin:{os.environ.get("PATH")}"

        if result == 0 and cmd_exists(tool):
            log("OK", f"{tool} instalado (v{get_bin_version(tool)}).")
            return 0
        else:
            if method == "pkg":
                log("WARN", f"{tool}: não disponível no {os.environ.get("PKG_MGR")} (ignorado).")
                return 2
            log("ERROR", f"Falha ao instalar: {tool}.")
            return 1

def get_all_tools():
    if not os.path.exists(TOOLS_CONF):
        generate_tools_conf()
    with open(TOOLS_CONF, 'r') as f:
        tools = []
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and ':' in line:
                parts = line.split(':')
                if len(parts) >= 4:
                    tools.append({'bin': parts[0], 'pkg': parts[1], 'method': parts[2], 'category': parts[3]})
        return tools

def generate_tools_conf():
    os.makedirs(IRIS_DIR, exist_ok=True)
    content = """# IRIS tools.conf v3.3
# Formato: BINARIO:PACOTE_OU_URL:METODO:CATEGORIA
# Metodos: pkg | pip | go | git
# Apenas ferramentas compativeis e testadas

# -- RECON ----------------------------------
nmap:nmap:pkg:recon
masscan:masscan:pkg:recon
whois:whois:pkg:recon
theHarvester:https://github.com/laramies/theHarvester:git:recon
recon-ng:https://github.com/lanmaster53/recon-ng:git:recon
subfinder:github.com/projectdiscovery/subfinder/v2/cmd/subfinder:go:recon
amass:github.com/owasp-amass/amass/v4/...:go:recon
dnsx:github.com/projectdiscovery/dnsx/cmd/dnsx:go:recon
dmitry:dmitry:pkg:recon
shodan:shodan:pip:recon

# -- VULNERABILITY ANALYSIS -----------------
openvas:openvas:pkg:vulnerability_analysis
nmap:nmap:pkg:vulnerability_analysis
nikto:nikto:pkg:vulnerability_analysis
nuclei:github.com/projectdiscovery/nuclei/v3/cmd/nuclei:go:vulnerability_analysis
searchsploit:exploitdb:pkg:vulnerability_analysis
vulnscan:vulnscan:git:vulnerability_analysis
lynis:lynis:pkg:vulnerability_analysis
wpscan:wpscan:git:vulnerability_analysis
joomscan:joomscan:git:vulnerability_analysis

# -- DATABASE ASSESSMENT --------------------
sqlmap:sqlmap:pkg:database_assessment
mysql:mysql-client:pkg:database_assessment
psql:postgresql-client:pkg:database_assessment
mongo:mongodb-clients:pkg:database_assessment
redis-cli:redis-tools:pkg:database_assessment
nosqlmap:nosqlmap:git:database_assessment
dbpwaudit:dbpwaudit:git:database_assessment
oscanner:oscanner:pkg:database_assessment

# -- WEB ------------------------------------
sqlmap:sqlmap:pkg:web
nikto:nikto:pkg:web
gobuster:gobuster:pkg:web
ffuf:ffuf:pkg:web
wfuzz:wfuzz:pkg:web
whatweb:whatweb:pkg:web
wafw00f:wafw00f:pip:web
nuclei:github.com/projectdiscovery/nuclei/v3/cmd/nuclei:go:web
dirsearch:https://github.com/maurosoria/dirsearch:git:web
xsstrike:https://github.com/s0md3v/XSStrike:git:web

# -- PASSWORD -------------------------------
hydra:hydra:pkg:password
hashcat:hashcat:pkg:password
john:john:pkg:password
medusa:medusa:pkg:password
ncrack:ncrack:pkg:password
cewl:cewl:pkg:password
crunch:crunch:pkg:password

# -- WIRELESS -------------------------------
aircrack-ng:aircrack-ng:pkg:wireless
bettercap:bettercap:pkg:wireless
wifite:wifite:pkg:wireless
kismet:kismet:pkg:wireless
mdk4:mdk4:pkg:wireless

# -- EXPLOITATION ---------------------------
msfconsole:metasploit-framework:pkg:exploitation
searchsploit:exploitdb:pkg:exploitation
setoolkit:set:pkg:exploitation

# -- SNIFFING -------------------------------
tcpdump:tcpdump:pkg:sniffing
wireshark:wireshark:pkg:sniffing
ettercap:ettercap:pkg:sniffing
arpspoof:dsniff:pkg:sniffing
dsniff:dsniff:pkg:sniffing
mitmproxy:mitmproxy:pip:sniffing
macchanger:macchanger:pkg:sniffing
responder:responder:git:sniffing
scapy:scapy:pip:sniffing

# -- POST EXPLOITATION ----------------------
empire:powershell-empire:git:post_exploitation
bloodhound:bloodhound:git:post_exploitation
crackmapexec:crackmapexec:pip:post_exploitation
evil-winrm:evil-winrm:git:post_exploitation
impacket-scripts:impacket:pip:post_exploitation
mimikatz:mimikatz:git:post_exploitation
powersploit:powersploit:git:post_exploitation
linpeas:linpeas:git:post_exploitation
covenant:covenant:git:post_exploitation

# -- FORENSICS ------------------------------
autopsy:autopsy:pkg:forensics
volatility3:volatility3:pip:forensics
sleuthkit:sleuthkit:pkg:forensics
binwalk:binwalk:pkg:forensics
foremost:foremost:pkg:forensics
dc3dd:dc3dd:pkg:forensics
exiftool:libimage-exiftool-perl:pkg:forensics
bulk_extractor:bulk_extractor:pkg:forensics
ghidra:ghidra:git:forensics
scalpel:scalpel:pkg:forensics

# -- REVERSE ENGINEERING --------------------
ghidra:ghidra:git:reverse_engineering
radare2:radare2:pkg:reverse_engineering
gdb:gdb:pkg:reverse_engineering
objdump:binutils:pkg:reverse_engineering
ltrace:ltrace:pkg:reverse_engineering
strace:strace:pkg:reverse_engineering
apktool:apktool:git:reverse_engineering
jadx:jadx:git:reverse_engineering
pwndbg:pwndbg:git:reverse_engineering
cutter:cutter:git:reverse_engineering

# -- HARDWARE / ANDROID HACKING -------------
adb:android-tools:pkg:android_hacking
apktool:apktool:git:android_hacking
jadx:jadx:git:android_hacking
frida:frida-tools:pip:android_hacking
drozer:drozer:pip:android_hacking
objection:objection:pip:android_hacking
androwarn:androwarn:pip:android_hacking
mobsf:Mobile-Security-Framework-MobSF:git:android_hacking
flashrom:flashrom:pkg:android_hacking
openocd:openocd:pkg:android_hacking

# -- SOCIAL ENGINEERING ---------------------
setoolkit:setoolkit:git:social_engineering
gophish:gophish:git:social_engineering
evilginx2:evilginx2:git:social_engineering
king-phisher:king-phisher:git:social_engineering
zphisher:zphisher:git:social_engineering
wifiphisher:wifiphisher:git:social_engineering
beef-xss:beef-xss:git:social_engineering
maltego:maltego:pkg:social_engineering
credphish:credphish:git:social_engineering
social-engineer-toolkit:setoolkit:git:social_engineering

# -- REPORTING TOOLS ------------------------
dradis:dradis-framework:git:reporting
faraday:faraday:git:reporting
serpico:serpico:git:reporting
pwndoc:pwndoc:git:reporting
cherrytree:cherrytree:pkg:reporting
magictree:magictree:git:reporting
pandoc:pandoc:pkg:reporting
libreoffice:libreoffice:pkg:reporting
keepnote:keepnote:pkg:reporting
piperka:piperka:git:reporting

# -- MAINTENANCE / SYSTEM -------------------
tmux:tmux:pkg:system
htop:htop:pkg:system
curl:curl:pkg:system
wget:wget:pkg:system
git:git:pkg:system
python3:python3:pkg:system
pip3:python3-pip:pkg:system
vim:vim:pkg:system
screen:screen:pkg:system
net-tools:net-tools:pkg:system

# -- NETWORK SCANNING / ENUMERATION ---------
nmap:nmap:pkg:network_scanning
masscan:masscan:pkg:network_scanning
rustscan:rustscan:git:network_scanning
netdiscover:netdiscover:pkg:network_scanning
arp-scan:arp-scan:pkg:network_scanning
enum4linux:enum4linux:pkg:network_scanning
smbclient:samba-client:pkg:network_scanning
rpcclient:samba-common-bin:pkg:network_scanning
nbtscan:nbtscan:pkg:network_scanning
onesixtyone:onesixtyone:pkg:network_scanning

# -- CRYPTOGRAPHY / CRACKING ----------------
hashcat:hashcat:pkg:cryptography
john:john:pkg:cryptography
gpg:gnupg:pkg:cryptography
openssl:openssl:pkg:cryptography
hashid:hashid:pip:cryptography
haiti:haiti:git:cryptography
fcrackzip:fcrackzip:pkg:cryptography
pdfcrack:pdfcrack:pkg:cryptography
rar2john:john:pkg:cryptography
stegcracker:stegcracker:git:cryptography

# -- VOIP ATTACKS ---------------------------
sipvicious:sipvicious:git:voip
svwar:sipvicious:git:voip
svcrack:sipvicious:git:voip
wireshark:wireshark:pkg:voip
sngrep:sngrep:pkg:voip
sipp:sipp:pkg:voip
viproy:viproy-voipkit:git:voip
voiphopper:voiphopper:git:voip
ohrwurm:ohrwurm:git:voip
iaxflood:iaxflood:git:voip

# -- STRESS TESTING / DDOS ------------------
hping3:hping3:pkg:stress_testing
slowhttptest:slowhttptest:pkg:stress_testing
ab:apache2-utils:pkg:stress_testing
siege:siege:pkg:stress_testing
wrk:wrk:git:stress_testing
t50:t50:git:stress_testing
mdk4:mdk4:pkg:stress_testing
goldeneye:goldeneye:git:stress_testing
xerxes:xerxes:git:stress_testing
thc-ssl-dos:thc-ssl-dos:git:stress_testing

# -- FILE & DATA ANALYSIS -------------------
binwalk:binwalk:pkg:file_analysis
hexedit:hexedit:pkg:file_analysis
xxd:vim:pkg:file_analysis
file:file:pkg:file_analysis
strings:binutils:pkg:file_analysis
exiftool:libimage-exiftool-perl:pkg:file_analysis
steghide:steghide:pkg:file_analysis
foremost:foremost:pkg:file_analysis
pdfinfo:poppler-utils:pkg:file_analysis
bulk_extractor:bulk_extractor:pkg:file_analysis
"""
    with open(TOOLS_CONF, 'w') as f:
        f.write(content)
    log("INFO", f"Arquivo de configuração de ferramentas gerado em {TOOLS_CONF}.")


TOOLS_CONF_VERSION = "v3.3"

# Inicialização
init_dirs()
detect_env()
check_internet()

# Regenera tools.conf se não existe ou está desatualizado
_needs_regen = True
if os.path.exists(TOOLS_CONF):
    with open(TOOLS_CONF) as _f:
        _needs_regen = TOOLS_CONF_VERSION not in _f.readline()
if _needs_regen:
    generate_tools_conf()

# Exemplo de uso (para teste)
if __name__ == "__main__":
    print("\n--- Testando funções IRIS ---")
    print(f"Ambiente: {os.environ.get('ENV_TYPE')}")
    print(f"Gerenciador de pacotes: {os.environ.get('PKG_MGR')}")
    print(f"Conexão online: {os.environ.get('ONLINE')}")

    print("\n--- Verificando e instalando nmap ---")
    check_and_update_tool("nmap", "nmap", "pkg")

    print("\n--- Verificando e instalando theHarvester (git) ---")
    check_and_update_tool("theHarvester", "https://github.com/laramies/theHarvester", "git")

    print("\n--- Listando todas as ferramentas ---")
    tools = get_all_tools()
    for tool_info in tools:
        status = "Instalado" if cmd_exists(tool_info['bin']) else "Ausente"
        version = get_bin_version(tool_info['bin']) if status == "Instalado" else "n/a"
        print(f"  {tool_info['bin']}: {status} (v{version}) - Categoria: {tool_info['category']}")

    print("\n--- Conteúdo do log ---")
    with open(IRIS_LOG, 'r') as f:
        print(f.read())
