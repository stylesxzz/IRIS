#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# setup_hermes.sh — Instala e configura o Hermes Agent para o IRIS
# Versão Ollama — sem necessidade de API key
# Execute no Termux: bash setup_hermes.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

echo -e "${BOLD}${RED}"
echo "  ██╗██████╗ ██╗███████╗"
echo "  ██║██╔══██╗██║██╔════╝"
echo "  ██║██████╔╝██║███████╗"
echo "  ██║██╔══██╗██║╚════██║"
echo "  ██║██║  ██║██║███████║"
echo "  ╚═╝╚═╝  ╚═╝╚═╝╚══════╝"
echo -e "${NC}${CYAN}  Hermes Agent Setup — IRIS Security Platform (Ollama)${NC}"
echo ""

# ── 1. Verificar Ollama ───────────────────────────────────────────────────────
echo -e "${YELLOW}[1/5] Verificando Ollama...${NC}"

if ! command -v ollama &>/dev/null; then
  echo -e "${RED}✗ Ollama não encontrado. Instale primeiro:${NC}"
  echo -e "  ${CYAN}curl -fsSL https://ollama.com/install.sh | bash${NC}"
  exit 1
fi

# Verifica se o Ollama está rodando
if ! curl -s http://localhost:11434 &>/dev/null; then
  echo -e "${YELLOW}⚠ Ollama não está rodando. Iniciando em background...${NC}"
  ollama serve &>/dev/null &
  sleep 3
fi

echo -e "${GREEN}✓ Ollama disponível.${NC}"

# ── 2. Verificar modelo Mistral ───────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[2/5] Verificando modelo Mistral...${NC}"

OLLAMA_MODEL="iris-mistral"

if ollama list 2>/dev/null | grep -q "$OLLAMA_MODEL"; then
  echo -e "${GREEN}✓ Modelo '$OLLAMA_MODEL' já disponível.${NC}"
else
  # Tenta encontrar o .gguf em downloads
  GGUF_FILE=$(ls ~/downloads/*.gguf 2>/dev/null | head -1)

  if [ -n "$GGUF_FILE" ]; then
    echo -e "${CYAN}Importando modelo local: $GGUF_FILE${NC}"
    echo "FROM $GGUF_FILE" > /tmp/Modelfile_iris
    ollama create "$OLLAMA_MODEL" -f /tmp/Modelfile_iris
    echo -e "${GREEN}✓ Modelo '$OLLAMA_MODEL' criado.${NC}"
  else
    echo -e "${RED}✗ Nenhum arquivo .gguf encontrado em ~/downloads/${NC}"
    echo -e "  Baixe o Mistral e coloque em ~/downloads/ antes de continuar."
    exit 1
  fi
fi

# ── 3. Instala o Hermes ───────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[3/5] Instalando o Hermes Agent...${NC}"

if command -v hermes &>/dev/null; then
  echo -e "${GREEN}✓ Hermes já instalado: $(hermes --version 2>/dev/null || echo 'versão desconhecida')${NC}"
else
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
  export PATH="$HOME/.hermes/bin:$PATH"
  echo 'export PATH="$HOME/.hermes/bin:$PATH"' >> ~/.bashrc 2>/dev/null || true
  echo 'export PATH="$HOME/.hermes/bin:$PATH"' >> ~/.bash_profile 2>/dev/null || true
  echo -e "${GREEN}✓ Hermes instalado.${NC}"
fi

HERMES_BIN=$(command -v hermes || echo "$HOME/.hermes/bin/hermes")

# ── 4. Cria e configura o profile iris-agent ──────────────────────────────────
echo ""
echo -e "${YELLOW}[4/5] Configurando profile iris-agent com Ollama...${NC}"

HERMES_DIR="$HOME/.hermes"
mkdir -p "$HERMES_DIR"

"$HERMES_BIN" profile create iris-agent 2>/dev/null || true
"$HERMES_BIN" -p iris-agent config set provider ollama     2>/dev/null || true
"$HERMES_BIN" -p iris-agent config set model "$OLLAMA_MODEL" 2>/dev/null || true
"$HERMES_BIN" -p iris-agent config set memory.provider sqlite 2>/dev/null || true

# Salva variáveis de ambiente para o app.py
HERMES_ENV="$HERMES_DIR/.env"
grep -q "HERMES_PROVIDER" "$HERMES_ENV" 2>/dev/null || echo "HERMES_PROVIDER=ollama" >> "$HERMES_ENV"
grep -q "HERMES_MODEL" "$HERMES_ENV" 2>/dev/null || echo "HERMES_MODEL=$OLLAMA_MODEL" >> "$HERMES_ENV"

echo -e "${GREEN}✓ Profile configurado: provider=ollama, model=$OLLAMA_MODEL${NC}"

# ── 5. Copia o AGENT.md (personalidade) ──────────────────────────────────────
echo ""
echo -e "${YELLOW}[5/5] Configurando personalidade de especialista em segurança...${NC}"

IRIS_DIR="$(dirname "$(realpath "$0")")"
PROFILE_DIR="$HERMES_DIR/profiles/iris-agent"
mkdir -p "$PROFILE_DIR"

if [ -f "$IRIS_DIR/AGENT.md" ]; then
  cp "$IRIS_DIR/AGENT.md" "$PROFILE_DIR/AGENT.md"
  echo -e "${GREEN}✓ AGENT.md copiado para o profile.${NC}"
else
  cat > "$PROFILE_DIR/AGENT.md" << 'AGENTEOF'
# IRIS Security Agent

Você é o agente de segurança cibernética da plataforma IRIS, chamado IRIS Agent.
Especialista em pentest, OSINT, análise de vulnerabilidades, forense e engenharia reversa.
Responda sempre em português brasileiro, de forma técnica e direta.
Quando receber saídas de ferramentas, analise e sugira próximos passos com comandos prontos.
AGENTEOF
  echo -e "${GREEN}✓ AGENT.md criado.${NC}"
fi

# ── Teste final ───────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}Testando o agente...${NC}"
REPLY=$("$HERMES_BIN" ask -p iris-agent --no-stream "Responda só: IRIS online." 2>/dev/null || echo "ERRO")

if echo "$REPLY" | grep -qi "IRIS\|online"; then
  echo -e "${GREEN}✓ Agente respondendo: ${REPLY:0:80}${NC}"
else
  echo -e "${YELLOW}⚠ Resposta: $REPLY${NC}"
  echo -e "${YELLOW}  Se der erro, verifique se o Ollama está rodando: ollama serve${NC}"
fi

# ── Resumo ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}══════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  Setup concluído! 🎯${NC}"
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo ""
echo -e "  ${CYAN}Profile:${NC}   iris-agent"
echo -e "  ${CYAN}Provider:${NC}  ollama (local, sem API key)"
echo -e "  ${CYAN}Modelo:${NC}    $OLLAMA_MODEL"
echo -e "  ${CYAN}Memória:${NC}   SQLite local (~/.hermes/profiles/iris-agent/)"
echo ""
echo -e "  Certifique-se que o Ollama está rodando:"
echo -e "  ${BOLD}ollama serve &${NC}"
echo ""
echo -e "  Depois inicie o IRIS:"
echo -e "  ${BOLD}python3 app.py${NC}"
echo ""
echo -e "  Acesse: ${BOLD}http://127.0.0.1:5000/agent${NC}"
echo ""
