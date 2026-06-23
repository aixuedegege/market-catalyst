#!/usr/bin/env python3
"""
Catalyst Event Resolver — 事件结果回填系统
用法:
  python3 catalyst_resolver.py list          # 列出所有未解决的历史事件
  python3 catalyst_resolver.py resolve <id> --value "3.2%" --status "worse" --summary "高于预期" --notes "详细描述" --source "URL"
  python3 catalyst_resolver.py resolve <id> --auto   # 标记为自动处理失败
  python3 catalyst_resolver.py stats         # 显示解决统计
"""

import sqlite3
import sys
import json
import argparse
from datetime import datetime, timezone

DB_PATH = "/data/ai/tmp/catalyst.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def list_pending():
    """列出所有未解决的历史事件"""
    conn = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    rows = conn.execute("""
        SELECT id, title, datetime_utc, weekday_en, event_type, 
               impact_analysis, estimate, previous, unit, symbol
        FROM events 
        WHERE datetime_utc < ? AND actual_value IS NULL
        ORDER BY datetime_utc DESC
    """, [now]).fetchall()
    conn.close()
    
    print(f"Found {len(rows)} pending events to resolve:")
    print("=" * 80)
    
    pending_list = []
    for r in rows:
        event = {
            "id": r["id"],
            "title": r["title"],
            "datetime_utc": r["datetime_utc"],
            "weekday": r["weekday_en"],
            "type": r["event_type"],
            "impact": r["impact_analysis"],
            "estimate": r["estimate"],
            "previous": r["previous"],
            "unit": r["unit"],
            "symbol": r["symbol"],
        }
        pending_list.append(event)
        
        print(f"\nID: {r['id']}")
        print(f"  Title: {r['title']}")
        print(f"  Time: {r['datetime_utc']} ({r['weekday_en']})")
        print(f"  Type: {r['event_type']}")
        print(f"  Impact: {r['impact_analysis']}")
        if r["estimate"]:
            print(f"  Estimate: {r['estimate']} {r['unit'] or ''}")
        if r["previous"]:
            print(f"  Previous: {r['previous']} {r['unit'] or ''}")
    
    # Also output JSON for agent consumption
    print("\n" + "=" * 80)
    print("JSON_OUTPUT:")
    print(json.dumps(pending_list, ensure_ascii=False, indent=2))
    
    return pending_list

def resolve_event(event_id, value, status, summary, notes, source):
    """写入事件结果"""
    conn = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Verify event exists
    event = conn.execute("SELECT id, title FROM events WHERE id = ?", [event_id]).fetchone()
    if not event:
        print(f"Error: Event {event_id} not found")
        conn.close()
        return False
    
    conn.execute("""
        UPDATE events SET 
            actual_value = ?,
            result_status = ?,
            result_summary = ?,
            news_notes = ?,
            resolved_at = ?,
            resolution_source = ?
        WHERE id = ?
    """, [value, status, summary, notes, now, source, event_id])
    
    conn.commit()
    conn.close()
    
    print(f"✅ Resolved event {event_id}: {event['title']}")
    print(f"   Value: {value}")
    print(f"   Status: {status}")
    if summary:
        print(f"   Summary: {summary}")
    return True

def mark_failed(event_id):
    """标记为自动处理失败"""
    conn = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    conn.execute("""
        UPDATE events SET 
            actual_value = 'AUTO_RESOLVE_FAILED',
            result_status = 'unknown',
            result_summary = '自动采集失败，待人工补充',
            news_notes = NULL,
            resolved_at = ?,
            resolution_source = NULL
        WHERE id = ?
    """, [now, event_id])
    
    conn.commit()
    conn.close()
    print(f"⚠️  Marked event {event_id} as auto-resolve failed")

def show_stats():
    """显示解决统计"""
    conn = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    
    total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    resolved = conn.execute("SELECT COUNT(*) FROM events WHERE actual_value IS NOT NULL").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM events WHERE datetime_utc < ? AND actual_value IS NULL", [now]).fetchone()[0]
    future = conn.execute("SELECT COUNT(*) FROM events WHERE datetime_utc >= ?", [now]).fetchone()[0]
    
    by_status = conn.execute("""
        SELECT result_status, COUNT(*) as cnt 
        FROM events 
        WHERE actual_value IS NOT NULL 
        GROUP BY result_status
    """).fetchall()
    
    by_type = conn.execute("""
        SELECT e.event_type, COUNT(*) as cnt 
        FROM events e 
        WHERE e.datetime_utc < ? AND e.actual_value IS NULL
        GROUP BY e.event_type 
        ORDER BY cnt DESC
    """, [now]).fetchall()
    
    conn.close()
    
    print("Catalyst Resolution Stats:")
    print(f"  Total events: {total}")
    print(f"  Future events: {future}")
    print(f"  Resolved: {resolved}")
    print(f"  Pending: {pending}")
    print()
    print("By resolution status:")
    for r in by_status:
        print(f"  {r['result_status']}: {r['cnt']}")
    print()
    print("Pending by type:")
    for r in by_type:
        print(f"  {r['event_type']}: {r['cnt']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Catalyst Event Resolver")
    subparsers = parser.add_subparsers(dest="command")
    
    # list command
    list_parser = subparsers.add_parser("list", help="List pending events")
    
    # resolve command
    resolve_parser = subparsers.add_parser("resolve", help="Resolve an event")
    resolve_parser.add_argument("event_id", type=int, help="Event ID")
    resolve_parser.add_argument("--value", type=str, help="Actual value/result")
    resolve_parser.add_argument("--status", type=str, choices=["better", "worse", "as_expected", "neutral", "unknown"], help="Result status")
    resolve_parser.add_argument("--summary", type=str, default="", help="One-line summary")
    resolve_parser.add_argument("--notes", type=str, default="", help="Detailed news notes")
    resolve_parser.add_argument("--source", type=str, default="", help="Source URL")
    resolve_parser.add_argument("--auto", action="store_true", help="Mark as auto-resolve failed")
    
    # stats command
    stats_parser = subparsers.add_parser("stats", help="Show resolution stats")
    
    args = parser.parse_args()
    
    if args.command == "list":
        list_pending()
    elif args.command == "resolve":
        if args.auto:
            mark_failed(args.event_id)
        else:
            if not args.value:
                print("Error: --value is required (or use --auto)")
                sys.exit(1)
            resolve_event(args.event_id, args.value, args.status or "unknown", args.summary, args.notes, args.source)
    elif args.command == "stats":
        show_stats()
    else:
        parser.print_help()
