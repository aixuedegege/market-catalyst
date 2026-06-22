#!/usr/bin/env python3
"""
催化剂日历 - HTML生成器 (纯英文)
"""

import json
import hashlib
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import Counter

def get_impact_level(impact_text):
    t = impact_text.lower()
    if "extremely high" in t:
        return "critical"
    elif "high" in t:
        return "high"
    elif "medium" in t:
        return "medium"
    return "low"

TYPE_ICONS = {
    "Political - Trump Policy": "🇺🇸",
    "Macro - Economic Data": "📈",
    "Macro - Monetary Policy": "🏦",
    "US Equities - Earnings": "📊",
    "US Equities - IPO": "🚀",
    "Crypto - Token Unlocks": "🔓",
    "Crypto - News": "📰",
}

def generate_html(events, output_path="/data/ai/tmp/catalyst.html"):
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d")
    week_str = (now + timedelta(days=7)).strftime("%Y-%m-%d")
    month_str = (now + timedelta(days=30)).strftime("%Y-%m-%d")

    future = [e for e in events if e["date"] >= now_str]
    week_events = [e for e in future if e["date"] <= week_str]
    month_list = [e for e in future if e["date"] <= month_str]

    for e in future:
        e["impact_level"] = get_impact_level(e.get("impact_analysis", ""))

    by_type = {}
    for e in future:
        t = e["type"]
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(e)

    stats = {
        "total": len(future),
        "week": len(week_events),
        "month": len(month_list),
        "critical": len([e for e in future if e["impact_level"] == "critical"]),
        "high": len([e for e in future if e["impact_level"] == "high"]),
    }

    date_counter = Counter(e["date"][:10] for e in week_events)
    resonance_days = [(d, c) for d, c in date_counter.most_common() if c >= 2]

    html = build_page(stats, by_type, resonance_days, week_events, week_str, month_str, now)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    www_path = "/data/ai/www/catalyst/index.html"
    Path(www_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output_path, www_path)
    print(f"  -> HTML: {output_path} -> {www_path}")


def build_page(stats, by_type, resonance_days, week_events, week_str, month_str, now):
    # Generate dynamic calendar icon with current day
    day_num = now.day
    # Cute SVG definition
    CAL_SVG = f'<svg viewBox="0 0 32 32" width="48" height="48" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="6" width="28" height="24" rx="4" fill="#6366f1"/><rect x="2" y="6" width="28" height="8" fill="#4f46e5"/><circle cx="9" cy="10" r="1.5" fill="#f43f5e"/><circle cx="23" cy="10" r="1.5" fill="#f43f5e"/><text x="16" y="25" font-family="sans-serif" font-size="14" font-weight="bold" fill="white" text-anchor="middle">{day_num}</text></svg>'
    
    # Favicon Base64 version for Chrome
    FAV_SVG = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect x="2" y="6" width="28" height="24" rx="4" fill="#6366f1"/><rect x="2" y="6" width="28" height="8" fill="#4f46e5"/><circle cx="9" cy="10" r="1.5" fill="#f43f5e"/><circle cx="23" cy="10" r="1.5" fill="#f43f5e"/><text x="16" y="25" font-family="sans-serif" font-size="14" font-weight="bold" fill="white" text-anchor="middle">{day_num}</text></svg>'
    import base64
    FAV_B64 = base64.b64encode(FAV_SVG.encode()).decode()
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>market-catalyst</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,{FAV_B64}">
    <style>{CSS}</style>
</head>
<body>
    <div class="topbar">
        <span class="topbar-stats">
            <a href="https://github.com/aixuedegege/market-catalyst" target="_blank" class="topbar-link" title="View Source on GitHub">
                <svg style="width:14px;height:14px;fill:currentColor;vertical-align:middle" viewBox="0 0 16 16"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 1.2.27.36-.1.74-.15 1.13-.15.38 0 .76.05 1.13.15.53-.49 1.2-.27 1.2-.27.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg> GitHub
            </a>
            <span class="topbar-stat" title="Total page views">👁 <span id="visitCount">0</span></span>
            <span class="topbar-stat" title="API calls this hour">🔌 <span id="apiCount">0</span></span>
        </span>
        <button class="topbar-btn" onclick="toggleApiModal()">API</button>
    </div>

    <div class="header">
        <h1><a href="https://github.com/aixuedegege/market-catalyst" target="_blank" class="title-link">{CAL_SVG} market-catalyst</a></h1>
        <div class="subtitle">Macro · Crypto · Equities · Politics</div>
        <div class="update-time">Updated: {now.strftime('%Y-%m-%d %H:%M UTC')} | Sources: BLS/BEA/Fed/Tokenomist</div>
    </div>

    <div class="container">
        <div class="stats">
            <div class="stat-card active" onclick="filterEvents('all')" id="stat-all">
                <div class="number">{stats['total']}</div>
                <div class="label">Total Events</div>
            </div>
            <div class="stat-card" onclick="filterEvents('week')" id="stat-week">
                <div class="number">{stats['week']}</div>
                <div class="label">Next 7 Days</div>
            </div>
            <div class="stat-card" onclick="filterEvents('month')" id="stat-month">
                <div class="number">{stats['month']}</div>
                <div class="label">Next 30 Days</div>
            </div>
            <div class="stat-card critical" onclick="filterEvents('critical')" id="stat-critical">
                <div class="number">{stats['critical']}</div>
                <div class="label">🔴 Critical</div>
            </div>
            <div class="stat-card high" onclick="filterEvents('high')" id="stat-high">
                <div class="number">{stats['high']}</div>
                <div class="label">🟠 High</div>
            </div>
        </div>

        {build_resonance(resonance_days, week_events)}

        <div class="filters">
            <button class="filter-btn active" onclick="filterEvents('all')">All ({stats['total']})</button>
            {build_filter_buttons(by_type)}
        </div>

        {build_categories(by_type, week_str, month_str)}

        <div class="footer">
            <p>Catalyst Calendar v4.0 | Updates hourly | Data for reference only, not investment advice</p>
            <p style="margin-top: 8px;"><a href="/api/v1/events" style="color: #6366f1;">API Endpoint (JSON)</a></p>
        </div>
    </div>

    <!-- API Modal -->
    <div class="modal-overlay" id="apiModal" onclick="if(event.target===this)toggleApiModal()">
        <div class="modal">
            <div class="modal-header">
                <h3>🔌 Catalyst Calendar API</h3>
                <button class="modal-close" onclick="toggleApiModal()">&times;</button>
            </div>
            <p class="modal-desc">Free public endpoint. No registration required. Returns standard JSON.</p>

            <h4>Get All Events</h4>
            <div class="curl-example">
                <button class="copy-btn" onclick="copyCurl(this)">📋 Copy</button>
                <code><span class="cmd">curl</span> <span class="flag">-s</span> <span class="url">https://catalyst.infodream.asia/api/v1/events</span> | <span class="cmd">python3</span> -m json.tool</code>
            </div>

            <h4>Save to File</h4>
            <div class="curl-example">
                <button class="copy-btn" onclick="copyCurl(this)">📋 Copy</button>
                <code><span class="cmd">curl</span> <span class="flag">-s</span> <span class="url">https://catalyst.infodream.asia/api/v1/events</span> <span class="flag">-o</span> catalyst.json</code>
            </div>

            <h4>Health Check</h4>
            <div class="curl-example">
                <button class="copy-btn" onclick="copyCurl(this)">📋 Copy</button>
                <code><span class="cmd">curl</span> <span class="flag">-s</span> <span class="url">https://catalyst.infodream.asia/api/health</span></code>
            </div>

            <h4>Python Example</h4>
            <div class="curl-example">
                <button class="copy-btn" onclick="copyCurl(this)">📋 Copy</button>
                <code><span class="cmd">import</span> requests
resp = requests.get(<span class="url">"https://catalyst.infodream.asia/api/v1/events"</span>)
data = resp.json()
<span class="cmd">print</span>(data[<span class="url">"stats"</span>])
<span class="cmd">for</span> e <span class="cmd">in</span> data[<span class="url">"data"</span>]:
    <span class="cmd">print</span>(e[<span class="url">"title"</span>], e[<span class="url">"date"</span>])</code>
            </div>

            <h4>MCP Server Config</h4>
            <p style="color:var(--text-muted);font-size:0.85rem;margin-bottom:12px;">
                Add to Cursor (<code>.cursor/mcp.json</code>), Claude Desktop, or any MCP client.
                Uses FastMCP Streamable HTTP — connects directly to the live API.
            </p>
            <div class="curl-example">
                <button class="copy-btn" onclick="copyCurl(this)">📋 Copy</button>
                <code>&#123;
  &quot;mcpServers&quot;: &#123;
    &quot;market-catalyst&quot;: &#123;
      &quot;url&quot;: &quot;https://catalyst.infodream.asia/mcp&quot;
    &#125;
  &#125;
&#125;</code>
            </div>
            <p style="color:var(--text-secondary);font-size:0.8rem;margin-top:8px;">
                <strong>5 Tools:</strong>
                <code>get_catalyst_stats</code> (stats cards) ·
                <code>get_resonance_days</code> (overlapping events) ·
                <code>get_events_by_type</code> (category filter) ·
                <code>get_catalyst_events</code> (full list) ·
                <code>search_catalyst_events</code> (keyword search)
            </p>

            <div class="api-info">
                <ul>
                    <li><span class="tag">GET</span> <code>/api/v1/events</code> — All future catalyst events</li>
                    <li><span class="tag">GET</span> <code>/api/health</code> — Service health check</li>
                    <li><span class="tag">Rate Limit</span> Max 100 requests/hour per IP</li>
                    <li><span class="tag">Format</span> JSON with stats + data + meta</li>
                    <li><span class="tag">Refresh</span> Data updates automatically every hour</li>
                </ul>
            </div>
        </div>
    </div>

    <!-- Resonance Modal -->
    <div class="modal-overlay" id="resonanceModal" onclick="if(event.target===this)toggleResonanceModal()">
        <div class="modal resonance-modal">
            <div class="modal-header">
                <h3>📋 Events on <span id="resonanceDate"></span></h3>
                <button class="modal-close" onclick="toggleResonanceModal()">&times;</button>
            </div>
            <div id="resonanceEvents" class="resonance-event-list"></div>
        </div>
    </div>

    <script>{JAVASCRIPT}</script>
</body>
</html>"""


def build_resonance(resonance_days, week_events):
    if not resonance_days:
        return ""
    days_html = ""
    resonance_data = []
    for date_str, count in resonance_days:
        evts = [e for e in week_events if e["date"].startswith(date_str)]
        preview = " · ".join([e["title"][:40] for e in evts[:3]])
        resonance_data.append({"date": date_str, "count": count, "events": evts})
        days_html += f"""<div class="resonance-day" onclick="showResonanceModal('{date_str}')">
            <div class="date">{date_str}</div>
            <div class="count">{count} events overlapping</div>
            <div class="preview">{preview}</div>
            <div class="resonance-hint">Click for details &rarr;</div>
        </div>"""
    # Store resonance data for JS
    resonance_json = json.dumps(resonance_data, ensure_ascii=False).replace('</', '<\\/')
    return f"""<div class="resonance">
        <h2>⚠️ Next 7 Days — Resonance (Multiple Events Overlapping)</h2>
        <div class="resonance-grid">{days_html}</div>
    </div>
    <script>window.__resonanceData = {resonance_json};</script>"""


def build_filter_buttons(by_type):
    buttons = ""
    for t, items in by_type.items():
        icon = TYPE_ICONS.get(t, "📌")
        buttons += f'<button class="filter-btn" onclick="filterEvents(\'{t}\')">{icon} {t} ({len(items)})</button>'
    return buttons


def build_categories(by_type, week_str, month_str):
    html = ""
    for t, events in sorted(by_type.items()):
        icon = TYPE_ICONS.get(t, "📌")
        events_html = ""
        for e in sorted(events, key=lambda x: x["date"]):
            date_part = e["date"][:10]
            time_part = e["date"][11:16] if len(e["date"]) > 11 else ""
            level = e.get("impact_level", "low")
            events_html += f"""
            <div class="event {level}" data-type="{t}" data-date="{date_part}">
                <div class="event-date">
                    <div class="day">{date_part[8:10]}</div>
                    <div class="month">{date_part[5:7]}/{date_part[:4]}</div>
                    <div class="time">{time_part}</div>
                </div>
                <div class="event-content">
                    <h3>{e['title']}</h3>
                    <div class="impact">{e['impact_analysis'][:140]}{'...' if len(e['impact_analysis']) > 140 else ''}</div>
                    <span class="asset">{e['asset_impact']}</span>
                </div>
                <span class="impact-badge {level}">{level.upper()}</span>
            </div>"""

        html += f"""<div class="category" data-type="{t}">
            <div class="category-header" onclick="toggleCategory(this)">
                <h2>{icon} {t}</h2>
                <span class="count">{len(events)} events</span>
                <span class="collapse-icon">▼</span>
            </div>
            <div class="category-content">{events_html}</div>
        </div>"""
    return html


CSS = r"""
* { margin: 0; padding: 0; box-sizing: border-box; }
:root {
    --bg-primary: #0a0a0f; --bg-secondary: #12121a; --bg-card: #1a1a24;
    --bg-hover: #22222e; --text-primary: #e4e4e7; --text-secondary: #a1a1aa;
    --text-muted: #71717a; --border: #27272a;
    --critical: #ef4444; --critical-bg: rgba(239,68,68,0.1);
    --high: #f97316; --high-bg: rgba(249,115,22,0.1);
    --medium: #eab308; --medium-bg: rgba(234,179,8,0.1);
    --low: #22c55e; --low-bg: rgba(34,197,94,0.1);
    --accent: #6366f1; --accent-bg: rgba(99,102,241,0.1);
}
body { background: var(--bg-primary); color: var(--text-primary); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; }
.topbar { position: fixed; top: 0; left: 0; right: 0; display: flex; justify-content: flex-end; align-items: center; padding: 8px 16px; background: rgba(10,10,15,0.8); backdrop-filter: blur(12px); z-index: 100; border-bottom: 1px solid var(--border); }
.topbar-btn { background: var(--bg-card); border: 1px solid var(--border); color: var(--text-primary); padding: 6px 14px; border-radius: 8px; font-size: 0.875rem; cursor: pointer; transition: all 0.2s; font-weight: 500; }
.topbar-btn:hover { background: var(--accent-bg); border-color: var(--accent); color: #818cf8; }
.topbar-stats { display: flex; gap: 16px; align-items: center; margin-right: 12px; }
.topbar-stat { color: var(--text-secondary); font-size: 0.8rem; display: flex; align-items: center; gap: 4px; }
.topbar-stat span { font-weight: 600; color: var(--text-primary); }
.header { text-align: center; padding: 60px 20px 40px; border-bottom: 1px solid var(--border); }
.header h1 { font-size: 2.5rem; font-weight: 700; background: linear-gradient(90deg, #818cf8, #c084fc); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 8px; }
.header .title-link { text-decoration: none; color: inherit; display: inline-flex; align-items: center; gap: 12px; }
.header .title-link svg { fill: #818cf8; filter: drop-shadow(0 0 8px rgba(99, 102, 241, 0.4)); }
.header .subtitle { color: var(--text-secondary); font-size: 1rem; }
.header .update-time { color: var(--text-muted); font-size: 0.875rem; margin-top: 8px; }
.container { max-width: 1400px; margin: 0 auto; padding: 24px; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 32px; }
.stat-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; text-align: center; cursor: pointer; transition: all 0.2s; }
.stat-card:hover { transform: translateY(-2px); border-color: var(--accent); }
.stat-card.active { border-color: var(--accent); background: var(--accent-bg); }
.stat-card .number { font-size: 2rem; font-weight: 700; color: var(--accent); }
.stat-card .label { color: var(--text-secondary); font-size: 0.875rem; margin-top: 4px; }
.stat-card.critical .number { color: var(--critical); }
.stat-card.high .number { color: var(--high); }
.resonance { background: var(--critical-bg); border: 1px solid var(--critical); border-radius: 12px; padding: 20px; margin-bottom: 32px; }
.resonance h2 { color: var(--critical); font-size: 1.25rem; margin-bottom: 12px; }
.resonance-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 12px; }
.resonance-event-list { max-height: 60vh; overflow-y: auto; padding: 8px; }
.resonance-event-item { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 8px; transition: all 0.2s; }
.resonance-event-item:hover { border-color: var(--accent); }
.resonance-event-item h4 { font-size: 0.95rem; margin-bottom: 4px; color: var(--text-primary); }
.resonance-event-item .meta { font-size: 0.8rem; color: var(--text-muted); display: flex; gap: 12px; flex-wrap: wrap; }
.resonance-event-item .impact-short { font-size: 0.8rem; color: var(--text-secondary); margin-top: 4px; }
.resonance-day { background: var(--bg-card); border-radius: 8px; padding: 12px; cursor: pointer; transition: all 0.2s; position: relative; }
.resonance-day:hover { border-color: var(--critical); background: var(--bg-hover); transform: translateY(-2px); box-shadow: 0 4px 12px rgba(239,68,68,0.2); }
.resonance-day .date { font-weight: 600; color: var(--critical); }
.resonance-day .count { color: var(--text-secondary); font-size: 0.875rem; }
.resonance-day .preview { font-size: 0.75rem; color: var(--text-muted); margin-top: 4px; }
.resonance-hint { font-size: 0.65rem; color: var(--critical); margin-top: 6px; opacity: 0; transition: opacity 0.2s; }
.resonance-day:hover .resonance-hint { opacity: 1; }
.resonance-day .date { font-weight: 600; color: var(--critical); }
.resonance-day .count { color: var(--text-secondary); font-size: 0.875rem; }
.resonance-day .preview { font-size: 0.75rem; color: var(--text-muted); margin-top: 4px; }
.filters { display: flex; gap: 8px; margin-bottom: 24px; flex-wrap: wrap; }
.filter-btn { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 8px 16px; color: var(--text-primary); cursor: pointer; font-size: 0.875rem; transition: all 0.2s; }
.filter-btn:hover, .filter-btn.active { background: var(--accent-bg); border-color: var(--accent); color: #818cf8; }
.category { margin-bottom: 16px; }
.category-header { display: flex; align-items: center; gap: 12px; padding: 12px 16px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; cursor: pointer; transition: all 0.2s; user-select: none; }
.category-header:hover { background: var(--bg-hover); }
.category-header h2 { font-size: 1.25rem; font-weight: 600; }
.category-header .count { background: var(--bg-secondary); padding: 4px 12px; border-radius: 20px; font-size: 0.875rem; color: var(--text-secondary); }
.category-header .collapse-icon { margin-left: auto; color: var(--text-muted); transition: transform 0.2s; }
.category.collapsed .collapse-icon { transform: rotate(-90deg); }
.category.collapsed .category-content { display: none; }
.category-content { padding-top: 12px; }
.events { display: grid; gap: 12px; }
.event { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; display: grid; grid-template-columns: auto 1fr auto; gap: 16px; align-items: start; transition: all 0.2s; }
.event:hover { border-color: var(--accent); background: var(--bg-hover); }
.event.critical { border-left: 3px solid var(--critical); }
.event.high { border-left: 3px solid var(--high); }
.event.medium { border-left: 3px solid var(--medium); }
.event.low { border-left: 3px solid var(--low); }
.event-date { text-align: center; min-width: 70px; }
.event-date .day { font-size: 1.5rem; font-weight: 700; line-height: 1; }
.event-date .month { font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; }
.event-date .time { font-size: 0.875rem; color: var(--text-secondary); margin-top: 4px; }
.event-content h3 { font-size: 1rem; font-weight: 600; margin-bottom: 8px; }
.event-content .impact { color: var(--text-secondary); font-size: 0.875rem; margin-bottom: 8px; }
.event-content .asset { display: inline-block; background: var(--accent-bg); color: #818cf8; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; }
.impact-badge { padding: 6px 12px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; white-space: nowrap; }
.impact-badge.critical { background: var(--critical-bg); color: var(--critical); }
.impact-badge.high { background: var(--high-bg); color: var(--high); }
.impact-badge.medium { background: var(--medium-bg); color: var(--medium); }
.impact-badge.low { background: var(--low-bg); color: var(--low); }
@media (max-width: 768px) {
    .event { grid-template-columns: 1fr; }
    .event-date { text-align: left; display: flex; gap: 8px; align-items: center; }
    .stats { grid-template-columns: repeat(2, 1fr); }
    .header h1 { font-size: 1.75rem; }
    .header { padding-top: 70px; }
}
.footer { text-align: center; padding: 32px; color: var(--text-muted); font-size: 0.875rem; border-top: 1px solid var(--border); margin-top: 48px; }
.modal-overlay { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 1000; justify-content: center; align-items: center; backdrop-filter: blur(4px); }
.modal-overlay.show { display: flex; }
.modal { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 16px; padding: 24px; max-width: 700px; width: 90%; max-height: 80vh; overflow-y: auto; }
.modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.modal-header h3 { font-size: 1.25rem; color: #818cf8; }
.modal-close { background: none; border: none; color: var(--text-muted); font-size: 1.5rem; cursor: pointer; padding: 4px 8px; }
.modal-close:hover { color: var(--text-primary); }
.modal-desc { color: var(--text-secondary); margin-bottom: 16px; }
.modal h4 { margin: 16px 0 8px; color: #818cf8; font-size: 1rem; }
.curl-example { background: #0d0d14; border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin: 12px 0; font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; font-size: 0.875rem; overflow-x: auto; position: relative; }
.curl-example code { color: #a1a1aa; line-height: 1.8; display: block; white-space: pre; }
.curl-example .cmd { color: #22c55e; }
.curl-example .url { color: #60a5fa; }
.curl-example .flag { color: #f472b6; }
.copy-btn { position: absolute; top: 8px; right: 8px; background: var(--bg-card); border: 1px solid var(--border); color: var(--text-secondary); padding: 4px 12px; border-radius: 6px; font-size: 0.75rem; cursor: pointer; }
.copy-btn:hover { background: var(--accent-bg); color: #818cf8; }
.api-info { color: var(--text-secondary); font-size: 0.875rem; line-height: 1.8; margin-top: 16px; }
.api-info li { margin-bottom: 4px; }
.api-info .tag { display: inline-block; background: var(--accent-bg); color: #818cf8; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; margin-right: 4px; }
"""

JAVASCRIPT = r"""
function toggleApiModal() { document.getElementById('apiModal').classList.toggle('show'); }
function toggleResonanceModal() { document.getElementById('resonanceModal').classList.toggle('show'); }
function showResonanceModal(dateStr) {
    const data = window.__resonanceData?.find(d => d.date === dateStr);
    if (!data) return;
    document.getElementById('resonanceDate').textContent = dateStr;
    const container = document.getElementById('resonanceEvents');
    container.innerHTML = data.events.map(e => {
        const level = e.impact_level || 'low';
        const badgeClass = level === 'critical' ? 'critical' : level === 'high' ? 'high' : level === 'medium' ? 'medium' : 'low';
        return `<div class="resonance-event-item">
            <h4>${e.title}</h4>
            <div class="meta">
                <span>📅 ${e.date}</span>
                <span>📁 ${e.type}</span>
                <span>🎯 ${e.asset_impact}</span>
            </div>
            <div class="impact-short">${e.impact_analysis}</div>
            <span class="impact-badge ${badgeClass}" style="margin-top:8px;display:inline-block">${level.toUpperCase()}</span>
        </div>`;
    }).join('');
    toggleResonanceModal();
}
// Visit tracking
(function() {
    // Only track unique sessions (prevents F5 spam)
    if (!sessionStorage.getItem('catalyst_visited')) {
        // Bot check
        if (navigator.webdriver || navigator.languages === undefined) return;
        
        fetch('/api/track-visit')
            .then(r => r.json())
            .then(d => {
                document.getElementById('visitCount').textContent = d.visits?.toLocaleString() || '0';
                document.getElementById('apiCount').textContent = d.api_calls?.toLocaleString() || '0';
            })
            .catch(() => {
                fetch('/api/stats')
                    .then(r => r.json())
                    .then(d => {
                        document.getElementById('visitCount').textContent = d.visits?.toLocaleString() || '0';
                        document.getElementById('apiCount').textContent = d.api_calls?.toLocaleString() || '0';
                    })
                    .catch(() => {
                        document.getElementById('visitCount').textContent = '--';
                        document.getElementById('apiCount').textContent = '--';
                    });
            });
        sessionStorage.setItem('catalyst_visited', '1');
    } else {
        // Just display current stats without incrementing
        fetch('/api/stats')
            .then(r => r.json())
            .then(d => {
                document.getElementById('visitCount').textContent = d.visits?.toLocaleString() || '0';
                document.getElementById('apiCount').textContent = d.api_calls?.toLocaleString() || '0';
            }).catch(() => {});
    }
})();
function copyCurl(btn) {
    const codeEl = btn.nextElementSibling;
    const text = codeEl.textContent || codeEl.innerText;
    navigator.clipboard.writeText(text.trim()).then(() => {
        btn.textContent = '✅ Copied';
        setTimeout(() => { btn.textContent = '📋 Copy'; }, 2000);
    });
}
function toggleCategory(header) { header.closest('.category').classList.toggle('collapsed'); }
const weekDate = new Date(); weekDate.setDate(weekDate.getDate() + 7);
const weekStr = weekDate.toISOString().split('T')[0];
const monthDate = new Date(); monthDate.setMonth(monthDate.getMonth() + 1);
const monthStr = monthDate.toISOString().split('T')[0];
function filterEvents(type) {
    document.querySelectorAll('.stat-card').forEach(card => card.classList.remove('active'));
    const el = document.getElementById('stat-' + type);
    if (el) el.classList.add('active');
    document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.filter-btn').forEach(btn => {
        const t = btn.textContent;
        if (type === 'all' && t.startsWith('All')) btn.classList.add('active');
        else if (type !== 'all' && type !== 'week' && type !== 'month' && type !== 'critical' && type !== 'high') {
            if (t.includes(type)) btn.classList.add('active');
        }
    });
    document.querySelectorAll('.event').forEach(event => {
        const level = event.classList.contains('critical') ? 'critical' : event.classList.contains('high') ? 'high' : event.classList.contains('medium') ? 'medium' : 'low';
        const dateStr = event.getAttribute('data-date');
        let show = false;
        if (type === 'all') show = true;
        else if (type === 'critical') show = level === 'critical';
        else if (type === 'high') show = level === 'critical' || level === 'high';
        else if (type === 'week') show = dateStr <= weekStr;
        else if (type === 'month') show = dateStr <= monthStr;
        else show = event.closest('.category')?.dataset.type === type;
        event.style.display = show ? 'grid' : 'none';
    });
    document.querySelectorAll('.category').forEach(cat => {
        let hasVisible = false;
        cat.querySelectorAll('.event').forEach(ev => { if (ev.style.display !== 'none') hasVisible = true; });
        cat.style.display = hasVisible ? 'block' : 'none';
    });
}
"""


def main():
    json_file = "/data/ai/tmp/catalyst_events.json"
    html_file = "/data/ai/tmp/catalyst.html"
    if not os.path.exists(json_file):
        print("[ERROR] Data file not found")
        return
    with open(json_file) as f:
        events = json.load(f)
    print(f"Loading {len(events)} events, generating HTML...")
    generate_html(events, html_file)
    print(f"✅ Done: {html_file}")


if __name__ == "__main__":
    main()
