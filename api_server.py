#!/usr/bin/env python3
"""
催化剂日历 API 服务 (SQLite Enhanced)
提供 JSON 格式的催化剂事件数据，支持历史记录、结果回填、精确时间查询。
IP 速率限制：每小时最多 100 次请求
"""

import json
import os
import time
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import threading

# Add tmp path for db module if running from workspace
sys.path.insert(0, "/data/ai/tmp")
try:
    from catalyst_db import get_stats as get_db_stats, query_events, init_db, DB_PATH
    HAS_DB = True
except ImportError:
    HAS_DB = False
    print("[WARN] SQLite backend not found. Falling back to JSON mode.")
    DATA_FILE = "/data/ai/tmp/catalyst_events.json"

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
        path = self.path.split("?")[0]
        params = {}
        if "?" in self.path:
            for p in self.path.split("?")[1].split("&"):
                if "=" in p:
                    k, v = p.split("=", 1)
                    params[k] = v

        if path == "/api/v1/events" or path == "/api/v1/events/":
            allowed, wait = rate_limiter.is_allowed(client_ip)
            if not allowed:
                self.send_json({
                    "error": "Rate limit exceeded",
                    "retry_after_seconds": wait,
                    "rate_limit": "100 requests/hour per IP"
                }, 429)
                return
            self.handle_events(client_ip, params)
            stats_tracker.increment_api_call()
        elif path.startswith("/api/v1/events/"):
            # Single event result lookup: /api/v1/events/{id}/result
            parts = path.split("/")
            # parts: ['', 'api', 'v1', 'events', '{id}', 'result'] -> length 6
            if len(parts) == 6 and parts[5] == "result":
                try:
                    event_id = int(parts[4])
                    self.handle_event_result(client_ip, event_id)
                except ValueError:
                    self.send_json({"error": "Invalid event ID"}, 400)
                stats_tracker.increment_api_call()
            else:
                self.send_json({"error": "Not Found"}, 404)
        elif path == "/api/health" or path == "/api/health/":
            self.handle_health()
        elif path == "/api/stats" or path == "/api/stats/":
            self.handle_stats()
        elif path == "/api/track-visit" or path == "/api/track-visit/":
            self.handle_track_visit()
        elif path == "/api/track-api-call" or path == "/api/track-api-call/":
            self.handle_track_api_call()
        else:
            self.send_json({"error": "Not Found", "endpoints": ["/api/v1/events", "/api/health", "/api/stats", "/api/track-visit"]}, 404)

    def handle_events(self, client_ip, params):
        if HAS_DB:
            self.handle_events_v2(client_ip, params)
        else:
            self.handle_events_legacy(client_ip, params)

    def handle_events_v2(self, client_ip, params):
        """SQLite-based event handling"""
        status_filter = params.get("status", "future").lower()
        days = int(params.get("days", "30"))
        event_type = params.get("type", None)
        impact_level = params.get("impact", None)
        keyword = params.get("keyword", None)
        limit = int(params.get("limit", "100"))
        
        if status_filter == "resolved":
            future_only = False
            resolved = True
        elif status_filter == "pending":
            future_only = False
            resolved = False
        else:
            future_only = True
            resolved = None
            
        events = query_events(
            future_only=future_only, future_days=days, 
            event_type=event_type, impact_level=impact_level, 
            keyword=keyword, resolved=resolved, limit=limit
        )
        
        now_utc = datetime.now(timezone.utc)
        week_cutoff = (now_utc + timedelta(days=7)).strftime("%Y-%m-%d")
        month_cutoff = (now_utc + timedelta(days=30)).strftime("%Y-%m-%d")
        
        def classify_impact(impact_str):
            if "极高" in impact_str or "Extremely High" in impact_str:
                return "critical"
            if "High" in impact_str or "高" in impact_str:
                return "high"
            return "other"
            
        future_stats = [e for e in events if e.get("datetime_utc", "")[:10] >= now_utc.strftime("%Y-%m-%d")]
        stats = {
            "total": len(future_stats),
            "week": len([e for e in future_stats if e.get("datetime_utc", "")[:10] <= week_cutoff]),
            "month": len([e for e in future_stats if e.get("datetime_utc", "")[:10] <= month_cutoff]),
            "critical": len([e for e in future_stats if classify_impact(e.get("impact_analysis", "")) == "critical"]),
            "high": len([e for e in future_stats if classify_impact(e.get("impact_analysis", "")) == "high"]),
        }
        
        date_high = defaultdict(int)
        for e in future_stats:
            if classify_impact(e.get("impact_analysis", "")) in ("critical", "high"):
                date_high[e.get("datetime_utc", "")[:10]] += 1
        resonance = [{"date": d, "count": c} for d, c in sorted(date_high.items()) if c >= 3]
        
        response = {
            "code": 0, "message": "success",
            "updated_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stats": stats, "resonance": resonance,
            "data": events,
            "db_stats": get_db_stats(),
            "meta": {
                "source": "SQLite (BLS/BEA/Fed)",
                "query_params": {"status": status_filter, "days": days, "type": event_type},
                "rate_limit": "100 requests/hour per IP",
                "your_remaining": rate_limiter.get_remaining(client_ip)
            }
        }
        self.send_json(response)

    def handle_events_legacy(self, client_ip, params):
        """Legacy JSON-based event handling"""
        if not os.path.exists(DATA_FILE):
            self.send_json({"error": "Data not ready"}, 503)
            return
        try:
            with open(DATA_FILE) as f:
                events = json.load(f)
        except Exception:
            self.send_json({"error": "Data read failed"}, 500)
            return
            
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        week_cutoff = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
        month_cutoff = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
        
        future = [e for e in events if e.get("date", "")[:10] >= now]
        future.sort(key=lambda x: x.get("date", ""))
        
        def classify_impact(impact_str):
            if "极高" in impact_str or "Extremely High" in impact_str:
                return "critical"
            if "High" in impact_str or "高" in impact_str:
                return "high"
            return "other"
            
        stats = {
            "total": len(future),
            "week": len([e for e in future if e.get("date", "")[:10] <= week_cutoff]),
            "month": len([e for e in future if e.get("date", "")[:10] <= month_cutoff]),
            "critical": len([e for e in future if classify_impact(e.get("impact_analysis", "")) == "critical"]),
            "high": len([e for e in future if classify_impact(e.get("impact_analysis", "")) == "high"]),
        }
        
        response = {
            "code": 0, "message": "success",
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stats": stats, "data": future,
            "meta": {
                "source": "Finnhub (BLS/BEA/Fed)",
                "update_frequency": "every hour",
                "rate_limit": "100 requests/hour per IP",
                "your_remaining": rate_limiter.get_remaining(client_ip)
            }
        }
        self.send_json(response)

    def handle_event_result(self, client_ip, event_id):
        """Get result for a single event"""
        if not HAS_DB:
            self.send_json({"error": "Results require SQLite backend"}, 400)
            return
            
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM events WHERE id = ?", [event_id]).fetchone()
        conn.close()
        
        if not row:
            self.send_json({"error": "Event not found", "id": event_id}, 404)
            return
            
        e = dict(row)
        self.send_json({
            "code": 0, "message": "success",
            "data": {
                "id": e["id"], "title": e["title"],
                "datetime_utc": e["datetime_utc"], "weekday_en": e["weekday_en"],
                "impact_analysis": e["impact_analysis"], "estimate": e["estimate"],
                "previous": e["previous"], "unit": e["unit"],
                "result": {
                    "actual_value": e["actual_value"],
                    "result_status": e["result_status"],
                    "result_summary": e["result_summary"],
                    "news_notes": e["news_notes"],
                    "resolved_at": e["resolved_at"],
                    "resolution_source": e["resolution_source"],
                    "is_resolved": e["actual_value"] is not None
                }
            }
        })

    def handle_health(self):
        self.send_json({
            "status": "ok",
            "backend": "SQLite" if HAS_DB else "JSON",
            "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "rate_limit": "100 requests/hour per IP"
        })
    
    def handle_stats(self):
        web_stats = stats_tracker.get_stats()
        db_stats = get_db_stats() if HAS_DB else {}
        self.send_json({"web": web_stats, "database": db_stats})
    
    def handle_track_visit(self):
        client_ip = self.client_address[0]
        user_agent = self.headers.get('User-Agent', '')
        if visit_dedup.should_count(client_ip, user_agent):
            visits = stats_tracker.increment_visit()
        else:
            visits = stats_tracker.get_stats()["visits"]
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
        self.send_header("X-RateLimit-Remaining", str(rate_limiter.get_remaining(self.client_address[0])))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[API] {self.client_address[0]} {args[0]}")

if __name__ == "__main__":
    if HAS_DB:
        init_db()
        print("[*] Catalyst API (SQLite) running on http://127.0.0.1:17002")
    else:
        print("[*] Catalyst API (JSON) running on http://127.0.0.1:17002")
    server = HTTPServer(("127.0.0.1", 17002), CatalystAPIHandler)
    server.serve_forever()
