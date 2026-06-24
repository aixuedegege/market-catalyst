#!/usr/bin/env python3
"""
Catalyst Calendar — SQLite 数据库模块
提供事件存储、查询、历史数据导入接口
"""

import sqlite3
import json
import os
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Import Config
from config import DB_PATH, load_env

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

def _get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db(db_path: str = DB_PATH) -> None:
    conn = _get_connection(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            event_hash      TEXT UNIQUE NOT NULL,
            title           TEXT NOT NULL,
            datetime_utc    TEXT NOT NULL,
            datetime_bj     TEXT NOT NULL,
            weekday_en      TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            source          TEXT NOT NULL,
            source_url      TEXT,
            impact_level    TEXT,
            impact_analysis TEXT,
            asset_impact    TEXT,
            estimate        TEXT,
            previous        TEXT,
            unit            TEXT,
            symbol          TEXT,
            fetched_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS api_requests (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ip              TEXT,
            path            TEXT,
            query_params    TEXT,
            timestamp       TEXT,
            response_count  INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_datetime  ON events(datetime_utc);
        CREATE INDEX IF NOT EXISTS idx_type      ON events(event_type);
        CREATE INDEX IF NOT EXISTS idx_impact    ON events(impact_level);
        CREATE INDEX IF NOT EXISTS idx_hash      ON events(event_hash);
    """)
    conn.commit()
    conn.close()

def _parse_datetime(date_str: str) -> tuple[str, str, str]:
    """标准化时间：返回 (utc_iso, bj_iso, weekday_en)"""
    if not date_str:
        return ("", "", "")

    date_str = date_str.strip().replace("T", " ").replace("Z", "")
    # Try parsing with seconds
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt_utc = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
            break
        except ValueError:
            continue
    else:
        return (date_str, date_str, "")

    dt_bj = dt_utc + timedelta(hours=8)
    weekday_en = WEEKDAY_NAMES[dt_bj.weekday()]
    
    utc_iso = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    bj_iso = dt_bj.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    
    return (utc_iso, bj_iso, weekday_en)

def _event_hash(title: str, date_str: str, source: str) -> str:
    return hashlib.md5(f"{title}|{date_str}|{source}".encode()).hexdigest()[:12]

def insert_event(event: dict, db_path: str = DB_PATH) -> bool:
    """插入单个事件，返回 True=新插入 False=已存在"""
    h = _event_hash(event["title"], event.get("date", ""), event.get("source", ""))
    utc_iso, bj_iso, weekday_en = _parse_datetime(event.get("date", ""))
    
    impact_analysis = event.get("impact_analysis", "")
    impact_level = "Medium"
    if "Extremely High" in impact_analysis or "极高" in impact_analysis:
        impact_level = "Extremely High"
    elif "High" in impact_analysis or "高" in impact_analysis:
        impact_level = "High"
    elif "Low" in impact_analysis or "低" in impact_analysis:
        impact_level = "Low"

    # Extract estimate/previous from impact_analysis if present
    estimate = ""
    previous = ""
    unit = ""
    for part in impact_analysis.split(" | "):
        part = part.strip()
        if part.startswith("Estimate:"):
            estimate = part.split(":", 1)[1].strip()
        elif part.startswith("Previous:"):
            previous = part.split(":", 1)[1].strip()
        elif part.startswith("Unit:"):
            unit = part.split(":", 1)[1].strip()

    # Extract symbol from title if it looks like a ticker
    symbol = ""
    parts = event["title"].split()
    for p in parts:
        if p.isalpha() and len(p) <= 5 and p == p.upper():
            symbol = p
            break

    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = _get_connection(db_path)
    try:
        conn.execute("""
            INSERT OR IGNORE INTO events (
                event_hash, title, datetime_utc, datetime_bj, weekday_en,
                event_type, source, source_url, impact_level, impact_analysis,
                asset_impact, estimate, previous, unit, symbol, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            h, event["title"], utc_iso, bj_iso, weekday_en,
            event.get("type", ""), event.get("source", ""), event.get("source_url", ""),
            impact_level, impact_analysis, event.get("asset_impact", ""),
            estimate, previous, unit, symbol, fetched_at
        ))
        conn.commit()
        return conn.total_changes > 0
    finally:
        conn.close()

def insert_events(events: list[dict], db_path: str = DB_PATH) -> int:
    """批量插入，返回新插入数量"""
    count = 0
    for e in events:
        if insert_event(e, db_path):
            count += 1
    return count

def query_events(
    future_only: bool = True,
    past_days: int = 0,
    future_days: int = 365,
    event_type: Optional[str] = None,
    impact_level: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 1000,
    resolved: Optional[bool] = None,  # True=only resolved, False=only pending, None=all
    db_path: str = DB_PATH
) -> list[dict]:
    """查询事件，返回标准化格式"""
    conn = _get_connection(db_path)
    
    conditions = []
    params = []
    
    now_utc = datetime.now(timezone.utc)
    
    if future_only:
        conditions.append("datetime_utc >= ?")
        params.append(now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"))
    elif past_days > 0:
        past = (now_utc - timedelta(days=past_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        future = (now_utc + timedelta(days=future_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conditions.append("datetime_utc BETWEEN ? AND ?")
        params.extend([past, future])
    
    if resolved is True:
        conditions.append("actual_value IS NOT NULL")
    elif resolved is False:
        conditions.append("actual_value IS NULL")
    
    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)
    
    if impact_level:
        conditions.append("impact_level = ?")
        params.append(impact_level)
    
    if keyword:
        conditions.append("(title LIKE ? OR impact_analysis LIKE ? OR asset_impact LIKE ?)")
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw])
    
    where = " AND ".join(conditions) if conditions else "1=1"
    
    cursor = conn.execute(f"""
        SELECT id, title, datetime_utc, datetime_bj, weekday_en,
               event_type, source, source_url, impact_level, impact_analysis,
               asset_impact, estimate, previous, unit, symbol, fetched_at,
               actual_value, result_status, result_summary, news_notes, resolved_at
        FROM events
        WHERE {where}
        ORDER BY datetime_utc ASC
        LIMIT ?
    """, [*params, limit])
    
    rows = cursor.fetchall()
    result = []
    for r in rows:
        event = {
            "id": r["id"],
            "title": r["title"],
            "datetime_utc": r["datetime_utc"],
            "datetime_bj": r["datetime_bj"],
            "weekday_en": r["weekday_en"],
            "type": r["event_type"],
            "source": r["source"],
            "source_url": r["source_url"],
            "impact_level": r["impact_level"],
            "impact_analysis": r["impact_analysis"],
            "asset_impact": r["asset_impact"],
            "estimate": r["estimate"] if r["estimate"] else None,
            "previous": r["previous"] if r["previous"] else None,
            "unit": r["unit"] if r["unit"] else None,
            "symbol": r["symbol"] if r["symbol"] else None,
            "actual_value": r["actual_value"],
            "result_status": r["result_status"],
            "result_summary": r["result_summary"],
            "news_notes": r["news_notes"],
            "resolved_at": r["resolved_at"],
        }
        result.append(event)
    
    conn.close()
    return result

def get_stats(db_path: str = DB_PATH) -> dict:
    """获取统计信息"""
    conn = _get_connection(db_path)
    
    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    week_str = (now_utc + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    month_str = (now_utc + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    stats = {}
    
    # Total future events
    r = conn.execute("SELECT COUNT(*) as c FROM events WHERE datetime_utc >= ?", [now_str]).fetchone()
    stats["total_future"] = r["c"]
    
    r = conn.execute("SELECT COUNT(*) as c FROM events WHERE datetime_utc BETWEEN ? AND ?", [now_str, week_str]).fetchone()
    stats["next_7_days"] = r["c"]
    
    r = conn.execute("SELECT COUNT(*) as c FROM events WHERE datetime_utc BETWEEN ? AND ?", [now_str, month_str]).fetchone()
    stats["next_30_days"] = r["c"]
    
    r = conn.execute("SELECT COUNT(*) as c FROM events WHERE datetime_utc < ?", [now_str]).fetchone()
    stats["total_past"] = r["c"]
    
    r = conn.execute("SELECT COUNT(*) as c FROM events WHERE 1=1").fetchone()
    stats["total_all"] = r["c"]
    
    # By impact
    r = conn.execute("SELECT impact_level, COUNT(*) as c FROM events WHERE datetime_utc >= ? GROUP BY impact_level", [now_str]).fetchall()
    stats["by_impact_future"] = {row["impact_level"]: row["c"] for row in r}
    
    # By type
    r = conn.execute("SELECT event_type, COUNT(*) as c FROM events WHERE datetime_utc >= ? GROUP BY event_type", [now_str]).fetchall()
    stats["by_type_future"] = {row["event_type"]: row["c"] for row in r}
    
    # Date range
    r = conn.execute("SELECT MIN(datetime_utc) as first_event, MAX(datetime_utc) as last_event FROM events").fetchone()
    stats["date_range"] = {"first": r["first_event"], "last": r["last_event"]}
    
    # Resolution stats
    r = conn.execute("SELECT COUNT(*) as c FROM events WHERE actual_value IS NOT NULL").fetchone()
    stats["resolved_count"] = r["c"]
    
    r = conn.execute("SELECT COUNT(*) as c FROM events WHERE datetime_utc < ? AND actual_value IS NULL", [now_str]).fetchone()
    stats["pending_resolution"] = r["c"]
    
    conn.close()
    return stats

def import_from_json(json_path: str, db_path: str = DB_PATH) -> int:
    """从旧 JSON 文件导入历史数据"""
    if not os.path.exists(json_path):
        return 0
    
    with open(json_path) as f:
        events = json.load(f)
    
    return insert_events(events, db_path)

if __name__ == "__main__":
    load_env()
    init_db()
    print("[+] 数据库初始化完成:", DB_PATH)
    
    # Import existing data if any
    # We might not have json events anymore, but keeping for legacy
    from config import JSON_DATA_FILE
    imported = import_from_json(JSON_DATA_FILE)
    if imported:
        print(f"[+] 从 JSON 导入 {imported} 条事件")
    
    # Show stats
    stats = get_stats()
    print(f"[+] 统计:")
    for k, v in stats.items():
        print(f"    {k}: {v}")
