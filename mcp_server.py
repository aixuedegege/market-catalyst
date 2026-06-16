#!/usr/bin/env python3
"""
Market Catalyst MCP Server — FastMCP SSE mode
Serves MCP tools via SSE (Server-Sent Events) for compatibility with
Copilot SDK, Cursor, and other SSE-based MCP clients.

Endpoints:
  GET  /mcp/sse      → SSE stream (sends event: endpoint, then event: message)
  POST /mcp/messages → Receive JSON-RPC requests from clients

Client config (Cursor / Claude Desktop / Copilot SDK):
{
  "mcpServers": {
    "market-catalyst": {
      "url": "https://catalyst.infodream.asia/mcp/sse"
    }
  }
}
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, "/tmp/mcp_venv/lib/python3.11/site-packages")

from mcp.server.fastmcp import FastMCP

DATA_FILE = "/data/ai/tmp/catalyst_events.json"

mcp = FastMCP(
    name="market-catalyst",
    debug=False,
    host="127.0.0.1",
    port=17003,
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


def classify_impact(impact_str):
    if "极高" in impact_str or "Extremely High" in impact_str:
        return "critical"
    if "High" in impact_str or "高" in impact_str:
        return "high"
    if "Medium" in impact_str or "中" in impact_str:
        return "medium"
    return "low"


def fmt_event(e):
    return (
        f"[{e.get('date', 'N/A')}] {e.get('title', 'N/A')} | "
        f"Impact: {e.get('impact_analysis', 'N/A')} | "
        f"Assets: {e.get('asset_impact', 'N/A')}"
    )


@mcp.tool()
def get_catalyst_stats(days: int = 30) -> str:
    """Get dashboard statistics: total events, this week count, this month count, critical/high counts.
    Mirrors the stats cards shown on the frontend.

    Args:
        days: Days ahead to compute stats for (default: 30, max: 30)
    """
    events = load_events()
    days = min(max(days, 1), 30)
    future = get_future_events(events, days)
    now = datetime.now(timezone.utc)
    week_cutoff = (now + timedelta(days=7)).strftime("%Y-%m-%d")
    month_cutoff = (now + timedelta(days=30)).strftime("%Y-%m-%d")
    stats = {
        "total": len(future),
        "this_week": len([e for e in future if e.get("date", "")[:10] <= week_cutoff]),
        "this_month": len([e for e in future if e.get("date", "")[:10] <= month_cutoff]),
        "critical": len([e for e in future if classify_impact(e.get("impact_analysis", "")) == "critical"]),
        "high": len([e for e in future if classify_impact(e.get("impact_analysis", "")) == "high"]),
        "by_type": {},
    }
    by_type = defaultdict(int)
    for e in future:
        by_type[e.get("type", "Other")] += 1
    stats["by_type"] = dict(by_type)
    lines = [
        f"📊 Catalyst Dashboard Stats (next {days} days)",
        f"  Total: {stats['total']}",
        f"  This week (7d): {stats['this_week']}",
        f"  This month (30d): {stats['this_month']}",
        f"  Critical: {stats['critical']}",
        f"  High: {stats['high']}",
        "", "Events by type:",
    ]
    for t, c in sorted(by_type.items(), key=lambda x: -x[1]):
        lines.append(f"  {t}: {c}")
    return "\n".join(lines)


@mcp.tool()
def get_resonance_days(days: int = 7) -> str:
    """Find resonance days — dates with 3+ high-impact events overlapping.

    Args:
        days: Days ahead to scan (default: 7, max: 30)
    """
    events = load_events()
    days = min(max(days, 1), 30)
    future = get_future_events(events, days)
    date_events = defaultdict(list)
    for e in future:
        if classify_impact(e.get("impact_analysis", "")) in ("critical", "high"):
            date_events[e.get("date", "")[:10]].append(e)
    resonance = []
    for date_str, evts in sorted(date_events.items()):
        if len(evts) >= 3:
            resonance.append({"date": date_str, "count": len(evts),
                "events": [{"title": e["title"], "impact": e["impact_analysis"]} for e in evts]})
    if not resonance:
        return f"⚠️ No resonance days found in next {days} days."
    lines = [f"⚠️ Resonance Days (next {days} days) — {len(resonance)} date(s):", ""]
    for r in resonance:
        lines.append(f"📅 {r['date']} — {r['count']} events:")
        for ev in r["events"]:
            lines.append(f"  • {ev['title']} | {ev['impact']}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def get_events_by_type(days: int = 7, type_filter: str = "all") -> str:
    """Get events grouped by category (Macro, Earnings, IPO, etc.).

    Args:
        days: Days ahead (default: 7, max: 30)
        type_filter: Filter by type name or 'all'
    """
    events = load_events()
    days = min(max(days, 1), 30)
    future = get_future_events(events, days)
    by_type = defaultdict(list)
    for e in future:
        by_type[e.get("type", "Other")].append(e)
    if type_filter.lower() != "all":
        matched = [t for t in by_type if type_filter.lower() in t.lower()]
        if matched:
            by_type = {t: by_type[t] for t in matched}
        else:
            return f"No type matching '{type_filter}'. Available: {', '.join(sorted(by_type.keys()))}"
    lines = [f"📂 Events by Category (next {days} days):", ""]
    for t in sorted(by_type):
        evts = sorted(by_type[t], key=lambda x: x.get("date", ""))
        lines.append(f"## {t} ({len(evts)} events)")
        for e in evts:
            level = classify_impact(e.get("impact_analysis", ""))
            lines.append(f"  [{level.upper()}] {e['date'][:10]} {e['date'][11:16] if len(e['date'])>11 else ''} | {e['title']} | {e['impact_analysis']} | {e.get('asset_impact','')}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def get_catalyst_events(days: int = 7, impact: str = "all") -> str:
    """Fetch upcoming macroeconomic catalyst events with full details.

    Args:
        days: Days ahead (default: 7, max: 30)
        impact: 'all', 'high', 'medium', or 'critical'
    """
    events = load_events()
    days = min(max(days, 1), 30)
    future = get_future_events(events, days)
    if impact != "all":
        future = [e for e in future if classify_impact(e.get("impact_analysis", "")) == impact]
    lines = [f"Found {len(future)} events in next {days} days.", ""]
    for i, e in enumerate(future, 1):
        level = classify_impact(e.get("impact_analysis", ""))
        lines.append(f"{i}. [{level.upper()}] {e['date'][:10]} {e['date'][11:16] if len(e['date'])>11 else ''} | {e['title']} | {e['impact_analysis']} | {e.get('asset_impact','')} | {e.get('type','')} | {e.get('source','')}")
    if not future:
        lines.append("No events found.")
    return "\n".join(lines)


@mcp.tool()
def search_catalyst_events(query: str, days: int = 30) -> str:
    """Search catalyst events by keyword (e.g., 'CPI', 'FOMC', 'NFP').

    Args:
        query: Search keyword (case-insensitive)
        days: Days ahead (default: 30, max: 30)
    """
    events = load_events()
    query = query.lower().strip()
    if not query:
        return "Error: 'query' parameter is required."
    days = min(max(days, 1), 30)
    future = get_future_events(events, days)
    matched = [e for e in future if query in e.get("title", "").lower() or query in e.get("type", "").lower()]
    lines = [f"Found {len(matched)} events matching '{query}' in next {days} days.", ""]
    for i, e in enumerate(matched, 1):
        lines.append(f"{i}. {fmt_event(e)}")
    if not matched:
        lines.append("No matching events found.")
    return "\n".join(lines)


if __name__ == "__main__":
    print("[*] Market Catalyst MCP Server (SSE mode)")
    print("[*] GET  /mcp/sse      → SSE stream")
    print("[*] POST /mcp/messages → JSON-RPC endpoint")
    mcp.run(transport="sse", mount_path="/mcp")
