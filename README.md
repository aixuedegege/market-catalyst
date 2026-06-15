# 📅 Market Catalyst Calendar

> **Automated macro & equity catalyst calendar with event resonance alerts, public API, and real-time updates.**

A lightweight, forward-looking market intelligence dashboard designed for traders and quantitative analysts. It aggregates high-impact macroeconomic data, US equity earnings, and IPOs into an interactive, dark-themed UI.

## ✨ Key Features

- **Event Resonance Alerts**: Automatically detects and highlights days with multiple overlapping high-impact events.
- **Real-time & Auto-updates**: Data refreshes every hour via Finnhub API.
- **Interactive UI**: Dark theme, filtering by impact/type, and click-to-detail modals.
- **Public API**: Rate-limited JSON endpoint for programmatic access.
- **MCP Integration**: Ready-to-use MCP server config for AI assistants.
- **Analytics**: Built-in visit tracking and API usage statistics.

## 🚀 Quick Start

### 1. Data Collection
```bash
python3 catalyst_collector.py
```

### 2. Frontend Generation
```bash
python3 catalyst_html.py
```
*Output is served via Caddy at `catalyst.infodream.asia`.*

### 3. API Server
```bash
python3 catalyst_api.py
```
*Runs on port 17002. Rate limit: 5 req/hour per IP.*

## 📦 Data Sources
- **Macro**: Economic Calendar (FOMC, CPI, NFP, etc.) via Finnhub.
- **Equities**: Earnings Calendar (COIN, MSTR, NVDA, etc.) via Finnhub.
- **IPO**: Upcoming IPOs via Finnhub.

## 🔌 API Endpoints

| Endpoint | Description |
| :--- | :--- |
| `GET /api/v1/events` | All future catalyst events (JSON) |
| `GET /api/health` | Service health check |
| `GET /api/stats` | Global traffic & usage stats |

## 🤖 MCP Config
Add this to your MCP client configuration to access the calendar data:
```json
{
  "mcpServers": {
    "catalyst-calendar": {
      "command": "curl",
      "args": ["-s", "https://catalyst.infodream.asia/api/v1/events"]
    }
  }
}
```

## 📂 Project Structure
- `catalyst_collector.py`: Data fetching, filtering, and deduplication logic.
- `catalyst_html.py`: Static HTML/CSS/JS generation engine.
- `catalyst_api.py`: Python HTTP server for API, stats, and rate limiting.

## 📄 License
Open Source.
