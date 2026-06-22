<p align="center">
  <img src="Screenshot_20260615_182251_Samsung Browser.jpg" alt="IRIS Banner" width="100%">
</p>

<h1 align="center">IRIS — Intelligence & Recon Investigation Suite</h1>

<p align="center">
  <b>Plataforma web de gerenciamento de ferramentas de segurança e investigação assistida por IA</b><br>
  Projetada para profissionais de cibersegurança, equipes de pentest e pesquisadores de segurança.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/versão-3.0-red">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue">
  <img src="https://img.shields.io/badge/flask-2.3-lightgrey">
  <img src="https://img.shields.io/badge/licença-MIT-green">
  <img src="https://img.shields.io/badge/plataforma-Linux%20%7C%20Termux-orange">
</p>

---

## 📖 Índice

- [Visão Geral](#-visão-geral)
- [Funcionalidades](#-funcionalidades)
- [Screenshots](#-screenshots)
- [Instalação](#️-instalação)
- [Configuração](#-configuração)
- [Uso](#-uso)
- [Segurança](#-segurança)
- [Aviso Legal](#️-aviso-legal)

---

## 🔍 Visão Geral

**IRIS** é uma plataforma web completa para profissionais de segurança que precisam organizar, executar e documentar investigações de pentest em um único ambiente. O diferencial: um **mapa mental de investigação interativo** que conecta automaticamente os resultados de cada ferramenta em um grafo visual navegável, permitindo que toda a superfície de ataque fique visível e organizada.

O **Agente IRIS** (integrado via Hermes + modelo de IA configurável) atua como um especialista em segurança consultivo — analisa outputs de ferramentas, sugere próximos passos e auxilia na interpretação de vulnerabilidades.

---

## ⚡ Funcionalidades

- **🗂️ Gerenciamento de ferramentas por categoria** — Recon, Web, Exploitation, OSINT, Forense e mais
- **▶️ Execução com 1 clique** — roda qualquer ferramenta instalada diretamente pela interface
- **🧠 Mapa mental de investigação** — grafo interativo com pan, zoom e drag; nós conectados por ferramenta usada
- **🤖 Agente IRIS com IA** — assistente especialista em segurança com memória persistente por sessão
- **💳 Planos e créditos** — monetização via Mercado Pago integrada
- **🔐 Autenticação segura** — Argon2id, rate limiting, lockout, CSRF, recuperação de senha
- **📱 Interface responsiva** — funciona em desktop, tablet e celular (Android/Termux)
- **📊 Log de auditoria** — registros estruturados em JSON Lines para monitoramento

---

## 📸 Screenshots

|| Login | Menu | Mapa Mental |
|-------|------|-------------|
| 

![Login](Screenshot_20260620_030210_Chrome.jpg)

 | 

![Menu](Screenshot_20260615_225725_Samsung%20Browser.jpg)

 | 

![Mapa](Screenshot_20260621_121310_Chrome.jpg)

 |
---

## 🛠️ Instalação

### Pré-requisitos

- Python 3.10+
- Linux, Kali, Parrot, Ubuntu — ou Termux (Android)

### Instalação rápida

```bash
# 1. Clonar o repositório
git clone https://github.com/SEU_USUARIO/IRIS.git
cd IRIS

# 2. Instalar dependências Python
pip install -r requirements.txt

# 3. Configurar variáveis de ambiente
cp .env.example .env
nano .env   # preencha SECRET_KEY e as APIs que quiser usar

# 4. Iniciar a plataforma
python3 app.py
```

Acesse em: **http://127.0.0.1:5000**

### Termux (Android)

```bash
pkg update && pkg install python git
pip install -r requirements.txt
python3 app.py
```

---

## ⚙️ Configuração

Copie `.env.example` para `.env` e preencha:

| Variável | Obrigatório | Descrição |
|----------|-------------|-----------|
| `SECRET_KEY` | ✅ | Chave de criptografia da sessão Flask |
| `FLASK_ENV` | ✅ | `development` ou `production` |
| `MERCADO_PAGO_ACCESS_TOKEN` | ⚪ | Para ativar planos pagos |
| `ANTHROPIC_API_KEY` | ⚪ | Para o Agente IRIS via Claude |
| `OPENROUTER_API_KEY` | ⚪ | Alternativa gratuita de IA |

> O Agente IRIS também suporta modelos locais via **Ollama** (sem necessidade de API key).

---

## 🔒 Segurança

A IRIS implementa as seguintes proteções por padrão:

- **Argon2id** para hash de senhas (com fallback PBKDF2-SHA256)
- **CSRF tokens** em todas as requisições POST via `secureFetch()`
- **Rate limiting + lockout** após 5 tentativas de login falhas
- **Whitelist de ferramentas** — apenas binários cadastrados podem ser executados
- **Sanitização de argumentos** via `shlex` + filtro de injeção de shell
- **Session fixation fix** — ID de sessão regenerado após login
- **Headers HTTP**: CSP, HSTS, X-Frame-Options, X-Content-Type-Options
- **Audit log estruturado** em JSON Lines (`~/.iris/iris_audit.jsonl`)

---

## ⚠️ Aviso Legal

Esta ferramenta foi desenvolvida **exclusivamente para uso profissional legítimo**: auditorias de segurança autorizadas, pesquisa acadêmica, CTFs e treinamento em cibersegurança.

**O uso da IRIS para escanear, auditar ou atacar sistemas sem autorização prévia e por escrito do proprietário é ilegal** e pode resultar em sanções criminais e civis.

A responsabilidade pelo uso desta plataforma é inteiramente do operador. O desenvolvedor não se responsabiliza por danos causados pelo mau uso.

---

<p align="center">
  Desenvolvido com ❤️ para a comunidade de cibersegurança
</p>
