#!/usr/bin/env python3
"""
Market Catalyst MCP Server — FastMCP HTTP mode
Provides ALL data visible on the frontend as structured MCP tools.

Run:
  /tmp/mcp_venv/bin/python3 /data/ai/tmp/mcp_server_fast.py --host 127.0.0.1 --port 17003

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
from collections import defaultdict

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


def classify_impact(impact_str):
    """Classify impact level: critical, high, medium, low"""
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
        "data_updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    by_type = defaultdict(int)
    for e in future:
        t = e.get("type", "Other")
        by_type[t] += 1
    stats["by_type"] = dict(by_type)

    lines = [
        f"📊 Catalyst Dashboard Stats (next {days} days)",
        f"  Total events: {stats['total']}",
        f"  This week (7d): {stats['this_week']}",
        f"  This month (30d): {stats['this_month']}",
        f"  Critical (极高): {stats['critical']}",
        f"  High (高): {stats['high']}",
        f"  Data updated: {stats['data_updated_at']}",
        "",
        "Events by type:",
    ]
    for t, count in sorted(by_type.items(), key=lambda x: -x[1]):
        lines.append(f"  {t}: {count}")

    return "\n".join(lines)


@mcp.tool()
def get_resonance_days(days: int = 7) -> str:
    """Find resonance days — dates with 3 or more high-impact events overlapping.
    Mirrors the 'Resonance' section on the frontend.

    Args:
        days: Days ahead to scan (default: 7, max: 30)
    """
    events = load_events()
    days = min(max(days, 1), 30)
    future = get_future_events(events, days)

    # Group high+ events by date
    date_events = defaultdict(list)
    for e in future:
        level = classify_impact(e.get("impact_analysis", ""))
        if level in ("critical", "high"):
            date_str = e.get("date", "")[:10]
            date_events[date_str].append(e)

    # Find dates with 3+ overlapping high-impact events
    resonance = []
    for date_str, evts in sorted(date_events.items()):
        if len(evts) >= 3:
            resonance.append({
                "date": date_str,
                "count": len(evts),
                "events": [
                    {"title": e["title"], "impact": e["impact_analysis"], "asset_impact": e.get("asset_impact", "")}
                    for e in evts
                ],
            })

    if not resonance:
        return f"⚠️ Resonance scan (next {days} days): No days with 3+ overlapping high-impact events found."

    lines = [f"⚠️ Resonance Days (next {days} days) — {len(resonance)} date(s) with overlapping events:", ""]
    for r in resonance:
        lines.append(f"📅 {r['date']} — {r['count']} events overlapping:")
        for ev in r["events"]:
            lines.append(f"  • {ev['title']} | Impact: {ev['impact']}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def get_events_by_type(days: int = 7, type_filter: str = "all") -> str:
    """Get events grouped by category (Macro, Earnings, IPO, etc.) — mirrors the frontend category sections.

    Args:
        days: Days ahead to fetch (default: 7, max: 30)
        type_filter: Filter by event type name (e.g., 'Macro', 'Earnings'), or 'all' for all types
    """
    events = load_events()
    days = min(max(days, 1), 30)
    future = get_future_events(events, days)

    by_type = defaultdict(list)
    for e in future:
        t = e.get("type", "Other")
        by_type[t].append(e)

    if type_filter.lower() != "all":
        matched_types = [t for t in by_type if type_filter.lower() in t.lower()]
        if matched_types:
            by_type = {t: by_type[t] for t in matched_types}
        else:
            return f"No event type matching '{type_filter}'. Available types: {', '.join(sorted(by_type.keys()))}"

    lines = [f"📂 Events by Category (next {days} days):", ""]
    for t in sorted(by_type.keys()):
        evts = sorted(by_type[t], key=lambda x: x.get("date", ""))
        lines.append(f"## {t} ({len(evts)} events)")
        for e in evts:
            date_part = e.get("date", "")[:10]
            time_part = e.get("date", "")[11:16] if len(e.get("date", "")) > 11 else ""
            level = classify_impact(e.get("impact_analysis", ""))
            lines.append(
                f"  [{level.upper()}] {date_part} {time_part} | {e['title']} | "
                f"Impact: {e['impact_analysis']} | Assets: {e.get('asset_impact', '')}"
            )
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def get_catalyst_events(days: int = 7, impact: str = "all") -> str:
    """Fetch upcoming macroeconomic catalyst events with full details.
    Mirrors the main event list on the frontend.

    Args:
        days: Days ahead to fetch (default: 7, max: 30)
        impact: Filter level — 'all', 'high', 'medium', or 'critical'
    """
    events = load_events()
    days = min(max(days, 1), 30)
    future = get_future_events(events, days)

    if impact != "all":
        future = [e for e in future if classify_impact(e.get("impact_analysis", "")) == impact]

    lines = [f"Found {len(future)} catalyst events in the next {days} days.", ""]
    for i, e in enumerate(future, 1):
        date_part = e.get("date", "")[:10]
        time_part = e.get("date", "")[11:16] if len(e.get("date", "")) > 11 else ""
        level = classify_impact(e.get("impact_analysis", ""))
        lines.append(
            f"{i}. [{level.upper()}] {date_part} {time_part} | {e['title']} | "
            f"Impact: {e['impact_analysis']} | Assets: {e.get('asset_impact', '')} | "
            f"Type: {e.get('type', '')} | Source: {e.get('source', '')}"
        )
    if not future:
        lines.append("No events found for the specified criteria.")
    return "\n".join(lines)


@mcp.tool()
def search_catalyst_events(query: str, days: int = 30) -> str:
    """Search catalyst events by keyword (e.g., 'CPI', 'FOMC', 'NFP', 'Fed').
    Case-insensitive search in title and type fields.

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
    print(f"[*] Tools: get_catalyst_stats, get_resonance_days, get_events_by_type, get_catalyst_events, search_catalyst_events")
    mcp.run(transport="streamable-http")
