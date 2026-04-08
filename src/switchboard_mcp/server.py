"""STDIO MCP server that proxies Switchboard HTTP endpoints."""

from dataclasses import dataclass
import json
import os
import sys
from datetime import datetime
from typing import Any, Callable

import httpx


JSON_RPC_VERSION = "2.0"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2024-11-05")
SERVER_INFO = {"name": "switchboard-mcp", "version": "0.1.0"}


def debug_log(message: str) -> None:
    """Write optional MCP debug logs to a file without touching stdout."""
    log_path = os.environ.get("SWITCHBOARD_MCP_DEBUG_LOG")
    if not log_path:
        return

    timestamp = datetime.utcnow().isoformat()
    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(f"{timestamp} {message}\n")


@dataclass(frozen=True)
class ToolResult:
    """Structured result returned by a tool handler."""

    payload: Any
    is_error: bool = False


class SwitchboardHttpClient:
    """Thin HTTP client for the existing Switchboard control plane."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=30.0)

    def close(self) -> None:
        """Release the underlying HTTP client."""
        self._client.close()

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> ToolResult:
        """Issue a GET request and return the decoded JSON response."""
        return self._request("GET", path, params=params)

    def post(self, path: str, payload: dict[str, Any]) -> ToolResult:
        """Issue a POST request and return the decoded JSON response."""
        return self._request("POST", path, json_body=payload)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Forward one request to the local Switchboard API."""
        try:
            response = self._client.request(
                method,
                path,
                params=params,
                json=json_body,
            )
        except httpx.HTTPError as exc:
            return ToolResult(
                {
                    "error": (
                        f"Failed to reach Switchboard API at {self.base_url}: {exc}"
                    )
                },
                is_error=True,
            )

        try:
            payload: Any = response.json()
        except ValueError:
            payload = {"error": response.text or "Non-JSON response from Switchboard API"}

        return ToolResult(payload=payload, is_error=not response.is_success)


def compact_json(value: Any) -> str:
    """Serialize a tool result into a compact JSON string."""
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def structured_content(value: Any) -> dict[str, Any] | None:
    """Normalize tool payloads to MCP-compatible structured content."""
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {"result": value}
    return None


def optional_value(arguments: dict[str, Any], key: str) -> Any:
    """Return an optional argument only when the caller provided it."""
    if key in arguments:
        return arguments[key]
    return None


def build_tool_definitions() -> list[dict[str, Any]]:
    """Return the MCP tool metadata exposed by this server."""
    return [
        {
            "name": "register_agent",
            "title": "Register Agent",
            "description": "Register an agent in Switchboard via POST /agents/register.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "capability": {"type": "string"},
                    "description": {"type": "string"},
                    "price_per_task": {"type": "number"},
                    "endpoint": {"type": "string"},
                },
                "required": ["name", "capability", "description", "price_per_task"],
            },
        },
        {
            "name": "discover_agents",
            "title": "Discover Agents",
            "description": "Discover registered agents by capability via GET /agents/discover.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"capability": {"type": "string"}},
                "required": ["capability"],
            },
        },
        {
            "name": "delegate_task",
            "title": "Delegate Task",
            "description": "Issue a spend token via POST /delegate.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "to_agent_id": {"type": "string"},
                    "task_description": {"type": "string"},
                    "budget": {"type": "number"},
                    "from_agent_id": {"type": "string"},
                    "job_id": {"type": "string"},
                    "payment_profile_id": {"type": "string"},
                    "payment_mode": {"type": "string"},
                    "merchant_category": {"type": "string"},
                    "allowed_merchants": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "single_use": {"type": "boolean"},
                },
                "required": ["to_agent_id", "task_description", "budget"],
            },
        },
        {
            "name": "verify_token",
            "title": "Verify Token",
            "description": "Verify a Switchboard spend token via GET /verify/{token}.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"token": {"type": "string"}},
                "required": ["token"],
            },
        },
        {
            "name": "complete_task",
            "title": "Complete Task",
            "description": "Complete a delegated task via POST /complete.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "token": {"type": "string"},
                    "actual_spend": {"type": "number"},
                },
                "required": ["token", "actual_spend"],
            },
        },
        {
            "name": "create_payment_profile",
            "title": "Create Payment Profile",
            "description": "Create a sandbox payment profile via POST /payment-profiles.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "payment_mode": {"type": "string"},
                    "merchant_category": {"type": "string"},
                    "allowed_merchants": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["name", "merchant_category"],
            },
        },
        {
            "name": "issue_sandbox_authorization",
            "title": "Issue Sandbox Authorization",
            "description": "Issue a sandbox payment authorization via POST /payments/authorize.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "spend_token_id": {"type": "string"},
                    "job_id": {"type": "string"},
                    "payment_profile_id": {"type": "string"},
                    "payment_mode": {"type": "string"},
                    "merchant_category": {"type": "string"},
                    "allowed_merchants": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "authorized_amount": {"type": "number"},
                    "single_use": {"type": "boolean"},
                    "expires_at": {"type": "string", "format": "date-time"},
                },
                "required": ["spend_token_id", "merchant_category", "authorized_amount"],
            },
        },
        {
            "name": "record_payment_attempt",
            "title": "Record Payment Attempt",
            "description": "Record one sandbox auth or capture attempt via POST /payments/attempt.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "payment_authorization_id": {"type": "string"},
                    "spend_token_id": {"type": "string"},
                    "job_id": {"type": "string"},
                    "attempt_type": {"type": "string", "enum": ["auth", "capture"]},
                    "merchant_name": {"type": "string"},
                    "merchant_category": {"type": "string"},
                    "amount": {"type": "number"},
                },
                "required": [
                    "payment_authorization_id",
                    "attempt_type",
                    "merchant_name",
                    "merchant_category",
                    "amount",
                ],
            },
        },
        {
            "name": "runtime_check_readiness",
            "title": "Runtime Check Readiness",
            "description": "Check delegated runtime state for connection, setup, approval, or allowed status.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "delegated_token": {"type": "string"},
                    "task_token": {"type": "string"},
                    "agent_name": {"type": "string"},
                    "approval_kind": {"type": "string"},
                    "profile_scopes": {"type": "array", "items": {"type": "string"}},
                    "budget_limit": {"type": "number"},
                    "monthly_limit": {"type": "number"},
                    "reason": {"type": "string"},
                    "require_payment": {"type": "boolean"},
                    "require_traveler_profile": {"type": "boolean"}
                },
                "required": ["delegated_token"],
            },
        },
        {
            "name": "runtime_approval_response",
            "title": "Runtime Approval Response",
            "description": "Submit the user's in-channel approval or denial for a pending delegated task.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "delegated_token": {"type": "string"},
                    "task_token": {"type": "string"},
                    "decision": {"type": "string", "enum": ["approve", "deny"]},
                    "message": {"type": "string"}
                },
                "required": ["delegated_token", "task_token", "decision"],
            },
        },
        {
            "name": "runtime_delegate",
            "title": "Runtime Delegate",
            "description": "Delegate work to a specialist agent under the delegated runtime flow.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "delegated_token": {"type": "string"},
                    "capability": {"type": "string"},
                    "task_description": {"type": "string"},
                    "budget": {"type": "number"},
                    "task_token": {"type": "string"},
                    "agent_name": {"type": "string"},
                    "profile_scope": {"type": "string"},
                    "domain": {"type": "string"}
                },
                "required": ["delegated_token", "capability", "task_description"],
            },
        },
        {
            "name": "runtime_result",
            "title": "Runtime Result",
            "description": "Fetch the standardized delegated runtime result contract for a task.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "delegated_token": {"type": "string"},
                    "task_token": {"type": "string"},
                    "domain": {"type": "string"}
                },
                "required": ["delegated_token", "task_token"],
            },
        },
        {
            "name": "task_status",
            "title": "Task Status",
            "description": "Get task status, input requirements, and event timeline via GET /tasks/{token}.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "token": {"type": "string"}
                },
                "required": ["token"],
            },
        },
        {
            "name": "task_pause_for_input",
            "title": "Task Pause For Input",
            "description": "Pause a task and declare the user input required via POST /tasks/{token}/pause.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "token": {"type": "string"},
                    "input_prompt": {"type": "string"},
                    "input_schema": {"type": "object"},
                    "input_timeout_minutes": {"type": "integer"}
                },
                "required": ["token", "input_prompt", "input_schema"],
            },
        },
        {
            "name": "task_submit_input",
            "title": "Task Submit Input",
            "description": "Submit user input to a paused task via POST /tasks/{token}/input.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "token": {"type": "string"},
                    "input_data": {"type": "object"}
                },
                "required": ["token", "input_data"],
            },
        },
    ]


TOOL_DEFINITIONS = build_tool_definitions()
TOOL_NAMES = {tool["name"] for tool in TOOL_DEFINITIONS}


def build_tool_handlers(
    api: SwitchboardHttpClient,
) -> dict[str, Callable[[dict[str, Any]], ToolResult]]:
    """Map MCP tool names onto existing Switchboard HTTP endpoints."""

    def register_agent(arguments: dict[str, Any]) -> ToolResult:
        return api.post(
            "/agents/register",
            {
                "name": arguments["name"],
                "capability": arguments["capability"],
                "description": arguments["description"],
                "price_per_task": arguments["price_per_task"],
                "endpoint": optional_value(arguments, "endpoint"),
            },
        )

    def discover_agents(arguments: dict[str, Any]) -> ToolResult:
        return api.get("/agents/discover", params={"capability": arguments["capability"]})

    def delegate_task(arguments: dict[str, Any]) -> ToolResult:
        return api.post(
            "/delegate",
            {
                "to_agent_id": arguments["to_agent_id"],
                "task_description": arguments["task_description"],
                "budget": arguments["budget"],
                "from_agent_id": arguments.get("from_agent_id", "anonymous"),
                "job_id": optional_value(arguments, "job_id"),
                "payment_profile_id": optional_value(arguments, "payment_profile_id"),
                "payment_mode": optional_value(arguments, "payment_mode"),
                "merchant_category": optional_value(arguments, "merchant_category"),
                "allowed_merchants": optional_value(arguments, "allowed_merchants"),
                "single_use": optional_value(arguments, "single_use"),
            },
        )

    def verify_token(arguments: dict[str, Any]) -> ToolResult:
        return api.get(f"/verify/{arguments['token']}")

    def complete_task(arguments: dict[str, Any]) -> ToolResult:
        return api.post(
            "/complete",
            {
                "token": arguments["token"],
                "actual_spend": arguments["actual_spend"],
            },
        )

    def create_payment_profile(arguments: dict[str, Any]) -> ToolResult:
        return api.post(
            "/payment-profiles",
            {
                "name": arguments["name"],
                "payment_mode": arguments.get("payment_mode", "sandbox_virtual_card"),
                "merchant_category": arguments["merchant_category"],
                "allowed_merchants": optional_value(arguments, "allowed_merchants"),
            },
        )

    def issue_sandbox_authorization(arguments: dict[str, Any]) -> ToolResult:
        return api.post(
            "/payments/authorize",
            {
                "spend_token_id": arguments["spend_token_id"],
                "job_id": optional_value(arguments, "job_id"),
                "payment_profile_id": optional_value(arguments, "payment_profile_id"),
                "payment_mode": arguments.get("payment_mode", "sandbox_virtual_card"),
                "merchant_category": arguments["merchant_category"],
                "allowed_merchants": optional_value(arguments, "allowed_merchants"),
                "authorized_amount": arguments["authorized_amount"],
                "single_use": arguments.get("single_use", True),
                "expires_at": optional_value(arguments, "expires_at"),
            },
        )

    def record_payment_attempt(arguments: dict[str, Any]) -> ToolResult:
        return api.post(
            "/payments/attempt",
            {
                "payment_authorization_id": arguments["payment_authorization_id"],
                "spend_token_id": optional_value(arguments, "spend_token_id"),
                "job_id": optional_value(arguments, "job_id"),
                "attempt_type": arguments["attempt_type"],
                "merchant_name": arguments["merchant_name"],
                "merchant_category": arguments["merchant_category"],
                "amount": arguments["amount"],
            },
        )

    def runtime_check_readiness(arguments: dict[str, Any]) -> ToolResult:
        delegated_token = arguments["delegated_token"]
        payload = {
            "task_token": optional_value(arguments, "task_token"),
            "agent_name": optional_value(arguments, "agent_name"),
            "approval_kind": optional_value(arguments, "approval_kind"),
            "profile_scopes": optional_value(arguments, "profile_scopes"),
            "budget_limit": optional_value(arguments, "budget_limit"),
            "monthly_limit": optional_value(arguments, "monthly_limit"),
            "reason": optional_value(arguments, "reason"),
            "require_payment": arguments.get("require_payment", False),
            "require_traveler_profile": arguments.get("require_traveler_profile", False),
        }
        try:
            response = api._client.post(
                "/runtime/check-readiness",
                json=payload,
                headers={"Authorization": f"Bearer {delegated_token}"},
            )
        except httpx.HTTPError as exc:
            return ToolResult({"error": f"Failed to reach Switchboard API at {api.base_url}: {exc}"}, is_error=True)
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": response.text or "Non-JSON response from Switchboard API"}
        return ToolResult(payload=payload, is_error=not response.is_success)

    def runtime_approval_response(arguments: dict[str, Any]) -> ToolResult:
        delegated_token = arguments["delegated_token"]
        payload = {
            "task_token": arguments["task_token"],
            "decision": arguments["decision"],
            "message": optional_value(arguments, "message"),
        }
        try:
            response = api._client.post(
                "/runtime/approval-response",
                json=payload,
                headers={"Authorization": f"Bearer {delegated_token}"},
            )
        except httpx.HTTPError as exc:
            return ToolResult({"error": f"Failed to reach Switchboard API at {api.base_url}: {exc}"}, is_error=True)
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": response.text or "Non-JSON response from Switchboard API"}
        return ToolResult(payload=payload, is_error=not response.is_success)

    def runtime_delegate(arguments: dict[str, Any]) -> ToolResult:
        delegated_token = arguments["delegated_token"]
        payload = {
            "capability": arguments["capability"],
            "task_description": arguments["task_description"],
            "budget": arguments.get("budget", 0.0),
            "task_token": optional_value(arguments, "task_token"),
            "agent_name": optional_value(arguments, "agent_name"),
            "profile_scope": optional_value(arguments, "profile_scope"),
            "domain": optional_value(arguments, "domain"),
        }
        try:
            response = api._client.post(
                "/runtime/delegate",
                json=payload,
                headers={"Authorization": f"Bearer {delegated_token}"},
            )
        except httpx.HTTPError as exc:
            return ToolResult({"error": f"Failed to reach Switchboard API at {api.base_url}: {exc}"}, is_error=True)
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": response.text or "Non-JSON response from Switchboard API"}
        return ToolResult(payload=payload, is_error=not response.is_success)

    def runtime_result(arguments: dict[str, Any]) -> ToolResult:
        delegated_token = arguments["delegated_token"]
        payload = {
            "task_token": arguments["task_token"],
            "domain": optional_value(arguments, "domain"),
        }
        try:
            response = api._client.post(
                "/runtime/result",
                json=payload,
                headers={"Authorization": f"Bearer {delegated_token}"},
            )
        except httpx.HTTPError as exc:
            return ToolResult({"error": f"Failed to reach Switchboard API at {api.base_url}: {exc}"}, is_error=True)
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": response.text or "Non-JSON response from Switchboard API"}
        return ToolResult(payload=payload, is_error=not response.is_success)

    def task_status(arguments: dict[str, Any]) -> ToolResult:
        return api.get(f"/tasks/{arguments['token']}")

    def task_pause_for_input(arguments: dict[str, Any]) -> ToolResult:
        return api.post(
            f"/tasks/{arguments['token']}/pause",
            {
                "token": arguments["token"],
                "input_prompt": arguments["input_prompt"],
                "input_schema": arguments["input_schema"],
                "input_timeout_minutes": arguments.get("input_timeout_minutes", 30),
            },
        )

    def task_submit_input(arguments: dict[str, Any]) -> ToolResult:
        return api.post(
            f"/tasks/{arguments['token']}/input",
            {
                "input_data": arguments["input_data"],
            },
        )

    return {
        "register_agent": register_agent,
        "discover_agents": discover_agents,
        "delegate_task": delegate_task,
        "verify_token": verify_token,
        "complete_task": complete_task,
        "create_payment_profile": create_payment_profile,
        "issue_sandbox_authorization": issue_sandbox_authorization,
        "record_payment_attempt": record_payment_attempt,
        "runtime_check_readiness": runtime_check_readiness,
        "runtime_approval_response": runtime_approval_response,
        "runtime_delegate": runtime_delegate,
        "runtime_result": runtime_result,
        "task_status": task_status,
        "task_pause_for_input": task_pause_for_input,
        "task_submit_input": task_submit_input,
    }


class JsonRpcError(Exception):
    """Structured JSON-RPC error."""

    def __init__(self, code: int, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_payload(self) -> dict[str, Any]:
        """Serialize the error into a JSON-RPC error object."""
        payload = {"code": self.code, "message": self.message}
        if self.data is not None:
            payload["data"] = self.data
        return payload


class SwitchboardMcpServer:
    """Minimal MCP server implementation over stdio."""

    def __init__(self, base_url: str) -> None:
        self._initialized = False
        self._transport_mode = "auto"
        self._api = SwitchboardHttpClient(base_url)
        self._tool_handlers = build_tool_handlers(self._api)

    def close(self) -> None:
        """Release local resources."""
        self._api.close()

    def serve(self) -> int:
        """Run the stdio message loop until the client disconnects."""
        debug_log("serve:start")
        try:
            while True:
                message = self._read_message()
                if message is None:
                    debug_log("serve:eof")
                    return 0

                if "id" in message:
                    debug_log(f"serve:request method={message.get('method')!r}")
                    response = self._handle_request(message)
                    self._write_message(response)
                else:
                    debug_log(f"serve:notification method={message.get('method')!r}")
                    self._handle_notification(message)
        finally:
            debug_log("serve:close")
            self.close()

    def _read_message(self) -> dict[str, Any] | None:
        """Read one framed JSON-RPC message from stdin."""
        if self._transport_mode == "jsonl":
            return self._read_jsonl_message()
        if self._transport_mode == "framed":
            return self._read_framed_message()

        first_line = sys.stdin.buffer.readline()
        if not first_line:
            debug_log("read:eof-before-header")
            return None

        if first_line in {b"\r\n", b"\n"}:
            return self._read_message()

        stripped_line = first_line.lstrip()
        if stripped_line.startswith((b"{", b"[")):
            self._transport_mode = "jsonl"
            return self._decode_message_bytes(first_line)

        self._transport_mode = "framed"
        return self._read_framed_message(first_line)

    def _read_jsonl_message(self) -> dict[str, Any] | None:
        """Read one newline-delimited JSON-RPC message from stdin."""
        while True:
            body = sys.stdin.buffer.readline()
            if not body:
                debug_log("read:eof-jsonl")
                return None
            if body in {b"\r\n", b"\n"}:
                continue
            return self._decode_message_bytes(body)

    def _read_framed_message(
        self,
        first_header_line: bytes | None = None,
    ) -> dict[str, Any] | None:
        """Read one Content-Length framed JSON-RPC message from stdin."""
        content_length: int | None = None
        header_line = first_header_line

        while True:
            if header_line is None:
                header_line = sys.stdin.buffer.readline()
            if not header_line:
                debug_log("read:eof-before-header")
                return None

            if header_line in {b"\r\n", b"\n"}:
                break

            header_name, _, header_value = header_line.decode("utf-8").partition(":")
            debug_log(f"read:header {header_name.lower()}={header_value.strip()}")
            if header_name.lower() == "content-length":
                content_length = int(header_value.strip())
            header_line = None

        if content_length is None:
            raise JsonRpcError(-32700, "Missing Content-Length header")

        body = sys.stdin.buffer.read(content_length)
        if not body:
            debug_log("read:eof-body")
            return None

        return self._decode_message_bytes(body)

    def _decode_message_bytes(self, body: bytes) -> dict[str, Any]:
        """Decode one raw JSON-RPC body."""
        body = body.strip()
        if not body:
            raise JsonRpcError(-32700, "Empty JSON-RPC message")

        try:
            message = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise JsonRpcError(-32700, "Invalid JSON", {"details": str(exc)}) from exc

        if not isinstance(message, dict):
            raise JsonRpcError(-32600, "Invalid Request")
        debug_log(f"read:body {compact_json(message)}")
        return message

    def _write_message(self, message: dict[str, Any]) -> None:
        """Write one framed JSON-RPC message to stdout."""
        debug_log(f"write:body {compact_json(message)}")
        body = json.dumps(message, separators=(",", ":"), default=str).encode("utf-8")

        if self._transport_mode == "jsonl":
            sys.stdout.buffer.write(body)
            sys.stdout.buffer.write(b"\n")
            sys.stdout.buffer.flush()
            return

        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        sys.stdout.buffer.write(header)
        sys.stdout.buffer.write(body)
        sys.stdout.buffer.flush()

    def _handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Dispatch one JSON-RPC request."""
        request_id = request.get("id")

        try:
            method = request.get("method")
            if method == "initialize":
                return self._response(request_id, self._handle_initialize(request))
            if method == "ping":
                return self._response(request_id, {})
            # Native clients may probe these list endpoints during startup even
            # when the server only exposes tools. Return empty catalogs instead
            # of hard errors so the handshake can complete cleanly.
            if method == "resources/list":
                return self._response(request_id, {"resources": []})
            if method == "resources/templates/list":
                return self._response(request_id, {"resourceTemplates": []})
            if method == "prompts/list":
                return self._response(request_id, {"prompts": []})
            if method == "tools/list":
                return self._response(request_id, {"tools": TOOL_DEFINITIONS})
            if method == "tools/call":
                self._require_initialized()
                return self._response(request_id, self._handle_tool_call(request))
            raise JsonRpcError(-32601, f"Method not found: {method}")
        except JsonRpcError as exc:
            return {
                "jsonrpc": JSON_RPC_VERSION,
                "id": request_id,
                "error": exc.to_payload(),
            }
        except Exception as exc:  # pragma: no cover - last-resort protocol guard
            return {
                "jsonrpc": JSON_RPC_VERSION,
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": "Internal error",
                    "data": {"details": str(exc)},
                },
            }

    def _handle_notification(self, request: dict[str, Any]) -> None:
        """Handle fire-and-forget notifications."""
        method = request.get("method")
        if method == "notifications/initialized":
            self._initialized = True
            return
        if method == "notifications/cancelled":
            return

    def _handle_initialize(self, request: dict[str, Any]) -> dict[str, Any]:
        """Negotiate protocol version and advertise server capabilities."""
        params = request.get("params", {})
        if not isinstance(params, dict):
            raise JsonRpcError(-32602, "initialize params must be an object")

        requested_version = params.get("protocolVersion")
        if requested_version in SUPPORTED_PROTOCOL_VERSIONS:
            protocol_version = requested_version
        else:
            protocol_version = SUPPORTED_PROTOCOL_VERSIONS[0]

        self._initialized = True
        return {
            "protocolVersion": protocol_version,
            "capabilities": {
                "prompts": {},
                "resources": {},
                "tools": {},
            },
            "serverInfo": SERVER_INFO,
        }

    def _handle_tool_call(self, request: dict[str, Any]) -> dict[str, Any]:
        """Validate and run one MCP tool call."""
        params = request.get("params", {})
        if not isinstance(params, dict):
            raise JsonRpcError(-32602, "tools/call params must be an object")

        tool_name = params.get("name")
        if tool_name not in TOOL_NAMES:
            raise JsonRpcError(-32602, f"Unknown tool: {tool_name}")

        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            raise JsonRpcError(-32602, "Tool arguments must be an object")

        result = self._tool_handlers[tool_name](arguments)
        response: dict[str, Any] = {
            "content": [{"type": "text", "text": compact_json(result.payload)}]
        }
        normalized_content = structured_content(result.payload)
        if normalized_content is not None:
            response["structuredContent"] = normalized_content
        if result.is_error:
            response["isError"] = True
        return response

    def _require_initialized(self) -> None:
        """Reject tool execution before the initialize request has completed."""
        if not self._initialized:
            raise JsonRpcError(-32002, "Server not initialized")

    def _response(self, request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        """Build a JSON-RPC success response."""
        return {"jsonrpc": JSON_RPC_VERSION, "id": request_id, "result": result}


def main() -> int:
    """Start the Switchboard MCP server on stdio."""
    base_url = os.environ.get("SWITCHBOARD_BASE_URL", "http://127.0.0.1:8000")
    debug_log(f"main:start base_url={base_url}")
    server = SwitchboardMcpServer(base_url=base_url)
    return server.serve()


if __name__ == "__main__":
    raise SystemExit(main())
