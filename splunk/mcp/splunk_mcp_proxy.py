#!/usr/bin/env python3
"""
Splunk MCP Server stdio proxy for Claude Desktop.

The Splunk MCP Server exposes MCP over HTTPS REST rather than stdio.
This proxy bridges the gap: it reads MCP JSON-RPC from stdin, forwards
it to the Splunk MCP Server, and writes the response back to stdout.

Usage (Claude Desktop claude_desktop_config.json):
  {
    "mcpServers": {
      "splunk-sustainability": {
        "command": "python3",
        "args": ["/path/to/splunk_mcp_proxy.py"],
        "env": {
          "SPLUNK_HOST": "198.18.1.100",
          "SPLUNK_PORT": "8089",
          "SPLUNK_USER": "admin",
          "SPLUNK_PASS": "cisco"
        }
      }
    }
  }

Environment variables:
  SPLUNK_HOST  - Splunk management hostname/IP (default: 198.18.1.100)
  SPLUNK_PORT  - Splunk management port (default: 8089)
  SPLUNK_USER  - Splunk admin username (default: admin)
  SPLUNK_PASS  - Splunk admin password (default: cisco)
"""

import json
import os
import ssl
import sys
import base64
import urllib.request
import urllib.error
import logging

# ── configuration ──────────────────────────────────────────────────────────────
SPLUNK_HOST = os.environ.get("SPLUNK_HOST", "198.18.1.100")
SPLUNK_PORT = os.environ.get("SPLUNK_PORT", "8089")
SPLUNK_USER = os.environ.get("SPLUNK_USER", "admin")
SPLUNK_PASS = os.environ.get("SPLUNK_PASS", "cisco")

BASE_URL = f"https://{SPLUNK_HOST}:{SPLUNK_PORT}/servicesNS/nobody/Splunk_MCP_Server"
MCP_URL = f"{BASE_URL}/mcp"
TOKEN_URL = f"{BASE_URL}/mcp_token"

# ── TLS context (Splunk uses self-signed certs) ────────────────────────────────
_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE

# ── logging to stderr only (stdout is reserved for MCP JSON-RPC) ──────────────
logging.basicConfig(
    stream=sys.stderr,
    level=logging.WARNING,
    format="[splunk_mcp_proxy] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# ── token cache ────────────────────────────────────────────────────────────────
_bearer_token: str = ""


def _basic_auth() -> str:
    return base64.b64encode(f"{SPLUNK_USER}:{SPLUNK_PASS}".encode()).decode()


def _refresh_token() -> str:
    global _bearer_token
    auth = _basic_auth()

    # Rotate (generate new token)
    req = urllib.request.Request(TOKEN_URL, data=b"action=rotate", method="POST")
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, context=_ctx) as r:
        r.read()

    # Fetch token value
    req2 = urllib.request.Request(f"{TOKEN_URL}?username={SPLUNK_USER}")
    req2.add_header("Authorization", f"Basic {auth}")
    with urllib.request.urlopen(req2, context=_ctx) as r:
        data = json.load(r)

    _bearer_token = data.get("token", "")
    log.info("Token refreshed (len=%d)", len(_bearer_token))
    return _bearer_token


def _send_mcp(payload: dict) -> dict:
    """Send one MCP JSON-RPC request; auto-refresh token on 401."""
    global _bearer_token
    if not _bearer_token:
        _refresh_token()

    body = json.dumps(payload).encode()
    for attempt in range(2):
        req = urllib.request.Request(MCP_URL, data=body, method="POST")
        req.add_header("Authorization", f"Bearer {_bearer_token}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, context=_ctx) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 0:
                log.warning("401 – refreshing token and retrying")
                _refresh_token()
                continue
            err_body = e.read().decode(errors="replace")
            log.error("HTTP %s from Splunk MCP: %s", e.code, err_body[:500])
            raise


def _write(obj: dict) -> None:
    """Write one JSON object followed by newline to stdout."""
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> None:
    log.info("Splunk MCP proxy started (target: %s:%s)", SPLUNK_HOST, SPLUNK_PORT)
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            request = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            log.error("Invalid JSON on stdin: %s", exc)
            continue

        req_id = request.get("id")
        method = request.get("method", "")

        try:
            response = _send_mcp(request)
            _write(response)
        except Exception as exc:
            log.error("Error forwarding %s: %s", method, exc)
            # Return a valid JSON-RPC error so the client doesn't hang
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32603,
                        "message": f"Proxy error: {exc}",
                    },
                }
            )


if __name__ == "__main__":
    main()
