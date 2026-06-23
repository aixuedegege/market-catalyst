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

# Add tmp path for db module if running from workspace
sys.path.insert(0, "/data/ai/tmp")
try:
    from catalyst_db import get_stats as get_db_stats, query_events
    HAS_DB = True
except ImportError:
    HAS_DB = False

# Fallback to JSON if DB not available
DATA_FILE = "/data/ai/tmp/catalyst_events.json"

sys.path.insert(0, "/tmp/mcp_venv/lib/python3.11/site-packages")
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="market-catalyst",
    debug=False,
    host="127.0.0.1",
    port=17003,
)


def load_events():
    """Fallback for JSON mode."""
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def classify_impact(impact_str):
    if "极高" in impact_str or "Extremely High" in impact_str:
        return "critical"
    if "High" in impact_str or "高" in impact_str:
        return "high"
    if "Medium" in impact_str or "中" in impact_str:
        return "medium"
    return "low"


def fmt_event(e):
    """Format event with English weekday and result info."""
    date_str = e.get("datetime_utc", e.get("date", "N/A"))[:10]
    weekday = e.get("weekday_en", "")
    time_str = e.get("datetime_utc", e.get("date", "N/A"))[11:16]
    base = f"[{date_str} {weekday} {time_str} UTC] {e.get('title','N/A')} | Impact: {e.get('impact_analysis', 'N/A')} | Assets: {e.get('asset_impact', 'N/A')}"
    
    actual = e.get("actual_value")
    if actual:
        if actual == "AUTO_RESOLVE_FAILED":
            return f"{base} | ⚠️ Auto-resolve failed"
        status = e.get("result_status", "")
        summary = e.get("result_summary", "")
        result_part = f"✅ Actual: {actual}"
        if status:
            result_part += f" ({status})"
        if summary:
            result_part += f" - {summary}"
        return f"{base} | {result_part}"
    
    return base


@mcp.tool()
def get_catalyst_stats(days: int = 30) -> str:
    """Get dashboard statistics: total events, this week count, this month count, critical/high counts."""
    if HAS_DB:
        stats = get_db_stats()
        lines = [
            "📊 Catalyst Dashboard Stats",
            f"  Total Future: {stats['total_future']}",
            f"  Next 7 days: {stats['next_7_days']}",
            f"  Next 30 days: {stats['next_30_days']}",
            f"  Total Past: {stats['total_past']}",
            f"  Resolved: {stats['resolved_count']}",
            f"  Pending Resolution: {stats['pending_resolution']}",
            "", "Events by type (future):",
        ]
        for t, c in sorted(stats.get("by_type_future", {}).items(), key=lambda x: -x[1]):
            lines.append(f"  {t}: {c}")
        return "\n".join(lines)
    else:
        events = load_events()
        future = [e for e in events if e.get("date", "")[:10] >= datetime.now(timezone.utc).strftime("%Y-%m-%d")]
        return f"📊 Stats: Total {len(future)} future events (Legacy Mode)"


@mcp.tool()
def get_resonance_days(days: int = 7) -> str:
    """Find resonance days — dates with 3+ high-impact events overlapping."""
    if not HAS_DB:
        return "Resonance days feature requires SQLite backend."
        
    now = datetime.now(timezone.utc)
    future = query_events(future_only=True, future_days=days)
    
    date_events = defaultdict(list)
    for e in future:
        if classify_impact(e.get("impact_analysis", "")) in ("critical", "high"):
            date_events[e.get("datetime_utc", "")[:10]].append(e)
            
    resonance = []
    for date_str, evts in sorted(date_events.items()):
        if len(evts) >= 3:
            resonance.append({"date": date_str, "count": len(evts), "events": evts})
            
    if not resonance:
        return f"⚠️ No resonance days found in next {days} days."
        
    lines = [f"⚠️ Resonance Days (next {days} days) — {len(resonance)} date(s):", ""]
    for r in resonance:
        lines.append(f"📅 {r['date']} — {r['count']} events:")
        for ev in r["events"]:
            lines.append(f"  • {ev['title']} | {ev['impact_analysis']}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def get_events_by_type(days: int = 7, type_filter: str = "all") -> str:
    """Get events grouped by category. Supports 'future', 'resolved', 'pending' status."""
    if HAS_DB:
        future = query_events(future_only=True, future_days=days)
    else:
        events = load_events()
        cutoff = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        future = [e for e in events if now_str <= e.get("date", "")[:10] <= cutoff]
        
    by_type = defaultdict(list)
    for e in future:
        t = e.get("type", e.get("event_type", "Other"))
        by_type[t].append(e)
        
    if type_filter.lower() != "all":
        matched = [t for t in by_type if type_filter.lower() in t.lower()]
        if matched:
            by_type = {t: by_type[t] for t in matched}
        else:
            return f"No type matching '{type_filter}'. Available: {', '.join(sorted(by_type.keys()))}"
            
    lines = [f"📂 Events by Category (next {days} days):", ""]
    for t in sorted(by_type):
        evts = sorted(by_type[t], key=lambda x: x.get("datetime_utc", x.get("date", "")))
        lines.append(f"## {t} ({len(evts)} events)")
        for e in evts:
            level = classify_impact(e.get("impact_analysis", ""))
            date_str = e.get("datetime_utc", e.get("date", ""))
            time_part = date_str[11:16] if len(date_str) > 11 else ""
            weekday = e.get("weekday_en", "")
            lines.append(f"  [{level.upper()}] {date_str[:10]} {weekday} {time_part} | {e['title']} | {e['impact_analysis']}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def get_catalyst_events(days: int = 7, impact: str = "all", status: str = "future") -> str:
    """Fetch events with full details.
    Args:
        days: Days ahead (default: 7, max: 30)
        impact: 'all', 'high', 'medium', or 'critical'
        status: 'future' (upcoming), 'resolved' (past with result), 'pending' (past no result)
    """
    if HAS_DB:
        resolved_filter = None
        if status == "resolved":
            resolved_filter = True
            future_only = False
        elif status == "pending":
            resolved_filter = False
            future_only = False
        else:
            future_only = True
            
        events = query_events(future_only=future_only, future_days=days, resolved=resolved_filter)
    else:
        events = load_events()
        cutoff = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        events = [e for e in events if now_str <= e.get("date", "")[:10] <= cutoff]
        
    if impact != "all":
        events = [e for e in events if classify_impact(e.get("impact_analysis", "")) == impact]
        
    lines = [f"Found {len(events)} events (status: {status}).", ""]
    for i, e in enumerate(events, 1):
        lines.append(f"{i}. {fmt_event(e)}")
    if not events:
        lines.append("No events found.")
    return "\n".join(lines)


@mcp.tool()
def search_catalyst_events(query: str, days: int = 30, include_past: bool = False) -> str:
    """Search catalyst events by keyword.
    Args:
        query: Search keyword (case-insensitive)
        days: Days ahead (default: 30, max: 30)
        include_past: Include past events in search
    """
    query = query.lower().strip()
    if not query:
        return "Error: 'query' parameter is required."
        
    if HAS_DB:
        events = query_events(future_only=not include_past, future_days=days, keyword=query)
    else:
        events = load_events()
        cutoff = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        events = [e for e in events if query in e.get("title", "").lower() or query in e.get("type", "").lower()]
        if not include_past:
            events = [e for e in events if now_str <= e.get("date", "")[:10] <= cutoff]
            
    lines = [f"Found {len(events)} events matching '{query}'.", ""]
    for i, e in enumerate(events, 1):
        lines.append(f"{i}. {fmt_event(e)}")
    if not events:
        lines.append("No matching events found.")
    return "\n".join(lines)


@mcp.tool()
def get_event_result(event_id: int) -> str:
    """Get detailed resolution result for a specific event ID."""
    if not HAS_DB:
        return "Error: Result lookup requires SQLite backend."
        
    import sqlite3
    DB_PATH = "/data/ai/tmp/catalyst.db"
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM events WHERE id = ?", [event_id]).fetchone()
    conn.close()
    
    if not row:
        return f"Error: Event {event_id} not found."
        
    e = dict(row)
    lines = [
        f"Event #{e['id']}: {e['title']}",
        f"Time: {e['datetime_utc']} ({e['weekday_en']})",
        f"Type: {e['event_type']}",
        f"Impact: {e.get('impact_analysis', 'N/A')}",
        f"Estimate: {e.get('estimate', 'N/A')} {e.get('unit', '')}",
        f"Previous: {e.get('previous', 'N/A')}"
    ]
    
    actual = e.get("actual_value")
    if actual:
        if actual == "AUTO_RESOLVE_FAILED":
            lines.append("⚠️ Auto-resolution failed, awaiting manual input")
        else:
            lines.append(f"✅ Actual Value: {actual} ({e.get('result_status', 'unknown')})")
            lines.append(f"Summary: {e.get('result_summary', '')}")
            if e.get("news_notes"):
                lines.append(f"\n📝 Notes:\n{e['news_notes']}")
            if e.get("resolution_source"):
                lines.append(f"Source: {e['resolution_source']}")
    else:
        lines.append("⏳ Not yet resolved")
        
    return "\n".join(lines)


if __name__ == "__main__":
    print("[*] Market Catalyst MCP Server (SSE mode)")
    print("[*] GET  /mcp/sse      → SSE stream")
    print("[*] POST /mcp/messages → JSON-RPC endpoint")
    mcp.run(transport="sse", mount_path="/mcp")
