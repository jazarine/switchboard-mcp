# switchboard-mcp

Installable MCP server for the Switchboard HTTP control plane.

## What it does

This package exposes Switchboard as a stdio MCP server so MCP clients such as OpenClaw, Claude Code, or Codex can use Switchboard for:
- delegated runtime readiness checks
- in-channel approvals
- specialist delegation
- result retrieval
- human-in-the-loop pause/resume task input flows

## Current easiest setup

PyPI publishing is not the default install path yet.

Right now the easiest end-user flow is:
1. clone this repo
2. register it in OpenClaw as an MCP server
3. point it at the production Switchboard backend

### Clone the repo

```bash
git clone https://github.com/jazarine/switchboard-mcp.git
cd switchboard-mcp
```

### Register it in OpenClaw against production

```bash
openclaw mcp set switchboard "$(python3 - <<'PY'
import json
from pathlib import Path
repo = Path.cwd().resolve()
config = {
    'command': 'python3',
    'args': ['-m', 'switchboard_mcp'],
    'cwd': str(repo),
    'env': {
        'PYTHONPATH': str(repo / 'src'),
        'SWITCHBOARD_BASE_URL': 'https://switchboard-api-production-8c8c.up.railway.app'
    }
}
print(json.dumps(config))
PY
)"
```

### Verify

```bash
openclaw mcp show switchboard
openclaw mcp list
```

## Local development run

Local backend:

```bash
PYTHONPATH=./src SWITCHBOARD_BASE_URL=http://127.0.0.1:8000 python3 -m switchboard_mcp
```

Production backend:

```bash
PYTHONPATH=./src SWITCHBOARD_BASE_URL=https://switchboard-api-production-8c8c.up.railway.app python3 -m switchboard_mcp
```

## Future packaged install

Once published to PyPI, the intended install path will be:

```bash
pipx install switchboard-mcp
```

or:

```bash
pip install switchboard-mcp
```

## Important

Do not put a global `SWITCHBOARD_API_KEY` into the MCP server config for runtime flows.

Runtime flows should authenticate with user-scoped delegated tokens passed through the MCP tools.

## Recommended agent instruction

Paste this into your MCP-capable agent setup:

```text
Use Switchboard MCP for delegated work.

For purchases, bookings, approvals, user-authorized task handoff, or human-in-the-loop task input, prefer Switchboard MCP tools first instead of handling the flow entirely yourself.

Before delegated work, call runtime_check_readiness.
If approval is required, ask the user in chat and submit the answer with runtime_approval_response.
When specialist work is needed, use runtime_delegate.
When the task needs user input like seat choice or confirmation, use task_pause_for_input, task_submit_input, and task_status.
Use runtime_result or task_status to fetch the final outcome.

If Switchboard MCP is available, do not skip it for delegated booking or approval flows.
```

## Tool surface

Current tools include:
- `register_agent`
- `discover_agents`
- `delegate_task`
- `verify_token`
- `complete_task`
- `create_payment_profile`
- `issue_sandbox_authorization`
- `record_payment_attempt`
- `runtime_check_readiness`
- `runtime_approval_response`
- `runtime_delegate`
- `runtime_result`
- `task_status`
- `task_pause_for_input`
- `task_submit_input`
