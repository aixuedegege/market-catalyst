#!/usr/bin/env python3
"""
Catalyst Calendar Data Collector v4
All data from REAL APIs — zero mock data.
Sources: Finnhub API (economic calendar + earnings)
"""

import json
import hashlib
import os
import time
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import Counter

FINNHUB_API_KEY = "d8jofn9r01qh6g3rijv0d8jofn9r01qh6g3rijvg"
DEDUP_FILE = "/tmp/catalyst_dedup.json"

def load_dedup_set():
    if os.path.exists(DEDUP_FILE):
        with open(DEDUP_FILE) as f:
            return set(json.load(f))
    return set()

def save_dedup_set(s):
    with open(DEDUP_FILE, "w") as f:
        json.dump(list(s), f, indent=2)

def event_hash(title, date_str, source):
    return hashlib.md5(f"{title}|{date_str}|{source}".encode()).hexdigest()[:12]

def get_impact_score(impact_str, estimate=None):
    """Determine impact level from Finnhub data"""
    impact = impact_str.lower() if impact_str else "low"
    event_keywords_critical = ["interest rate", "fomc", "federal funds", "nonfarm", "non-farm"]
    event_keywords_high = ["cpi", "ppi", "inflation", "gdp", "retail sales", "unemployment",
                           "jobless claims", "consumer sentiment", "housing starts", "building permits"]
    title_lower = (title_str := "").lower()
    
    for kw in event_keywords_critical:
        if kw in impact or kw in title_lower:
            return "Extremely High"
    for kw in event_keywords_high:
        if kw in impact or kw in title_lower:
            return "High"
    if impact == "high":
        return "High"
    elif impact == "medium":
        return "Medium"
    return "Low"

def fetch_economic_calendar():
    """Pull economic calendar from Finnhub API — real data only"""
    events = []
    now = datetime.now(timezone.utc)
    days_ahead = 90
    date_from = now.strftime("%Y-%m-%d")
    date_to = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/calendar/economic",
            params={"token": FINNHUB_API_KEY, "from": date_from, "to": date_to},
            timeout=30
        )
        data = resp.json()
        raw_events = data.get("economicCalendar", [])
        print(f"  -> Finnhub returned {len(raw_events)} economic events")
        
        # Filter: US only, medium+ impact
        us_events = [e for e in raw_events 
                     if e.get("country") == "US" 
                     and e.get("impact") in ("medium", "high")]
        
        print(f"  -> US medium/high: {len(us_events)}")
        
        for e in us_events:
            event_name = e.get("event", "")
            impact_raw = e.get("impact", "low")
            estimate = e.get("estimate")
            prev = e.get("previous")
            time_str = e.get("time", "")
            # Normalize time to YYYY-MM-DD HH:MM:SS if available
            if time_str:
                # Finnhub returns like "2026-06-23 12:30:00" or "2026-06-23 12:30"
                time_str = time_str.replace("T", " ").strip()
                if len(time_str) <= 10:  # Just date, add time
                    time_str += " 00:00:00"
                elif len(time_str) <= 16:  # No seconds
                    time_str += ":00"
            
            # Determine impact level
            kw_critical = ["interest rate", "fomc", "federal funds", "nonfarm", "non-farm", "federal open"]
            kw_high = ["cpi", "ppi", "inflation", "gdp", "retail sales", "unemployment",
                       "jobless claims", "consumer sentiment", "housing starts", "building permits",
                       "durable goods", "pce", "michigan", "empire state", "ism", "adp employment"]
            
            impact_level = "Medium"
            for kw in kw_critical:
                if kw in event_name.lower():
                    impact_level = "Extremely High"
                    break
            if impact_level != "Extremely High":
                for kw in kw_high:
                    if kw in event_name.lower():
                        impact_level = "High"
                        break
            if impact_level == "Medium" and impact_raw == "high":
                impact_level = "High"
            
            # Build impact description
            analysis_parts = []
            if estimate is not None:
                analysis_parts.append(f"Estimate: {estimate}")
            if prev is not None:
                analysis_parts.append(f"Previous: {prev}")
            unit = e.get("unit", "")
            if unit:
                analysis_parts.append(f"Unit: {unit}")
            
            analysis = " | ".join(analysis_parts) if analysis_parts else "No estimates available"
            
            events.append({
                "title": event_name,
                "date": time_str if time_str else e.get("time", ""),
                "type": "Macro - Economic Data",
                "source": "Finnhub",
                "source_url": "https://finnhub.io",
                "impact_analysis": f"{impact_level} - {analysis}",
                "asset_impact": "BTC/ETH/US Equities/USD"
            })
    except Exception as ex:
        print(f"  -> Finnhub economic calendar error: {ex}")
    
    return events

def fetch_fomc_specific():
    """FOMC events are in the economic calendar but let's highlight them"""
    # These come from the economic calendar already, no separate fetch needed
    return []

def fetch_earnings_calendar():
    """Pull earnings calendar from Finnhub API — real data only"""
    events = []
    now = datetime.now(timezone.utc)
    days_ahead = 90
    date_from = now.strftime("%Y-%m-%d")
    date_to = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    
    crypto_related = ["COIN", "MSTR", "MARA", "RIOT", "HOOD", "NVDA", "SQ", "PYPL", "CLSK", "HUT", "BITF", "IREN"]
    
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/calendar/earnings",
            params={"token": FINNHUB_API_KEY, "from": date_from, "to": date_to},
            timeout=30
        )
        data = resp.json()
        raw_events = data.get("earningsCalendar", [])
        print(f"  -> Finnhub returned {len(raw_events)} earnings events")
        
        for e in raw_events:
            symbol = e.get("symbol", "")
            if symbol in crypto_related:
                eps = e.get("epsEstimate")
                rev = e.get("revenueEstimate")
                
                impact = "Medium"
                if symbol in ["COIN", "MSTR", "NVDA"]:
                    impact = "Extremely High" if symbol == "NVDA" else "High"
                
                analysis_parts = []
                if eps is not None:
                    analysis_parts.append(f"EPS Est: ${eps:.4f}")
                if rev is not None:
                    analysis_parts.append(f"Revenue Est: ${rev:,.0f}")
                analysis = " | ".join(analysis_parts) if analysis_parts else "No estimates available"
                
                events.append({
                    "title": f"{symbol} Q2 Earnings",
                    "date": e.get("date", "") + " 00:00:00",
                    "type": "US Equities - Earnings",
                    "source": "Finnhub",
                    "source_url": f"https://finance.yahoo.com/quote/{symbol}",
                    "impact_analysis": f"{impact} - {analysis}",
                    "asset_impact": f"{symbol} Stock + Related Crypto Assets"
                })
    except Exception as ex:
        print(f"  -> Finnhub earnings calendar error: {ex}")
    
    return events

def fetch_ipo_calendar():
    """Pull IPO calendar from Finnhub API"""
    events = []
    now = datetime.now(timezone.utc)
    days_ahead = 90
    date_from = now.strftime("%Y-%m-%d")
    date_to = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/calendar/ipo",
            params={"token": FINNHUB_API_KEY, "from": date_from, "to": date_to},
            timeout=30
        )
        data = resp.json()
        raw_events = data.get("ipoCalendar", [])
        print(f"  -> Finnhub returned {len(raw_events)} IPO events")
        
        for e in raw_events:
            name = e.get("name", "")
            exchange = e.get("exchange", "")
            price_range = e.get("priceRange", "")
            
            if name and exchange:
                events.append({
                    "title": f"IPO: {name} on {exchange}",
                    "date": e.get("date", "") + " 00:00:00",
                    "type": "US Equities - IPO",
                    "source": "Finnhub",
                    "source_url": "https://finnhub.io",
                    "impact_analysis": f"Medium - IPO on {exchange}" + (f" | Price: {price_range}" if price_range else ""),
                    "asset_impact": "Market sentiment indicator"
                })
    except Exception as ex:
        print(f"  -> Finnhub IPO calendar error: {ex}")
    
    return events

def output_local(events, json_events=None):
    output_file = "/data/ai/tmp/catalyst_events.json"
    md_file = "/data/ai/tmp/catalyst_events.md"
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    existing = []
    if os.path.exists(output_file):
        try:
            with open(output_file) as f:
                existing = json.load(f)
        except:
            existing = []

    # Dedup
    existing_hashes = set()
    for e in existing:
        h = hashlib.md5(f"{e['title']}|{e['date']}|{e['source']}".encode()).hexdigest()[:12]
        existing_hashes.add(h)
    for e in events:
        h = hashlib.md5(f"{e['title']}|{e['date']}|{e['source']}".encode()).hexdigest()[:12]
        if h not in existing_hashes:
            existing_hashes.add(h)
            existing.append(e)

    # Keep 90 days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    existing = [e for e in existing if e["date"] >= cutoff]

    with open(output_file, "w") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    # Also write to SQLite
    if json_events:
        from catalyst_db import insert_events, init_db
        init_db()
        new_count = insert_events(json_events)
        print(f"  -> SQLite: {new_count} new events inserted")

    # MD summary
    with open(md_file, "w") as f:
        f.write(f"# Catalyst Calendar\n\n")
        f.write(f"**Updated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")
        f.write(f"**Total Events**: {len(existing)}\n")
        f.write(f"**Source**: Finnhub API (real-time)\n\n")
        
        week = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
        week_events = [e for e in existing if e["date"][:10] <= week and e["date"] >= datetime.now(timezone.utc).strftime("%Y-%m-%d")]
        if week_events:
            f.write("## Next 7 Days\n\n")
            for e in sorted(week_events, key=lambda x: x["date"]):
                f.write(f"- **{e['date']}** | {e['title']} | {e['impact_analysis']}\n")
            f.write("\n---\n\n")
        
        by_type = {}
        for e in sorted(existing, key=lambda x: x["date"]):
            t = e["type"]
            if t not in by_type: by_type[t] = []
            by_type[t].append(e)
        for t, items in by_type.items():
            f.write(f"## {t}\n\n")
            f.write("| Date | Event | Assets | Source |\n")
            f.write("|------|------|--------|------|\n")
            for item in items:
                f.write(f"| {item['date']} | {item['title']} | {item['asset_impact']} | [{item['source']}]({item['source_url']}) |\n")
            f.write("\n")

def main():
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}] Collecting catalyst events from REAL APIs...")
    all_events = []
    
    print("  -> Fetching economic calendar (Finnhub)...")
    all_events.extend(fetch_economic_calendar())
    
    print("  -> Fetching earnings calendar (Finnhub)...")
    all_events.extend(fetch_earnings_calendar())
    
    print("  -> Fetching IPO calendar (Finnhub)...")
    all_events.extend(fetch_ipo_calendar())
    
    print(f"  -> Collected {len(all_events)} events from APIs")
    
    # Dedup
    dedup = load_dedup_set()
    new_events = []
    for e in all_events:
        h = event_hash(e["title"], e["date"], e["source"])
        if h not in dedup:
            dedup.add(h)
            new_events.append(e)
    save_dedup_set(dedup)
    print(f"  -> {len(new_events)} new after dedup")
    
    # Stats
    types = Counter(e["type"] for e in all_events)
    print(f"  -> By type: {dict(types)}")
    
    output_local(new_events, all_events)
    print(f"  -> Saved to /data/ai/tmp/catalyst_events.json")
    
    # Increment API call counter in stats
    try:
        import requests as req
        req.get("http://127.0.0.1:17002/api/track-api-call", timeout=5)
    except:
        pass
    
    # Generate HTML
    os.system("python3 /data/ai/tmp/catalyst_html.py 2>&1 | tail -1")
    print("[Done]")

if __name__ == "__main__":
    main()
