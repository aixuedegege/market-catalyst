# market-catalyst

Forward-looking macroeconomic catalyst calendar for US equities & crypto markets.

## Features

- **Automated Data Collection**: Fetches macro events from Finnhub API (BLS, BEA, Fed, etc.)
- **Impact Analysis**: Auto-classifies events by impact level (Critical / High / Medium / Low)
- **Asset Impact Mapping**: Shows affected assets (BTC, ETH, US Equities, USD)
- **Resonance Detection**: Highlights days with multiple overlapping high-impact events
- **Static HTML Dashboard**: Dark-themed, responsive UI with filtering & resonance modals
- **Rate-Limited API**: 5 requests/hour per IP with deduplication
- **MCP Server**: Proper stdio JSON-RPC server for Cursor / Claude Desktop integration

## Architecture

```
catalyst_collector.py  →  Fetches & filters events from Finnhub API
        ↓
catalyst_events.json   →  Raw event data (updated hourly via cron)
        ↓
html_generator.py      →  Generates static index.html with embedded CSS/JS
        ↓
index.html             →  Served via Caddy static file server (HTTPS)
        ↓
api_server.py          →  Optional HTTP API with rate limiting
mcp_server.py          →  MCP stdio JSON-RPC server for AI IDE integration
```

## Quick Start

### 1. Collect Data
```bash
python3 collector.py
```

### 2. Generate Dashboard
```bash
python3 html_generator.py
```

### 3. Serve via Caddy
```
catalyst.infodream.asia {
    root * /data/ai/www/catalyst
    file_server
    encode gzip
}
```

### 4. MCP Server (Cursor / Claude Desktop)
Add to your MCP config:
```json
{
  "mcpServers": {
    "catalyst-calendar": {
      "command": "python3",
      "args": ["mcp_server.py"]
    }
  }
}
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `get_catalyst_events` | Fetch upcoming events (filter by days & impact level) |
| `search_catalyst_events` | Search events by keyword (CPI, FOMC, NFP, etc.) |

## Cron Setup

```cron
# Collect catalyst data every hour
0 * * * * cd /data/ai/tmp && python3 collector.py >> logs/catalyst.log 2>&1

# Generate static HTML after collection
5 * * * * cd /data/ai/tmp && python3 html_generator.py >> logs/html.log 2>&1
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `/api/v1/events` | All future catalyst events (JSON) |
| `/api/health` | Health check |
| `/api/stats` | Visit & API call statistics |
| `/api/track-visit` | Track unique page visit |

## License

MIT
