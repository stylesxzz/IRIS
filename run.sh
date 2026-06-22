#!/bin/bash

# Script de inicialização para IRIS Web no Termux
# Este script instala as dependências necessárias e inicia a aplicação Flask

set -e

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Função para imprimir mensagens
print_message() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Detectar ambiente
detect_env() {
    if [ -d "/data/data/com.termux" ] || [ -n "$TERMUX_VERSION" ]; then
        print_message "$GREEN" "[+] Ambiente detectado: Termux"
        return 0
    else
        print_message "$YELLOW" "[!] Aviso: Este script foi otimizado para Termux. Você está em outro ambiente."
        return 1
    fi
}

# Instalar dependências
install_dependencies() {
    print_message "$CYAN" "[*] Instalando dependências..."

    # Atualizar repositórios
    if command -v pkg &> /dev/null; then
        print_message "$CYAN" "[*] Atualizando repositórios (pkg)..."
        pkg update -y
        pkg upgrade -y
        
        # Instalar Python e pip
        print_message "$CYAN" "[*] Instalando Python 3 e pip..."
        pkg install -y python python-pip
        
        # Instalar ferramentas básicas
        print_message "$CYAN" "[*] Instalando ferramentas básicas..."
        pkg install -y curl wget git tmux vim
    elif command -v apt &> /dev/null; then
        print_message "$CYAN" "[*] Atualizando repositórios (apt)..."
        sudo apt-get update
        sudo apt-get upgrade -y
        
        # Instalar Python e pip
        print_message "$CYAN" "[*] Instalando Python 3 e pip..."
        sudo apt-get install -y python3 python3-pip
        
        # Instalar ferramentas básicas
        print_message "$CYAN" "[*] Instalando ferramentas básicas..."
        sudo apt-get install -y curl wget git tmux vim
    else
        print_message "$RED" "[-] Gerenciador de pacotes não encontrado. Instale manualmente Python 3 e pip."
        return 1
    fi

    # Instalar dependências Python
    print_message "$CYAN" "[*] Instalando dependências Python..."
    # No Termux, não devemos tentar atualizar o pip via pip, o pkg cuida disso.
    # Usamos --break-system-packages apenas se necessário em versões mais novas do Python, 
    # mas no Termux geralmente o pip install funciona direto ou via pkg.
    pip install flask requests || pip install flask requests --break-system-packages

    print_message "$GREEN" "[+] Dependências instaladas com sucesso!"
}

# Iniciar a aplicação Flask
start_flask_app() {
    print_message "$CYAN" "[*] Iniciando aplicação Flask..."
    
    # Obter o IP local
    local ip_address=$(hostname -I | awk '{print $1}')
    if [ -z "$ip_address" ]; then
        ip_address="127.0.0.1"
    fi
    
    # Aguardar um pouco para o servidor subir
    sleep 2

    # Abrir o navegador automaticamente (se disponível)
    # No Termux, termux-open é o padrão para abrir links
    if command -v termux-open &> /dev/null; then
        print_message "$CYAN" "[*] Abrindo navegador (Termux)..."
        termux-open "http://127.0.0.1:5000" &
    elif command -v xdg-open &> /dev/null; then
        print_message "$CYAN" "[*] Abrindo navegador..."
        xdg-open "http://127.0.0.1:5000" &
    elif command -v open &> /dev/null; then
        print_message "$CYAN" "[*] Abrindo navegador..."
        open "http://127.0.0.1:5000" &
    else
        print_message "$YELLOW" "[!] Navegador não encontrado. Acesse manualmente: http://127.0.0.1:5000"
    fi

    # Iniciar o servidor Flask
    print_message "$GREEN" "[+] Servidor Flask iniciado em http://${ip_address}:5000"
    print_message "$YELLOW" "[!] Pressione Ctrl+C para parar o servidor"
    python app.py
}

# Função principal
main() {
    print_message "$CYAN" "╔════════════════════════════════════════╗"
    print_message "$CYAN" "║     IRIS Web - Inicializador           ║"
    print_message "$CYAN" "║  Intelligent Recon & Intrusion System  ║"
    print_message "$CYAN" "╚════════════════════════════════════════╝"
    echo ""

    # Detectar ambiente
    detect_env

    # Instalar dependências
    install_dependencies

    # Iniciar aplicação
    start_flask_app
}

# Executar função principal
main
