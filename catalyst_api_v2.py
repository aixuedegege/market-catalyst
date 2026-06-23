#!/usr/bin/env python3
"""
催化剂日历 API v2 — SQLite 后端
新增: weekday_en, datetime_bj, datetime_utc (精确到秒)
查询参数: ?type=...&impact=...&keyword=...&days=...&past_days=...&limit=...
"""

import json
import os
import time
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import threading
from urllib.parse import urlparse, parse_qs

# Add db module path
sys.path.insert(0, "/data/ai/tmp")
from catalyst_db import init_db, query_events, get_stats, DB_PATH

STATS_FILE = "/data/ai/www/catalyst/stats.json"

class StatsTracker:
    """Track visits and API calls"""
    def __init__(self):
        self.lock = threading.Lock()
        self.stats = {"visits": 0, "api_calls": 0, "last_updated": ""}
        self._load()
    
    def _load(self):
        try:
            if os.path.exists(STATS_FILE):
                with open(STATS_FILE) as f:
                    self.stats = json.load(f)
        except:
            pass
    
    def _save(self):
        self.stats["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            with open(STATS_FILE, "w") as f:
                json.dump(self.stats, f)
        except:
            pass
    
    def increment_visit(self):
        with self.lock:
            self.stats["visits"] += 1
            self._save()
            return self.stats["visits"]
    
    def increment_api_call(self):
        with self.lock:
            self.stats["api_calls"] += 1
            self._save()
            return self.stats["api_calls"]
    
    def get_stats(self):
        with self.lock:
            return dict(self.stats)

stats_tracker = StatsTracker()

class RateLimiter:
    """简单的基于 IP 的速率限制器"""
    def __init__(self, max_requests=100, window_seconds=3600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)
        self.lock = threading.Lock()
    
    def is_allowed(self, client_ip):
        now = time.time()
        with self.lock:
            self.requests[client_ip] = [
                t for t in self.requests[client_ip] 
                if now - t < self.window_seconds
            ]
            if len(self.requests[client_ip]) >= self.max_requests:
                oldest = self.requests[client_ip][0]
                wait = int(self.window_seconds - (now - oldest))
                return False, wait
            self.requests[client_ip].append(now)
            return True, 0
    
    def get_remaining(self, client_ip):
        now = time.time()
        with self.lock:
            recent = [t for t in self.requests[client_ip] if now - t < self.window_seconds]
            return max(0, self.max_requests - len(recent))

rate_limiter = RateLimiter(max_requests=100, window_seconds=3600)

class VisitDeduplicator:
    """Prevent visit spam: only count 1 visit per IP per 30 mins"""
    def __init__(self, window_minutes=30):
        self.window = window_minutes * 60
        self.last_visits = {}
        self.lock = threading.Lock()
        self.bot_keywords = ['bot', 'spider', 'crawler', 'curl', 'wget', 'python-requests', 'go-http-client']
    
    def should_count(self, client_ip, user_agent):
        ua_lower = (user_agent or '').lower()
        if any(kw in ua_lower for kw in self.bot_keywords):
            return False
        now = time.time()
        with self.lock:
            last = self.last_visits.get(client_ip, 0)
            if now - last > self.window:
                self.last_visits[client_ip] = now
                return True
            return False

visit_dedup = VisitDeduplicator()

class CatalystAPIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        client_ip = self.client_address[0]
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)
        
        if path.startswith("/api/v1/events/"):
            # Single event result lookup: /api/v1/events/{id}/result
            parts = path.split("/")
            # parts: ['', 'api', 'v1', 'events', '{id}', 'result']
            if len(parts) == 6 and parts[5] == "result":
                try:
                    event_id = int(parts[4])
                    self.handle_event_result(client_ip, event_id)
                except ValueError:
                    self.send_json({"error": "Invalid event ID"}, 400)
                stats_tracker.increment_api_call()
                return
            self.send_json({"error": "Not Found"}, 404)
        elif path == "/api/v1/events":
            allowed, wait = rate_limiter.is_allowed(client_ip)
            if not allowed:
                self.send_json({
                    "error": "速率限制：每小时最多 100 次请求",
                    "retry_after_seconds": wait,
                    "rate_limit": "100 requests/hour per IP"
                }, 429)
                return
            self.handle_events_v2(client_ip, params)
            stats_tracker.increment_api_call()
        elif path == "/api/health":
            self.handle_health()
        elif path == "/api/stats":
            self.handle_stats()
        elif path == "/api/track-visit":
            self.handle_track_visit()
        elif path == "/api/track-api-call":
            self.handle_track_api_call()
        else:
            self.send_json({"error": "Not Found", "endpoints": ["/api/v1/events", "/api/health", "/api/stats", "/api/track-visit"]}, 404)

    def handle_events_v2(self, client_ip, params):
        """新 API: 从 SQLite 查询，返回 weekday + 精确时间 + 结果字段"""
        # Parse query params
        status_filter = params.get("status", ["all"])[0].lower()  # future/resolved/pending/all
        future_only = params.get("future_only", [None])[0]
        days = int(params.get("days", ["90"])[0])
        past_days = int(params.get("past_days", ["0"])[0])
        event_type = params.get("type", [None])[0]
        impact_level = params.get("impact", [None])[0]
        keyword = params.get("keyword", [None])[0]
        limit = int(params.get("limit", ["1000"])[0])
        include_resolved = params.get("include_resolved", ["false"])[0].lower() == "true"
        
        # Determine query mode based on status filter
        if status_filter == "future":
            future_only_param = True
            resolved_filter = None  # Only future events
        elif status_filter == "resolved":
            future_only_param = False
            resolved_filter = True  # Only resolved (actual_value IS NOT NULL)
        elif status_filter == "pending":
            future_only_param = False
            resolved_filter = False  # Only pending (actual_value IS NULL)
        else:  # all
            future_only_param = future_only.lower() != "false" if future_only else True
            resolved_filter = None
        
        events = query_events(
            future_only=future_only_param,
            past_days=past_days,
            future_days=days,
            event_type=event_type,
            impact_level=impact_level,
            keyword=keyword,
            limit=limit,
            resolved=resolved_filter,
        )
        
        now_utc = datetime.now(timezone.utc)
        today_str = now_utc.strftime("%Y-%m-%d")
        week_cutoff = (now_utc + timedelta(days=7)).strftime("%Y-%m-%d")
        month_cutoff = (now_utc + timedelta(days=30)).strftime("%Y-%m-%d")
        
        def classify_impact(impact_str):
            if "极高" in impact_str or "Extremely High" in impact_str:
                return "critical"
            if "High" in impact_str or "高" in impact_str:
                return "high"
            return "other"
        
        # Stats from returned events
        future_events = [e for e in events if e.get("datetime_utc", "")[:10] >= today_str]
        
        stats = {
            "total": len(future_events),
            "week": len([e for e in future_events if e.get("datetime_utc", "")[:10] <= week_cutoff]),
            "month": len([e for e in future_events if e.get("datetime_utc", "")[:10] <= month_cutoff]),
            "critical": len([e for e in future_events if classify_impact(e.get("impact_analysis", "")) == "critical"]),
            "high": len([e for e in future_events if classify_impact(e.get("impact_analysis", "")) == "high"]),
        }
        
        # Resonance: days with 3+ high/critical events
        date_high = defaultdict(int)
        for e in future_events:
            if classify_impact(e.get("impact_analysis", "")) in ("critical", "high"):
                date_high[e.get("datetime_utc", "")[:10]] += 1
        resonance_days = [{"date": d, "count": c} for d, c in sorted(date_high.items()) if c >= 3]
        
        # DB stats
        db_stats = get_stats()
        
        response = {
            "code": 0,
            "message": "success",
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stats": stats,
            "db_stats": db_stats,
            "resonance": resonance_days,
            "data": events,
            "meta": {
                "source": "Finnhub (BLS/BEA/Fed)",
                "storage": "SQLite + JSON",
                "update_frequency": "every hour",
                "rate_limit": "100 requests/hour per IP",
                "your_remaining": rate_limiter.get_remaining(client_ip),
                "query_params": {
                    "status": status_filter,
                    "future_only": future_only_param,
                    "days": days,
                    "past_days": past_days,
                    "type": event_type,
                    "impact": impact_level,
                    "keyword": keyword,
                    "limit": limit,
                    "include_resolved": include_resolved,
                }
            }
        }
        
        self.send_json(response)

    def handle_event_result(self, client_ip, event_id):
        """查询单个事件的完整结果详情"""
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        
        event = conn.execute("SELECT * FROM events WHERE id = ?", [event_id]).fetchone()
        conn.close()
        
        if not event:
            self.send_json({"error": "Event not found", "id": event_id}, 404)
            return
        
        event_dict = dict(event)
        
        response = {
            "code": 0,
            "message": "success",
            "data": {
                "id": event_dict["id"],
                "title": event_dict["title"],
                "datetime_utc": event_dict["datetime_utc"],
                "datetime_bj": event_dict["datetime_bj"],
                "weekday_en": event_dict["weekday_en"],
                "event_type": event_dict["event_type"],
                "impact_analysis": event_dict["impact_analysis"],
                "asset_impact": event_dict["asset_impact"],
                "estimate": event_dict["estimate"],
                "previous": event_dict["previous"],
                "unit": event_dict["unit"],
                "result": {
                    "actual_value": event_dict["actual_value"],
                    "result_status": event_dict["result_status"],
                    "result_summary": event_dict["result_summary"],
                    "news_notes": event_dict["news_notes"],
                    "resolved_at": event_dict["resolved_at"],
                    "resolution_source": event_dict["resolution_source"],
                    "is_resolved": event_dict["actual_value"] is not None,
                }
            }
        }
        
        self.send_json(response)

    def handle_health(self):
        self.send_json({
            "status": "ok",
            "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "rate_limit": "100 requests/hour per IP",
            "storage": "SQLite",
            "db_path": DB_PATH
        })
    
    def handle_stats(self):
        web_stats = stats_tracker.get_stats()
        db_stats = get_stats()
        self.send_json({"web": web_stats, "database": db_stats})
    
    def handle_track_visit(self):
        client_ip = self.client_address[0]
        user_agent = self.headers.get('User-Agent', '')
        if visit_dedup.should_count(client_ip, user_agent):
            visits = stats_tracker.increment_visit()
            print(f"[Visit] New unique visit from {client_ip} (Total: {visits})")
        else:
            visits = stats_tracker.get_stats()["visits"]
            print(f"[Visit] Ignored repeat/bot visit from {client_ip}")
        self.send_json({"visits": visits, "api_calls": stats_tracker.get_stats()["api_calls"]})
    
    def handle_track_api_call(self):
        api_calls = stats_tracker.increment_api_call()
        self.send_json({"api_calls": api_calls, "visits": stats_tracker.get_stats()["visits"]})

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET")
        self.send_header("X-RateLimit-Limit", "100")
        self.send_header("X-RateLimit-Window", "3600")
        self.send_header("X-RateLimit-Remaining", str(rate_limiter.get_remaining(self.client_address[0])))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[API] {self.client_address[0]} {args[0]}")

if __name__ == "__main__":
    # Init database on startup
    init_db()
    
    # Import existing JSON data if DB is empty
    db_stats = get_stats()
    if db_stats.get("total_all", 0) == 0:
        from catalyst_db import import_from_json
        imported = import_from_json("/data/ai/tmp/catalyst_events.json")
        print(f"[*] Imported {imported} events from JSON")
    
    server = HTTPServer(("127.0.0.1", 17002), CatalystAPIHandler)
    print("[*] Catalyst API v2 running on http://127.0.0.1:17002")
    print("[*] Storage: SQLite + JSON fallback")
    print("[*] New fields: datetime_utc, datetime_bj, weekday_en")
    print("[*] Rate limit: 100 requests/hour per IP")
    server.serve_forever()
