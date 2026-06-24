#!/usr/bin/env python3
"""
Deterministic API Resolvers for Economic Events.
Uses FRED and BLS APIs to fetch official data without LLM hallucination.
"""

import os
import re
import json
import urllib.request
from datetime import datetime, timedelta

# Load API keys
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
BLS_API_KEY = os.environ.get("BLS_API_KEY", "")

# Metric Mapping: keyword -> (FRED series, BLS series, friendly_name)
# FRED is preferred for most, BLS for employment/detailed CPI
METRIC_MAP = {
    "CPI": ("CPIAUCSL", "CUUR0000SA0", "Consumer Price Index (All Items)"),
    "Core CPI": ("CPILFESL", "CUUR0000SA0L1E", "Core CPI (Excl. Food & Energy)"),
    "Unemployment Rate": ("UNRATE", "LNS14000000", "Unemployment Rate"),
    "GDP": ("GDPC1", None, "Real GDP"),
    "Fed Funds Rate": ("FEDFUNDS", None, "Federal Funds Rate"),
    "Nonfarm Payrolls": (None, "CES0000000001", "Nonfarm Payrolls"),
    "Retail Sales": ("RSAFS", None, "Retail Sales"),
    "PPI": ("PPIACO", "PCUOMFGOMFG", "Producer Price Index"),
    "Initial Jobless Claims": ("ICSA", None, "Initial Jobless Claims"),
    "Industrial Production": ("INDPRO", None, "Industrial Production Index"),
    "Housing Starts": ("HOUST", None, "Housing Starts"),
    "Consumer Confidence": ("UMCSENT", None, "Michigan Consumer Sentiment"),
}

def map_event_to_metric(event_name: str) -> tuple:
    """Match event name to known metric. Returns (metric_key, series_id, source_pref)."""
    event_upper = event_name.upper()
    for key, (fred_id, bls_id, _) in METRIC_MAP.items():
        if key.upper() in event_upper:
            # Prefer BLS for employment data, FRED for everything else
            if "PAYROLLS" in event_upper or "NONFARM" in event_upper or "UNEMPLOYMENT" in event_upper:
                return key, bls_id, "BLS" if bls_id else "FRED"
            return key, fred_id, "FRED" if fred_id else "BLS"
    return None, None, None

def fred_fetch(series_id: str, date: str = None) -> str:
    """Fetch latest observation from FRED."""
    if not series_id or not FRED_API_KEY:
        return None
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json&limit=3&sort_order=desc"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.load(resp)
        obs = data.get("observations", [])
        for ob in obs:
            # Skip missing values
            if ob.get("value") == ".":
                continue
            # If date specified, find closest match
            if date:
                if ob["date"] <= date:
                    return ob["value"]
            else:
                return ob["value"]
    except Exception as e:
        print(f"FRED fetch error: {e}")
    return None

def bls_fetch(series_id: str, date: str = None) -> str:
    """Fetch latest observation from BLS."""
    if not series_id or not BLS_API_KEY:
        return None
    year = date[:4] if date else str(datetime.now().year)
    payload = {
        "seriesid": [series_id],
        "registrationKey": BLS_API_KEY,
        "startyear": year,
        "endyear": year,
    }
    try:
        req = urllib.request.Request(
            "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
        
        results = data.get("Results", {}).get("series", [])
        if not results:
            return None
        
        # BLS returns monthly data, find the month matching date
        if date:
            target_month = date[5:7]  # "MM"
            for item in results[0].get("data", []):
                if item.get("period")[1:] == target_month:
                    return item.get("value")
        
        # Otherwise return latest
        return results[0].get("data", [{}])[0].get("value")
    except Exception as e:
        print(f"BLS fetch error: {e}")
    return None

def resolve_event_api(event_name: str, event_date: str = None) -> dict:
    """
    Try to resolve an event using official APIs.
    Returns: {"value": str, "source": str, "metric": str} or None
    """
    metric, series_id, source_pref = map_event_to_metric(event_name)
    if not metric:
        return None
    
    # Try preferred source first
    value = None
    source = source_pref
    if source_pref == "FRED":
        value = fred_fetch(series_id, event_date)
        if not value and "BLS" in [s for k, (_, s, _) in METRIC_MAP.items() if k == metric]:
            # Fallback to BLS if available
            bls_id = METRIC_MAP[metric][1]
            value = bls_fetch(bls_id, event_date)
            source = "BLS" if value else "FRED"
    elif source_pref == "BLS":
        value = bls_fetch(series_id, event_date)
        if not value:
            fred_id = METRIC_MAP[metric][0]
            value = fred_fetch(fred_id, event_date)
            source = "FRED" if value else "BLS"
    
    if value:
        return {"value": value, "source": source, "metric": metric}
    
    return None
