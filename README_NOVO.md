# IRIS Web Turbo v3.3 - Com Autenticação, Créditos e Mercado Pago

Sistema de pentest com agente IA Mistral (via Ollama), autenticação de usuários, sistema de créditos e integração com Mercado Pago para monetização.

## 🚀 Novidades da v3.3

- ✅ **Autenticação de Usuários**: Login/Registro com hash seguro de senhas
- ✅ **Sistema de Créditos**: 500 créditos/mês (gratuito), 5 créditos por consulta
- ✅ **Integração Mercado Pago**: Planos mensais (R$ 29,90) e anuais (R$ 299,90)
- ✅ **Agente Mistral via Ollama**: Removida dependência de ChatGPT/GPT-4o
- ✅ **Histórico por Usuário**: Cada usuário tem seu próprio histórico de conversas
- ✅ **Dashboard de Créditos**: Visualize saldo e histórico de consumo

## 📋 Requisitos

- Python 3.8+
- Ollama (para rodar o modelo Mistral localmente)
- Hermes Agent (para integração com o Ollama)
- SQLite (incluído no Python)

## 🔧 Instalação

### 1. Clone ou extraia o projeto

```bash
cd iris_project
```

### 2. Instale as dependências Python

```bash
pip install -r requirements.txt
```

### 3. Configure o Ollama e Hermes

Execute o script de setup:

```bash
bash setup_hermes.sh
```

Este script irá:
- Verificar se o Ollama está instalado
- Criar/importar o modelo `iris-mistral`
- Instalar o Hermes Agent
- Configurar o profile `iris-agent`

### 4. Configure as variáveis de ambiente

Copie o arquivo `.env.example` para `.env` e configure:

```bash
cp .env.example .env
```

Edite o `.env` com suas configurações, especialmente:

```
SECRET_KEY=sua-chave-secreta-aleatoria
MERCADO_PAGO_ACCESS_TOKEN=seu_token_aqui
MERCADO_PAGO_PUBLIC_KEY=sua_chave_publica_aqui
MERCADO_PAGO_WEBHOOK_URL=https://seu-dominio.com/payment/webhook
```

### 5. Inicie o servidor

```bash
python3 app.py
```

O servidor estará disponível em `http://localhost:5000`

## 🔐 Autenticação

### Primeiro Acesso

1. Acesse `http://localhost:5000/login`
2. Clique em "Criar conta"
3. Preencha usuário, email e senha
4. Faça login com suas credenciais

### Fluxo de Autenticação

- Senhas são armazenadas com hash PBKDF2 (100.000 iterações)
- Sessões são mantidas por 7 dias
- Histórico de conversas é isolado por usuário

## 💳 Sistema de Créditos

### Como Funciona

- **Plano Gratuito**: 500 créditos/mês (renovação automática)
- **Plano Mensal**: R$ 29,90 → 500 créditos/mês com renovação automática
- **Plano Anual**: R$ 299,90 → 6.000 créditos/ano (sem renovação automática)

### Consumo

- Cada consulta ao agente consome **5 créditos**
- Com 500 créditos = 100 consultas por mês
- Créditos são resetados automaticamente a cada 30 dias

### Visualizar Créditos

- Barra superior mostra saldo atual
- Página `/plans` mostra detalhes dos planos
- Rota `/credits/history` mostra histórico de consumo

## 💰 Integração Mercado Pago

### Configuração

1. Acesse [Mercado Pago Developer](https://www.mercadopago.com.br/developers)
2. Crie uma aplicação
3. Copie o `Access Token` e `Public Key`
4. Configure no `.env`:

```
MERCADO_PAGO_ACCESS_TOKEN=APP_USR-...
MERCADO_PAGO_PUBLIC_KEY=APP_USR-...
MERCADO_PAGO_WEBHOOK_URL=https://seu-dominio.com/payment/webhook
```

### Fluxo de Pagamento

1. Usuário clica em "Escolher plano" em `/plans`
2. Redireciona para checkout do Mercado Pago
3. Após aprovação, webhook confirma o pagamento
4. Créditos são adicionados automaticamente
5. Assinatura é atualizada no banco de dados

### Webhooks

O endpoint `/payment/webhook` processa notificações do Mercado Pago:

```
POST /payment/webhook
```

Certifique-se de configurar a URL de webhook na sua conta Mercado Pago.

## 🤖 Agente Mistral via Ollama

### Características

- Modelo: `iris-mistral` (customizado para segurança)
- Provider: Ollama (local, sem dependência de API externa)
- Memória: SQLite persistente por usuário
- Contexto: Últimas 12 trocas de conversa

### Personalidade

O agente é especialista em:
- Pentest e testes de invasão
- OSINT (Open Source Intelligence)
- Análise de vulnerabilidades
- Análise forense digital
- Engenharia reversa
- Criptografia

### Customizar Personalidade

Edite o arquivo `AGENT.md` para mudar o comportamento do agente. As mudanças serão refletidas após reiniciar o servidor.

## 📊 Banco de Dados

O sistema usa SQLite com as seguintes tabelas:

- **users**: Dados de usuários (username, email, password_hash)
- **credits**: Saldo de créditos por usuário
- **subscriptions**: Plano e status da assinatura
- **credit_history**: Histórico de consumo de créditos
- **mp_transactions**: Transações do Mercado Pago

Banco de dados está em `~/.iris/iris_users.db`

## 🔗 Rotas Principais

### Autenticação
- `POST /auth/register` - Registrar novo usuário
- `POST /auth/login` - Fazer login
- `POST /auth/logout` - Fazer logout

### Créditos
- `GET /credits/balance` - Saldo atual
- `GET /credits/history` - Histórico de consumo

### Pagamento
- `POST /payment/create-preference` - Criar preferência Mercado Pago
- `GET /payment/success` - Callback de sucesso
- `GET /payment/failure` - Callback de falha
- `POST /payment/webhook` - Webhook do Mercado Pago

### Agente
- `GET /agent` - Interface do agente
- `POST /agent/chat` - Enviar mensagem (consome 5 créditos)
- `GET /agent/history` - Histórico de conversas
- `POST /agent/clear` - Limpar histórico

### Planos
- `GET /plans` - Página de planos e preços
- `GET /user/subscription` - Dados da assinatura atual

## 🐛 Troubleshooting

### Erro: "Hermes não instalado"

```bash
bash setup_hermes.sh
```

### Erro: "Créditos insuficientes"

O usuário precisa de pelo menos 5 créditos para fazer uma consulta. Upgrade do plano em `/plans`.

### Erro: "Mercado Pago não configurado"

Verifique se as variáveis de ambiente estão configuradas no `.env`:
- `MERCADO_PAGO_ACCESS_TOKEN`
- `MERCADO_PAGO_PUBLIC_KEY`

### Ollama não está respondendo

```bash
ollama serve &
```

## 📝 Logs

Logs são salvos em `~/.iris/iris.log`. Para visualizar:

```bash
tail -f ~/.iris/iris.log
```

## 🔐 Segurança em Produção

Antes de colocar em produção:

1. Mude a `SECRET_KEY` para algo aleatório e seguro
2. Configure `FLASK_DEBUG=False`
3. Use um servidor WSGI (gunicorn, uWSGI)
4. Configure HTTPS/SSL
5. Use um banco de dados robusto (PostgreSQL)
6. Configure rate limiting
7. Valide e sanitize todas as entradas

## 📞 Suporte

Para problemas ou sugestões, verifique:
- Logs em `~/.iris/iris.log`
- Documentação do Ollama: https://ollama.ai
- Documentação do Hermes: https://hermes-agent.nousresearch.com

## 📄 Licença

Este projeto é fornecido como está, para fins educacionais e de teste.

---

**Versão**: 3.3  
**Última atualização**: 2024  
**Agente**: Mistral via Ollama  
**Autenticação**: Sim  
**Monetização**: Sim (Mercado Pago)
