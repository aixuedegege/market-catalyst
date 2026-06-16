#!/usr/bin/env python3
"""
Catalyst Calendar MCP Server — stdio JSON-RPC
Configure in Cursor/Claude Desktop:
{
  "mcpServers": {
    "catalyst-calendar": {
      "command": "python3",
      "args": ["/data/ai/tmp/catalyst_mcp_server.py"]
    }
  }
}
"""

import json
import sys
import os
from datetime import datetime, timezone, timedelta

DATA_FILE = "/data/ai/tmp/catalyst_events.json"
PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "catalyst-calendar"
SERVER_VERSION = "1.0.0"

def load_events():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except Exception:
        return []

def get_future_events(events, days=30):
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days)
    now_str = now.strftime("%Y-%m-%d")
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    future = [e for e in events if now_str <= e.get("date", "")[:10] <= cutoff_str]
    future.sort(key=lambda x: x.get("date", ""))
    return future

def fmt_event(e):
    return f"[{e.get('date','N/A')}] {e.get('title','N/A')} | Impact: {e.get('impact_analysis','N/A')} | Assets: {e.get('asset_impact','N/A')}"

def send_response(req_id, result=None, error=None):
    resp = {"jsonrpc": "2.0", "id": req_id}
    if error:
        resp["error"] = error
    else:
        resp["result"] = result
    body = json.dumps(resp, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
    sys.stdout.buffer.write(header + body)
    sys.stdout.buffer.flush()

def handle_initialize(req_id):
    send_response(req_id, {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}
    })

def handle_tools_list(req_id):
    send_response(req_id, {"tools": [
        {
            "name": "get_catalyst_events",
            "description": "Fetch upcoming macroeconomic catalyst events. Filter by days ahead and impact level.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Days ahead to fetch (default: 7, max: 30)", "default": 7},
                    "impact": {"type": "string", "description": "Filter: 'all', 'high', or 'critical'", "enum": ["all", "high", "critical"], "default": "all"}
                }
            }
        },
        {
            "name": "search_catalyst_events",
            "description": "Search catalyst events by keyword (e.g., 'CPI', 'FOMC', 'NFP').",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keyword, e.g., 'CPI', 'FOMC', 'Fed', 'NFP'"},
                    "days": {"type": "integer", "description": "Days ahead to search within (default: 30)", "default": 30}
                },
                "required": ["query"]
            }
        }
    ]})

def handle_tool_call(req_id, name, args):
    events = load_events()
    if name == "get_catalyst_events":
        days = min(args.get("days", 7), 30)
        impact = args.get("impact", "all")
        future = get_future_events(events, days)
        if impact == "high":
            future = [e for e in future if "High" in e.get("impact_analysis","") or "极高" in e.get("impact_analysis","")]
        elif impact == "critical":
            future = [e for e in future if "极高" in e.get("impact_analysis","")]
        lines = [f"Found {len(future)} catalyst events in the next {days} days.", ""]
        for i, e in enumerate(future, 1):
            lines.append(f"{i}. {fmt_event(e)}")
        if not future:
            lines.append("No events found.")
        send_response(req_id, {"content": [{"type": "text", "text": "\n".join(lines)}]})

    elif name == "search_catalyst_events":
        query = args.get("query","").lower()
        days = min(args.get("days", 30), 30)
        if not query:
            send_response(req_id, None, {"code": -32602, "message": "query is required"})
            return
        future = get_future_events(events, days)
        matched = [e for e in future if query in e.get("title","").lower() or query in e.get("type","").lower()]
        lines = [f"Found {len(matched)} events matching '{query}' in the next {days} days.", ""]
        for i, e in enumerate(matched, 1):
            lines.append(f"{i}. {fmt_event(e)}")
        if not matched:
            lines.append("No matching events found.")
        send_response(req_id, {"content": [{"type": "text", "text": "\n".join(lines)}]})

    else:
        send_response(req_id, None, {"code": -32601, "message": f"Unknown tool: {name}"})

def read_message():
    """Read one JSON-RPC message from stdin with Content-Length framing."""
    headers = {}
    while True:
        line = sys.stdin.readline()
        if not line:
            return None
        stripped = line.strip()
        if not stripped:
            break
        key, val = stripped.split(": ", 1)
        headers[key] = val
    length = int(headers.get("Content-Length", 0))
    if length == 0:
        return None
    body = sys.stdin.read(length)
    return json.loads(body)

def main():
    while True:
        try:
            msg = read_message()
            if msg is None:
                break
            method = msg.get("method")
            rid = msg.get("id")
            params = msg.get("params", {})

            if method == "initialize":
                handle_initialize(rid)
            elif method == "tools/list":
                handle_tools_list(rid)
            elif method == "tools/call":
                handle_tool_call(rid, params.get("name",""), params.get("arguments",{}))
            elif method == "notifications/initialized":
                pass  # no response
            elif rid is not None:
                send_response(rid, None, {"code": -32601, "message": f"Method not found: {method}"})
        except (EOFError, Exception) as e:
            break

if __name__ == "__main__":
    main()
