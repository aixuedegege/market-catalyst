#!/usr/bin/env python3
"""
Market Catalyst MCP Server — FastMCP HTTP mode
Serves MCP tools via Streamable HTTP at /mcp endpoint.

Run:
  /tmp/mcp_venv/bin/python3 /data/ai/tmp/mcp_server_fast.py --host 127.0.0.1 --port 17003

Caddy reverse proxy (already configured for catalyst.infodream.asia):
  handle /mcp* {
    reverse_proxy 127.0.0.1:17003
  }

Client config (Cursor / Claude Desktop):
{
  "mcpServers": {
    "market-catalyst": {
      "url": "https://catalyst.infodream.asia/mcp"
    }
  }
}
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

# Add venv path for mcp package
sys.path.insert(0, "/tmp/mcp_venv/lib/python3.11/site-packages")

from mcp.server.fastmcp import FastMCP

DATA_FILE = "/data/ai/tmp/catalyst_events.json"

mcp = FastMCP(
    name="market-catalyst",
    debug=False,
    host="127.0.0.1",
    port=17003,
    streamable_http_path="/mcp",
    stateless_http=True,
)


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
    return (
        f"[{e.get('date', 'N/A')}] {e.get('title', 'N/A')} | "
        f"Impact: {e.get('impact_analysis', 'N/A')} | "
        f"Assets: {e.get('asset_impact', 'N/A')}"
    )


@mcp.tool()
def get_catalyst_events(days: int = 7, impact: str = "all") -> str:
    """Fetch upcoming macroeconomic catalyst events. Filter by days ahead and impact level.

    Args:
        days: Days ahead to fetch (default: 7, max: 30)
        impact: Filter level — 'all', 'high', or 'critical'
    """
    events = load_events()
    days = min(max(days, 1), 30)
    future = get_future_events(events, days)

    if impact == "high":
        future = [
            e for e in future
            if "High" in e.get("impact_analysis", "") or "极高" in e.get("impact_analysis", "")
        ]
    elif impact == "critical":
        future = [e for e in future if "极高" in e.get("impact_analysis", "")]

    lines = [f"Found {len(future)} catalyst events in the next {days} days.", ""]
    for i, e in enumerate(future, 1):
        lines.append(f"{i}. {fmt_event(e)}")
    if not future:
        lines.append("No events found for the specified criteria.")
    return "\n".join(lines)


@mcp.tool()
def search_catalyst_events(query: str, days: int = 30) -> str:
    """Search catalyst events by keyword (e.g., 'CPI', 'FOMC', 'NFP', 'Fed').

    Args:
        query: Search keyword (case-insensitive)
        days: Days ahead to search within (default: 30, max: 30)
    """
    events = load_events()
    query = query.lower().strip()
    if not query:
        return "Error: 'query' parameter is required."

    days = min(max(days, 1), 30)
    future = get_future_events(events, days)
    matched = [
        e for e in future
        if query in e.get("title", "").lower() or query in e.get("type", "").lower()
    ]

    lines = [f"Found {len(matched)} events matching '{query}' in the next {days} days.", ""]
    for i, e in enumerate(matched, 1):
        lines.append(f"{i}. {fmt_event(e)}")
    if not matched:
        lines.append("No matching events found.")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=17003)
    args = parser.parse_args()

    mcp._host = args.host
    mcp._port = args.port

    print(f"[*] Market Catalyst MCP Server starting on http://{args.host}:{args.port}/mcp")
    print(f"[*] Streamable HTTP endpoint: /mcp")
    mcp.run(transport="streamable-http")
