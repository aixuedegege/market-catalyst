#!/usr/bin/env python3
"""
Catalyst Calendar MCP Server — stdio JSON-RPC (SQLite backend)
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
import sqlite3
from datetime import datetime, timezone, timedelta

DB_PATH = "/data/ai/tmp/catalyst.db"
PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "catalyst-calendar"
SERVER_VERSION = "3.0.0"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def fmt_event(e):
    """Format event for MCP text output with English weekday and result info"""
    date_str = e.get("datetime_utc", "N/A")[:10]
    weekday = e.get("weekday_en", "")
    time_str = e.get("datetime_utc", "N/A")[11:16]
    base = f"[{date_str} {weekday} {time_str} UTC] {e.get('title','N/A')} | Impact: {e.get('impact_analysis','N/A')} | Assets: {e.get('asset_impact','N/A')}"
    
    # Add result info if resolved
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
            "description": "Fetch macroeconomic catalyst events from SQLite database. Returns precise UTC times, English weekday names, impact levels, affected assets, and resolution results for past events.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Days ahead to fetch (default: 7, max: 30)", "default": 7},
                    "impact": {"type": "string", "description": "Filter: 'all', 'high', or 'critical'", "enum": ["all", "high", "critical"], "default": "all"},
                    "type_filter": {"type": "string", "description": "Filter by event type, e.g. 'FOMC', 'CPI', 'NFP'"},
                    "status": {"type": "string", "description": "Filter by resolution status: 'future' (upcoming only), 'resolved' (has actual result), 'pending' (past but no result yet), 'all' (default)", "enum": ["future", "resolved", "pending", "all"], "default": "future"}
                }
            }
        },
        {
            "name": "search_catalyst_events",
            "description": "Search catalyst events by keyword (e.g., 'CPI', 'FOMC', 'NFP', 'Bitcoin'). Returns precise UTC/BJS times with weekday and resolution results.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keyword, e.g. 'CPI', 'FOMC', 'Fed', 'NFP', 'Bitcoin'"},
                    "days": {"type": "integer", "description": "Days ahead to search within (default: 30)", "default": 30},
                    "include_past": {"type": "boolean", "description": "Include past events in search results", "default": false}
                },
                "required": ["query"]
            }
        },
        {
            "name": "get_event_result",
            "description": "Get the detailed resolution result of a specific event, including actual value, status, summary, and news notes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "integer", "description": "The event ID from the database"}
                },
                "required": ["event_id"]
            }
        },
        {
            "name": "get_event_stats",
            "description": "Get database statistics: total events, date range, distribution by type and impact level, resolution counts.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        }
    ]})

def handle_tool_call(req_id, name, args):
    try:
        conn = get_db()
        now = datetime.now(timezone.utc)

        if name == "get_catalyst_events":
            days = min(args.get("days", 7), 30)
            impact = args.get("impact", "all")
            type_filter = args.get("type_filter", "")
            status = args.get("status", "future")

            cutoff = now + timedelta(days=days)
            now_str = now.strftime("%Y-%m-%dT%H:%M:%S")
            cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S")

            # Build query based on status
            if status == "future":
                query = "SELECT * FROM events WHERE datetime_utc >= ? AND datetime_utc <= ?"
                params = [now_str, cutoff_str]
            elif status == "resolved":
                query = "SELECT * FROM events WHERE actual_value IS NOT NULL AND datetime_utc < ? ORDER BY datetime_utc DESC LIMIT 50"
                params = [now_str]
            elif status == "pending":
                query = "SELECT * FROM events WHERE actual_value IS NULL AND datetime_utc < ? ORDER BY datetime_utc DESC LIMIT 50"
                params = [now_str]
            else:  # all
                query = "SELECT * FROM events WHERE datetime_utc <= ? ORDER BY datetime_utc DESC LIMIT 100"
                params = [cutoff_str]

            if impact == "high":
                query += " AND (impact_analysis LIKE ? OR impact_analysis LIKE ?)"
                params.extend(["%High%", "%极高%"])
            elif impact == "critical":
                query += " AND impact_analysis LIKE ?"
                params.append("%极高%")

            if type_filter:
                query += " AND (event_type LIKE ? OR title LIKE ?)"
                params.extend([f"%{type_filter}%", f"%{type_filter}%"])

            query += " ORDER BY datetime_utc ASC"
            rows = conn.execute(query, params).fetchall()

            status_label = {"future": "upcoming", "resolved": "resolved", "pending": "pending resolution", "all": "total"}.get(status, status)
            lines = [f"Found {len(rows)} {status_label} catalyst events.", ""]
            for i, r in enumerate(rows, 1):
                lines.append(f"{i}. {fmt_event(dict(r))}")
            if not rows:
                lines.append("No events found.")
            send_response(req_id, {"content": [{"type": "text", "text": "\n".join(lines)}]})

        elif name == "search_catalyst_events":
            query_text = args.get("query","").lower()
            days = min(args.get("days", 30), 30)
            include_past = args.get("include_past", False)
            if not query_text:
                send_response(req_id, None, {"code": -32602, "message": "query is required"})
                return

            cutoff = now + timedelta(days=days)
            now_str = now.strftime("%Y-%m-%dT%H:%M:%S")
            cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S")

            if include_past:
                sql = ("SELECT * FROM events WHERE "
                       "(LOWER(title) LIKE ? OR LOWER(event_type) LIKE ? OR LOWER(impact_analysis) LIKE ?) "
                       "ORDER BY datetime_utc DESC LIMIT 100")
                rows = conn.execute(sql, [f"%{query_text}%", f"%{query_text}%", f"%{query_text}%"]).fetchall()
            else:
                sql = ("SELECT * FROM events WHERE datetime_utc >= ? AND datetime_utc <= ? "
                       "AND (LOWER(title) LIKE ? OR LOWER(event_type) LIKE ? OR LOWER(impact_analysis) LIKE ?) "
                       "ORDER BY datetime_utc ASC")
                rows = conn.execute(sql, [now_str, cutoff_str, f"%{query_text}%", f"%{query_text}%", f"%{query_text}%"]).fetchall()

            lines = [f"Found {len(rows)} events matching '{query_text}'.", ""]
            for i, r in enumerate(rows, 1):
                lines.append(f"{i}. {fmt_event(dict(r))}")
            if not rows:
                lines.append("No matching events found.")
            send_response(req_id, {"content": [{"type": "text", "text": "\n".join(lines)}]})

        elif name == "get_event_result":
            event_id = args.get("event_id")
            if not event_id:
                send_response(req_id, None, {"code": -32602, "message": "event_id is required"})
                return

            row = conn.execute("SELECT * FROM events WHERE id = ?", [event_id]).fetchone()
            if not row:
                send_response(req_id, None, {"code": -32604, "message": f"Event {event_id} not found"})
                return

            e = dict(row)
            actual = e.get("actual_value")
            
            lines = [
                f"Event #{e['id']}: {e['title']}",
                f"Time: {e['datetime_utc']} ({e['weekday_en']})",
                f"Type: {e['event_type']}",
                f"Impact: {e.get('impact_analysis', 'N/A')}",
                f"Assets: {e.get('asset_impact', 'N/A')}",
                f"Estimate: {e.get('estimate', 'N/A')} {e.get('unit', '') or ''}",
                f"Previous: {e.get('previous', 'N/A')} {e.get('unit', '') or ''}",
                ""
            ]
            
            if actual:
                if actual == "AUTO_RESOLVE_FAILED":
                    lines.append("⚠️ Auto-resolution failed, awaiting manual input")
                else:
                    lines.append(f"✅ Actual Value: {actual}")
                    lines.append(f"Status: {e.get('result_status', 'unknown')}")
                    if e.get("result_summary"):
                        lines.append(f"Summary: {e['result_summary']}")
                    if e.get("news_notes"):
                        lines.append(f"\n📝 Notes:\n{e['news_notes']}")
                    if e.get("resolution_source"):
                        lines.append(f"\nSource: {e['resolution_source']}")
                    if e.get("resolved_at"):
                        lines.append(f"Resolved at: {e['resolved_at']}")
            else:
                lines.append("⏳ Not yet resolved - awaiting data publication")
            
            send_response(req_id, {"content": [{"type": "text", "text": "\n".join(lines)}]})

        elif name == "get_event_stats":
            total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            future = conn.execute("SELECT COUNT(*) FROM events WHERE datetime_utc >= ?", [now.strftime("%Y-%m-%dT%H:%M:%S")]).fetchone()[0]
            past = total - future
            resolved = conn.execute("SELECT COUNT(*) FROM events WHERE actual_value IS NOT NULL").fetchone()[0]
            pending = conn.execute("SELECT COUNT(*) FROM events WHERE datetime_utc < ? AND actual_value IS NULL", [now.strftime("%Y-%m-%dT%H:%M:%S")]).fetchone()[0]
            date_range = conn.execute("SELECT MIN(datetime_utc) as first, MAX(datetime_utc) as last FROM events").fetchone()

            by_type = conn.execute("SELECT event_type, COUNT(*) as cnt FROM events WHERE datetime_utc >= ? GROUP BY event_type ORDER BY cnt DESC", [now.strftime("%Y-%m-%dT%H:%M:%S")]).fetchall()
            by_impact = conn.execute("SELECT impact_analysis, COUNT(*) as cnt FROM events WHERE datetime_utc >= ? GROUP BY impact_analysis ORDER BY cnt DESC", [now.strftime("%Y-%m-%dT%H:%M:%S")]).fetchall()

            result_text = [
                f"Catalyst Database Statistics",
                f"Total events: {total} (Future: {future}, Past: {past})",
                f"Resolution: {resolved} resolved, {pending} pending",
                f"Date range: {date_range['first'][:10]} to {date_range['last'][:10]}",
                f"",
                f"Future events by type:"
            ]
            for r in by_type:
                result_text.append(f"  {r['event_type']}: {r['cnt']}")
            result_text.append(f"")
            result_text.append(f"Future events by impact:")
            for r in by_impact:
                result_text.append(f"  {r['impact_analysis']}: {r['cnt']}")

            send_response(req_id, {"content": [{"type": "text", "text": "\n".join(result_text)}]})

        else:
            send_response(req_id, None, {"code": -32601, "message": f"Unknown tool: {name}"})

        conn.close()
    except Exception as e:
        send_response(req_id, None, {"code": -32603, "message": str(e)})

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
                pass
            elif rid is not None:
                send_response(rid, None, {"code": -32601, "message": f"Method not found: {method}"})
        except (EOFError, Exception) as e:
            break

if __name__ == "__main__":
    main()
