# MCP: Commands to Run and How to Connect

This guide covers how to run OpenRAG and the MCP components, and how to connect to MCP from Cursor, Claude Desktop, or an MCP Apps host (Streamable HTTP).

## Commands to Run

### 1. Start OpenRAG

Choose one of these ways to run OpenRAG:

**Quickstart (no project files):**
```bash
uvx openrag
```

**Development (from repo):**
```bash
# Full stack with Docker
make dev          # GPU
make dev-cpu      # CPU only

# Or run backend and frontend locally (infra in Docker)
make dev-local
make backend      # Terminal 1: backend at http://localhost:8000
make frontend     # Terminal 2: frontend at http://localhost:3000
```

- **Frontend:** http://localhost:3000  
- **Backend API:** http://localhost:8000  

### 2. Build MCP Apps (for Streamable HTTP MCP)

The in-process MCP server at `/mcp` serves Settings and Models MCP App UIs. Build the frontend assets once:

```bash
cd mcp-apps
npm install
npm run build
```

Built files go to `mcp-apps/dist/`. The backend serves them when you use the Streamable HTTP MCP endpoint.

### 3. Run the STDIO MCP server (for Cursor / Claude Desktop)

To use the **STDIO** MCP server (chat, search, ingest, settings, models) from Cursor or Claude Desktop, run it from source so it talks to your OpenRAG instance:

```bash
cd sdks/mcp
uv sync
export OPENRAG_URL="http://localhost:3000"   # OpenRAG frontend URL
export OPENRAG_API_KEY="orag_your_api_key"   # from Settings → API Keys
uv run openrag-mcp
```

Use your real API key from the OpenRAG UI (Settings → API Keys). Do **not** install the `openrag-mcp` package if you want local code changes to apply; point your client at this repo (see below).

---

## How to Connect to the MCP

There are two ways to use OpenRAG’s MCP: **STDIO** (for Cursor/Claude Desktop) and **Streamable HTTP** (for MCP Apps hosts and other HTTP clients).

### Option A: STDIO (Cursor, Claude Desktop)

Use this for Cursor, Claude Desktop, or any client that runs the MCP server as a subprocess and talks over stdin/stdout.

1. **Start OpenRAG** (see above) and ensure you have an API key (Settings → API Keys).
2. **Run the MCP from the repo** (don’t install the package):
   ```bash
   cd sdks/mcp
   uv sync
   export OPENRAG_URL="http://localhost:3000"
   export OPENRAG_API_KEY="orag_your_api_key"
   uv run openrag-mcp
   ```
3. **Point your client at the repo** so it uses this code path.

**Cursor** – In `~/.cursor/mcp.json`, use `--directory` so Cursor runs the MCP from your repo:

```json
{
  "mcpServers": {
    "openrag": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/openrag/sdks/mcp", "openrag-mcp"],
      "env": {
        "OPENRAG_URL": "http://localhost:3000",
        "OPENRAG_API_KEY": "orag_your_api_key"
      }
    }
  }
}
```

Replace `/path/to/openrag` with your actual OpenRAG repo path. Restart Cursor after changing `mcp.json`.

**Claude Desktop** – In your Claude Desktop config (e.g. `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS), add the server with the same `command`, `args`, and `env`, using your repo path and API key.

More detail and troubleshooting: [sdks/mcp/README.md](../sdks/mcp/README.md).

---

### Option B: Streamable HTTP (MCP Apps host, browser, or HTTP clients)

Use this when your client connects to MCP over HTTP (e.g. an MCP Apps–compatible host or a custom HTTP client).

- **URL:** `http://localhost:8000/mcp/`  
  (Use the **backend** base URL and include the trailing slash.)
- **Authentication:** Send your OpenRAG API key in one of these ways:
  - **Header:** `X-API-Key: orag_your_api_key`
  - **Header:** `Authorization: Bearer orag_your_api_key`

**Example (curl):**
```bash
curl -H "X-API-Key: orag_your_api_key" http://localhost:8000/mcp/
```

**Requirements:**
- OpenRAG backend running (e.g. `make backend` or `uvx openrag`).
- API key created in OpenRAG (Settings → API Keys).
- For Settings/Models MCP App UIs: build once with `cd mcp-apps && npm install && npm run build`.

---

## Summary

| Goal                         | What to run / use |
|-----------------------------|-------------------|
| Use MCP in Cursor/Claude    | STDIO: `uv run openrag-mcp` from `sdks/mcp` with `OPENRAG_URL` and `OPENRAG_API_KEY`; configure client with repo path. |
| Use MCP over HTTP          | Streamable HTTP at `http://localhost:8000/mcp/` with `X-API-Key` or `Authorization: Bearer orag_...`. |
| Serve Settings/Models UIs  | Build once: `cd mcp-apps && npm install && npm run build`. |

For full MCP server tool list and STDIO setup, see [sdks/mcp/README.md](../sdks/mcp/README.md).
