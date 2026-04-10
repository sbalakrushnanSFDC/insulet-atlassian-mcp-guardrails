# Cursor AI Setup Guide

Step-by-step instructions for configuring the Atlassian MCP Guardrails server in Cursor AI.

---

## Prerequisites

Before you begin:

1. **Python 3.12 or later** — check with `python3 --version`
2. **Git** — check with `git --version`
3. **Atlassian API token** — create one at [https://id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
   - Log in to your Atlassian account
   - Click "Create API token"
   - Give it a label (e.g. "Cursor MCP")
   - Copy the token — you will not be able to see it again

---

## Step 1 — Clone and Install

```bash
git clone https://github.com/sbalakrushnanSFDC/insulet-atlassian-mcp-guardrails
cd insulet-atlassian-mcp-guardrails

python3 -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows

pip install -e .
```

Note the full path to your Python interpreter — you will need it in Step 4:

```bash
which python   # macOS/Linux: e.g. /Users/yourname/insulet-atlassian-mcp-guardrails/.venv/bin/python
# Windows: where python
```

---

## Step 2 — Configure Credentials

```bash
cp .env.example .env
```

Open `.env` in a text editor and fill in:

```
JIRA_BASE_URL=https://your-instance.atlassian.net
JIRA_EMAIL=your-email@company.com
JIRA_TOKEN=your-atlassian-api-token
```

If your admin has provided default project/space scopes, add them:

```
JIRA_DEFAULT_PROJECTS=PROJ1,PROJ2
CONFLUENCE_DEFAULT_SPACES=SPACE1,DOCS
```

**Never commit `.env` to version control.** It is already in `.gitignore`.

---

## Step 3 — Verify Connectivity

Test that your credentials work before configuring Cursor:

```bash
# With your .venv activated:
python -c "
from atlassian_mcp_guardrails.config import AtlassianConfig
from atlassian_mcp_guardrails.jira.client import JiraClient
config = AtlassianConfig.from_env()
client = JiraClient.from_config(config)
info = client.server_info()
print('Connected to:', info.get('serverTitle'), info.get('version'))
"
```

If you see `Connected to: ...` you are ready for Step 4.

---

## Step 4 — Configure Cursor AI

There are three ways to add this server to Cursor. Choose the one that fits your workflow.

### Option A — Global User Config (recommended for individuals)

1. Open Cursor
2. Go to **Settings** (Cmd+, on macOS, Ctrl+, on Windows/Linux)
3. Search for **MCP** or navigate to **Features → MCP**
4. Click **"Add new global MCP server"**
5. Paste the following JSON, replacing the empty strings with your values:

```json
{
  "atlassian-guardrails": {
    "command": "/full/path/to/insulet-atlassian-mcp-guardrails/.venv/bin/atlassian-mcp-guardrails",
    "args": [],
    "cwd": "/full/path/to/insulet-atlassian-mcp-guardrails",
    "env": {
      "JIRA_BASE_URL": "https://your-instance.atlassian.net",
      "JIRA_EMAIL": "your-email@company.com",
      "JIRA_TOKEN": "your-atlassian-api-token",
      "JIRA_DEFAULT_PROJECTS": "PROJ1,PROJ2",
      "CONFLUENCE_DEFAULT_SPACES": "SPACE1,DOCS",
      "LOG_LEVEL": "INFO"
    }
  }
}
```

Replace `/full/path/to/` with the actual paths on your machine.

### Option B — Workspace Config (recommended for teams)

Create `.cursor/mcp.json` in your project repo (the repo you work in, not this one):

```json
{
  "mcpServers": {
    "atlassian-guardrails": {
      "command": "/full/path/to/insulet-atlassian-mcp-guardrails/.venv/bin/atlassian-mcp-guardrails",
      "args": [],
      "cwd": "/full/path/to/insulet-atlassian-mcp-guardrails",
      "envFile": "/full/path/to/insulet-atlassian-mcp-guardrails/.env"
    }
  }
}
```

**Important:** Use the `atlassian-mcp-guardrails` CLI entry point (or `python -m atlassian_mcp_guardrails`), **not** `python -m atlassian_mcp_guardrails.server`. The latter causes a duplicate module load and results in "No tools, prompts, or resources" in Cursor.

This lets the whole team share the same MCP config by committing `.cursor/mcp.json` to your project repo. Each developer keeps their own `.env` with their personal credentials.

### Option C — Using `cursor_mcp_config.json` (drop-in)

The repo includes `cursor_mcp_config.json` as a starting point. Copy it to your Cursor config directory and fill in the empty values.

---

## Step 5 — Verify in Cursor

1. Restart Cursor (or reload the window: Cmd+Shift+P → "Reload Window")
2. Open the Cursor chat panel
3. Type: `@atlassian-guardrails` — you should see the server listed
4. Ask: `run atlassian_health_check`

A successful response looks like:

```json
{
  "ok": true,
  "jira": { "ok": true, "server_title": "...", "latency_ms": 234 },
  "confluence": { "ok": true, "user": "Your Name", "latency_ms": 187 }
}
```

---

## Example Prompts in Cursor

Once configured, you can ask Cursor to use the tools naturally:

```
Search Jira for open Stories assigned to me in my configured projects
```

```
Get the Confluence page with ID 12345678
```

```
What custom fields are available in Jira for this instance?
```

```
Search Confluence for pages about authentication in my configured spaces
```

```
Find all Jira bugs with High priority that are not yet resolved
```

```
Show me the Jira issue PROJ-456 with full details
```

---

## Common Mistakes

| Mistake | Fix |
|---|---|
| `JIRA_BASE_URL` ends with `/` | Remove the trailing slash: `https://company.atlassian.net` |
| Using your Atlassian password instead of an API token | Create an API token at id.atlassian.com |
| `CONFLUENCE_BASE_URL` set to the proxy URL | Set it to the canonical `*.atlassian.net` URL, or leave it unset (defaults to `JIRA_BASE_URL`) |
| Python path points to system Python, not the venv | Use the full path: `/path/to/.venv/bin/python` |
| Server not appearing in Cursor | Restart Cursor; check the MCP logs in Cursor settings |
| "No tools, prompts, or resources" (green dot but empty) | Use `atlassian-mcp-guardrails` CLI or `python -m atlassian_mcp_guardrails`, not `python -m atlassian_mcp_guardrails.server` |

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for more detailed diagnosis.
