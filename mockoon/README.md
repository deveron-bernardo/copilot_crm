# Mock de Provedor de IA com Mockoon — Copilot CRM

Este diretório contém o ambiente exportado do **Mockoon** para simular com fidelidade um provedor de IA compatível com a API da OpenAI (utilizado pelo Copilot CRM via LiteLLM).

Com ele, é possível testar e desenvolver funcionalidades do Copilot CRM (chat com streaming SSE, chamadas de ferramentas/tools do CRM, embeddings e consultas de modelos) localmente sem necessidade de chaves pagas ou conexão com a internet.

---

## 📁 Arquivos

- **`copilot_ai_mock_environment.json`**: Definição completa do ambiente Mockoon, incluindo rotas, regras de roteamento (rules), respostas de streaming SSE, chamadas de ferramentas (`tool_calls`), embeddings e healthcheck.

---

## 🚀 Como Iniciar o Mock

Você pode utilizar qualquer uma das seguintes opções:

### Opção 1: Mockoon Desktop (Recomendado para interface visual)

1. Baixe e abra o [Mockoon](https://mockoon.com/).
2. No menu lateral, clique em **Open environment** (ou aperte `Ctrl + O`).
3. Selecione o arquivo `mockoon/copilot_ai_mock_environment.json`.
4. Clique no botão **Start** (ícone de play verde) no topo. O servidor iniciará na porta `3001`.

### Opção 2: Mockoon CLI via NPX (Sem instalar nada globalmente)

No terminal (Windows ou WSL):

```bash
npx @mockoon/cli start --data ./mockoon/copilot_ai_mock_environment.json --port 3001
```

Para parar o servidor:
```bash
npx @mockoon/cli stop "Deveron Copilot AI Mock"
```

### Opção 3: Docker

```bash
docker run -d --name copilot-ai-mock -p 3001:3001 -v "$(pwd)/mockoon/copilot_ai_mock_environment.json:/data:ro" mockoon/cli:latest -d /data -p 3001
```

---

## ⚙️ Configuração no Copilot CRM (`.env`)

No seu arquivo `.env` (seja no bench root `/home/bernardo/frappe/my-bench/.env`, no site ou no repositório `copilot_crm/.env`), configure:

```dotenv
# ==============================================================================
# Copilot CRM - Mockoon Local AI Provider
# ==============================================================================
COPILOT_AI_MODEL=openai/gpt-4o-mini
COPILOT_AI_API_KEY=mockoon-dev-key
COPILOT_AI_BASE_URL=http://localhost:3001/v1
```

> **Nota:** As rotas suportam tanto chamadas com prefixo (`http://localhost:3001/v1`) quanto diretas (`http://localhost:3001`).

---

## 🧪 Cenários Mockados & Endpoints

O ambiente simula automaticamente as principais operações do Copilot CRM:

| Método | Endpoint | Regra / Disparo | Resposta Simulada |
|---|---|---|---|
| **POST** | `/v1/chat/completions` ou `/chat/completions` | `stream: true` no body | **SSE Streaming (chunks em tempo real)** simulando a digitação fluida do Copilot CRM e fechando com `data: [DONE]`. |
| **POST** | `/v1/chat/completions` ou `/chat/completions` | Mensagem contém `tarefa`, `task`, `agenda` | **Tool Call: `manage_crm_task`** criando uma tarefa de follow-up com status `Todo`. |
| **POST** | `/v1/chat/completions` ou `/chat/completions` | Mensagem contém `coment`, `comment`, `timeline` | **Tool Call: `add_crm_comment`** adicionando comentário à timeline de um Lead. |
| **POST** | `/v1/chat/completions` ou `/chat/completions` | Mensagem contém `listar`, `buscar`, `leads`, `deals` | **Tool Call: `read`** consultando registros de `CRM Lead`. |
| **POST** | `/v1/chat/completions` ou `/chat/completions` | Default (outras mensagens) | **Chat Completion padrão (JSON)** com saudação contextualizada em PT-BR e contagem de tokens de uso. |
| **POST** | `/v1/embeddings` ou `/embeddings` | Qualquer payload | **Vetor de Embedding** com 1536 dimensões compatível com `text-embedding-3-small` / Qdrant. |
| **GET** | `/v1/models` ou `/models` | - | Lista de modelos disponíveis (`gpt-4o-mini`, `gpt-4o`, `text-embedding-3-small`, etc.). |
| **GET** | `/health` ou `/` | - | Status de saúde do mock server: `{"status": "healthy"}`. |

---

## 🔍 Como Testar o Mock Diretamente (cURL)

### 1. Testar Healthcheck
```bash
curl http://localhost:3001/health
```

### 2. Testar Chat Não-Streaming
```bash
curl -X POST http://localhost:3001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Olá"}]}'
```

### 3. Testar Streaming SSE
```bash
curl -N -X POST http://localhost:3001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o-mini", "stream": true, "messages": [{"role": "user", "content": "Teste"}]}'
```

### 4. Testar Disparo de Tool Call (Tarefa)
```bash
curl -X POST http://localhost:3001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Crie uma nova tarefa para amanhã"}]}'
```

### 5. Testar Embeddings
```bash
curl -X POST http://localhost:3001/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model": "text-embedding-3-small", "input": "Busca semântica no CRM"}'
```
