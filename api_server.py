#!/usr/bin/env python3
"""
催化剂日历 API 服务
提供 JSON 格式的催化剂事件数据
IP 速率限制：每小时最多 5 次请求
"""

import json
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import threading

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
    def __init__(self, max_requests=5, window_seconds=3600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)
        self.lock = threading.Lock()
    
    def is_allowed(self, client_ip):
        now = time.time()
        with self.lock:
            # 清理过期记录
            self.requests[client_ip] = [
                t for t in self.requests[client_ip] 
                if now - t < self.window_seconds
            ]
            if len(self.requests[client_ip]) >= self.max_requests:
                # 返回剩余等待时间
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

rate_limiter = RateLimiter(max_requests=5, window_seconds=3600)

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
            return False  # Skip bots
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
        
        if self.path == "/api/v1/events" or self.path == "/api/v1/events/":
            allowed, wait = rate_limiter.is_allowed(client_ip)
            if not allowed:
                self.send_json({
                    "error": "速率限制：每小时最多 5 次请求",
                    "retry_after_seconds": wait,
                    "rate_limit": "5 requests/hour per IP"
                }, 429)
                return
            self.handle_events(client_ip)
            stats_tracker.increment_api_call()
        elif self.path == "/api/health" or self.path == "/api/health/":
            self.handle_health()
        elif self.path == "/api/stats" or self.path == "/api/stats/":
            self.handle_stats()
        elif self.path == "/api/track-visit" or self.path == "/api/track-visit/":
            self.handle_track_visit()
        elif self.path == "/api/track-api-call" or self.path == "/api/track-api-call/":
            self.handle_track_api_call()
        else:
            self.send_json({"error": "Not Found", "endpoints": ["/api/v1/events", "/api/health", "/api/stats", "/api/track-visit"]}, 404)

    def handle_events(self, client_ip):
        if not os.path.exists(DATA_FILE):
            self.send_json({"error": "数据未就绪，请稍后重试"}, 503)
            return

        try:
            with open(DATA_FILE) as f:
                events = json.load(f)
        except Exception as e:
            self.send_json({"error": f"数据读取失败: {str(e)}"}, 500)
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

        # Resonance: days with 3+ high/critical events
        from collections import defaultdict
        date_high = defaultdict(int)
        for e in future:
            if classify_impact(e.get("impact_analysis", "")) in ("critical", "high"):
                date_high[e.get("date", "")[:10]] += 1
        resonance_days = [{"date": d, "count": c} for d, c in sorted(date_high.items()) if c >= 3]

        response = {
            "code": 0,
            "message": "success",
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stats": stats,
            "resonance": resonance_days,
            "data": future,
            "meta": {
                "source": "Finnhub (BLS/BEA/Fed)",
                "update_frequency": "every hour",
                "rate_limit": "5 requests/hour per IP",
                "your_remaining": rate_limiter.get_remaining(client_ip)
            }
        }

        self.send_json(response)

    def handle_health(self):
        self.send_json({
            "status": "ok",
            "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "rate_limit": "5 requests/hour per IP"
        })
    
    def handle_stats(self):
        self.send_json(stats_tracker.get_stats())
    
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
        self.send_header("X-RateLimit-Limit", "5")
        self.send_header("X-RateLimit-Window", "3600")
        self.send_header("X-RateLimit-Remaining", str(rate_limiter.get_remaining(self.client_address[0])))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[API] {self.client_address[0]} {args[0]}")

if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 17002), CatalystAPIHandler)
    print("[*] Catalyst API running on http://127.0.0.1:17002")
    print("[*] Rate limit: 5 requests/hour per IP")
    server.serve_forever()
