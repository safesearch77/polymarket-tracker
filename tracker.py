#!/usr/bin/env python3
"""
Polymarket Ukraine War Activity Tracker
Tracks: volume leaders, price movers, hottest markets
Fetches ALL Ukraine-related markets (territorial + peace deals + relations)
Runs hourly via GitHub Actions
"""

import json
import os
import re
import requests
import time
from datetime import datetime, timezone

GAMMA_API = "https://gamma-api.polymarket.com"

# Multiple search terms to catch all Ukraine markets
SEARCH_TERMS = ["ukraine", "kyiv", "zelensky", "crimea", "donbas", "donbass", "kherson", "zaporizhzhia"]
TAG_SLUGS = ["ukraine-map", "ukraine", "russia-ukraine"]

OUTPUT_FILE = "polymarket-activity.json"
HISTORY_FILE = "price-history.json"

REQUEST_DELAY = 0.2


def resolve_tag_id(slug):
    """Resolve tag slug to numeric ID"""
    print(f"  Resolving tag: {slug}")
    
    try:
        r = requests.get(f"{GAMMA_API}/tags/slug/{slug}", timeout=15)
        if r.status_code == 200:
            data = r.json()
            tag_id = data.get("id")
            if tag_id:
                print(f"    Found ID: {tag_id}")
                return tag_id
    except Exception as e:
        print(f"    Failed: {e}")
    
    return None


def fetch_markets_by_tag(tag_id):
    """Fetch markets for a specific tag ID"""
    all_markets = []
    offset = 0
    limit = 100
    
    while True:
        params = {
            "tag_id": tag_id,
            "related_tags": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset,
            "order": "volumeNum",
            "ascending": "false"
        }
        
        try:
            r = requests.get(f"{GAMMA_API}/markets", params=params, timeout=30)
            r.raise_for_status()
            markets = r.json()
            
            if not markets:
                break
            
            all_markets.extend(markets)
            
            if len(markets) < limit:
                break
            
            offset += limit
            time.sleep(REQUEST_DELAY)
            
        except Exception:
            break
    
    return all_markets


def fetch_markets_by_search(term):
    """Fetch markets matching a search term via text search"""
    all_markets = []
    offset = 0
    limit = 100
    
    while True:
        params = {
            "closed": "false",
            "limit": limit,
            "offset": offset,
            "order": "volumeNum",
            "ascending": "false"
        }
        
        try:
            # Try text_query parameter
            r = requests.get(f"{GAMMA_API}/markets?text_query={term}", params=params, timeout=30)
            if r.status_code != 200:
                # Fallback - just get all and filter
                break
            
            markets = r.json()
            if not markets:
                break
            
            all_markets.extend(markets)
            
            if len(markets) < limit:
                break
            
            offset += limit
            time.sleep(REQUEST_DELAY)
            
        except Exception:
            break
    
    return all_markets


def is_ukraine_related(market):
    """Check if market is Ukraine-related by keywords in question/description"""
    text = (market.get("question", "") + " " + market.get("description", "")).lower()
    
    keywords = [
        "ukraine", "ukrainian", "kyiv", "kiev", "zelensky", "zelenskyy",
        "crimea", "donbas", "donbass", "kherson", "zaporizhzhia", "mariupol",
        "bakhmut", "avdiivka", "pokrovsk", "kursk", "kharkiv", "odesa", "odessa",
        "russia capture", "russian capture", "russia enter", "russian forces",
        "putin", "moscow", "kremlin"
    ]
    
    return any(kw in text for kw in keywords)


def fetch_all_ukraine_markets():
    """Fetch ALL Ukraine-related markets from multiple sources"""
    print("Fetching ALL Ukraine-related markets...")
    
    seen_slugs = set()
    all_markets = []
    
    # Method 1: Fetch from known tags
    for slug in TAG_SLUGS:
        tag_id = resolve_tag_id(slug)
        if tag_id:
            markets = fetch_markets_by_tag(tag_id)
            for m in markets:
                if m.get("slug") not in seen_slugs:
                    seen_slugs.add(m.get("slug"))
                    all_markets.append(m)
            print(f"    Tag '{slug}': {len(markets)} markets")
            time.sleep(REQUEST_DELAY)
    
    # Method 2: Fetch all open markets and filter by Ukraine keywords
    print("  Fetching all markets and filtering...")
    offset = 0
    limit = 100
    checked = 0
    
    while offset < 2000:  # Cap at 2000 to avoid infinite loops
        try:
            params = {
                "closed": "false",
                "limit": limit,
                "offset": offset,
                "order": "volumeNum",
                "ascending": "false"
            }
            r = requests.get(f"{GAMMA_API}/markets", params=params, timeout=30)
            r.raise_for_status()
            markets = r.json()
            
            if not markets:
                break
            
            for m in markets:
                checked += 1
                slug = m.get("slug")
                if slug and slug not in seen_slugs and is_ukraine_related(m):
                    seen_slugs.add(slug)
                    all_markets.append(m)
            
            if len(markets) < limit:
                break
            
            offset += limit
            time.sleep(REQUEST_DELAY)
            
        except Exception as e:
            print(f"    Error: {e}")
            break
    
    print(f"  Checked {checked} markets total, found {len(all_markets)} Ukraine-related")
    return all_markets


def load_previous_snapshot():
    """Load previous snapshot for delta calculations"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_snapshot(markets):
    """Save current snapshot for future delta calculations"""
    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "markets": {}
    }
    
    for m in markets:
        slug = m.get("slug", "")
        if slug:
            snapshot["markets"][slug] = {
                "volumeNum": m.get("volumeNum", 0),
                "volume24hr": m.get("volume24hr", 0),
                "lastTradePrice": m.get("lastTradePrice", 0)
            }
    
    with open(HISTORY_FILE, 'w') as f:
        json.dump(snapshot, f, indent=2)
    
    return snapshot


def classify_market(question):
    """Classify market type for better display"""
    q = question.lower()
    
    if any(x in q for x in ["capture", "enter", "recapture", "take control"]):
        return "territorial"
    elif any(x in q for x in ["peace", "ceasefire", "truce", "armistice", "negotiate", "treaty"]):
        return "peace"
    elif any(x in q for x in ["election", "president", "zelensky", "putin", "leader"]):
        return "political"
    elif any(x in q for x in ["aid", "weapon", "military assistance", "funding", "billion"]):
        return "aid"
    elif any(x in q for x in ["nato", "eu", "european union", "alliance"]):
        return "diplomatic"
    else:
        return "general"


def build_report(markets, previous_snapshot):
    """Build activity report using API-provided fields"""
    
    def get_current_price(m):
        """Get current market price from outcomePrices (mid-market), fall back to lastTradePrice"""
        # outcomePrices contains actual current market prices, not just last trade
        outcome_prices = m.get("outcomePrices")
        if outcome_prices:
            try:
                # Parse if it's a string (API returns stringified JSON)
                if isinstance(outcome_prices, str):
                    import json
                    prices = json.loads(outcome_prices)
                else:
                    prices = outcome_prices
                # First price is typically YES outcome
                if prices and len(prices) > 0:
                    return float(prices[0])
            except:
                pass
        # Fall back to lastTradePrice
        return m.get("lastTradePrice")
    
    def simplify(m):
        mtype = classify_market(m.get("question", ""))
        
        # Extract parent event slug from events array for correct URL
        # The 'events' array contains parent event objects with the correct slug
        parent_event_slug = ""
        events = m.get("events", [])
        if events and isinstance(events, list) and len(events) > 0:
            parent_event_slug = events[0].get("slug", "")
        
        # Fall back to market slug if no parent event found
        url_slug = parent_event_slug or m.get("slug", "")
        
        # Get current price (prefer outcomePrices over lastTradePrice)
        current_price = get_current_price(m)
        
        return {
            "slug": m.get("slug", ""),
            "eventSlug": url_slug,  # This is now the parent event slug for URLs
            "question": m.get("question", ""),
            "volume24hr": round(m.get("volume24hr") or 0, 2),
            "volumeNum": round(m.get("volumeNum") or 0, 2),
            "currentPrice": current_price,  # Actual market price from order book
            "lastTradePrice": m.get("lastTradePrice"),  # Keep for reference
            "endDate": m.get("endDate"),
            "market_type": mtype,
        }
    
    # Top by 24h volume - fetch more for filtering
    top_volume_24h = sorted(
        [m for m in markets if m.get("volume24hr")],
        key=lambda x: x.get("volume24hr", 0),
        reverse=True
    )[:100]
    
    # Top by total volume
    top_volume_total = sorted(
        [m for m in markets if m.get("volumeNum")],
        key=lambda x: x.get("volumeNum", 0),
        reverse=True
    )[:100]
    
    # Hottest: 24h volume as % of total (which markets are heating up)
    hot = []
    for m in markets:
        v24 = m.get("volume24hr") or 0
        vtotal = m.get("volumeNum") or 0
        if vtotal > 1000:
            heat = (v24 / vtotal) * 100
            hot.append({"market": m, "heat_score": round(heat, 2)})
    hot = sorted(hot, key=lambda x: x["heat_score"], reverse=True)[:100]
    
    # Top movers 1h (using API field)
    movers_1h = sorted(
        [m for m in markets if m.get("oneHourPriceChange") is not None],
        key=lambda x: abs(x.get("oneHourPriceChange", 0)),
        reverse=True
    )[:50]
    
    # Top movers 24h (using API field)
    movers_24h = sorted(
        [m for m in markets if m.get("oneDayPriceChange") is not None],
        key=lambda x: abs(x.get("oneDayPriceChange", 0)),
        reverse=True
    )[:50]
    
    # Volume spikes since last snapshot
    prev_markets = previous_snapshot.get("markets", {})
    spikes = []
    for m in markets:
        slug = m.get("slug", "")
        if slug in prev_markets:
            curr = m.get("volumeNum") or 0
            prev = prev_markets[slug].get("volumeNum") or 0
            delta = curr - prev
            if delta > 100:
                spikes.append({"market": m, "delta": round(delta, 2)})
    spikes = sorted(spikes, key=lambda x: x["delta"], reverse=True)[:50]
    
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "previous_snapshot": previous_snapshot.get("timestamp", "none"),
        "total_markets": len(markets),
        
        "top_volume_24h": [
            {**simplify(m), "rank": i+1}
            for i, m in enumerate(top_volume_24h)
        ],
        
        "top_volume_total": [
            {**simplify(m), "rank": i+1}
            for i, m in enumerate(top_volume_total)
        ],
        
        "hottest_markets": [
            {**simplify(h["market"]), "heat_score": h["heat_score"], "rank": i+1}
            for i, h in enumerate(hot)
        ],
        
        "top_movers_1h": [
            {
                **simplify(m),
                "price_change_1h": round((m.get("oneHourPriceChange") or 0) * 100, 2),
                "rank": i+1
            }
            for i, m in enumerate(movers_1h)
        ],
        
        "top_movers_24h": [
            {
                **simplify(m),
                "price_change_24h": round((m.get("oneDayPriceChange") or 0) * 100, 2),
                "rank": i+1
            }
            for i, m in enumerate(movers_24h)
        ],
        
        "volume_spikes": [
            {**simplify(s["market"]), "volume_delta": s["delta"], "rank": i+1}
            for i, s in enumerate(spikes)
        ]
    }
    
    return report


def main():
    print("=" * 60)
    print("Polymarket Ukraine War Activity Tracker")
    print(f"Running at: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    
    # Fetch ALL Ukraine-related markets
    markets = fetch_all_ukraine_markets()
    print(f"\nFound {len(markets)} total Ukraine-related markets")
    
    if not markets:
        print("No markets found, exiting")
        return
    
    # Count by type
    type_counts = {}
    for m in markets:
        mtype = classify_market(m.get("question", ""))
        type_counts[mtype] = type_counts.get(mtype, 0) + 1
    print(f"Market types: {type_counts}")
    
    # Load previous snapshot
    prev = load_previous_snapshot()
    if prev:
        print(f"Previous snapshot: {prev.get('timestamp', 'unknown')}")
    else:
        print("No previous snapshot (first run)")
    
    # Build report
    report = build_report(markets, prev)
    
    # Save outputs
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved report to {OUTPUT_FILE}")
    
    save_snapshot(markets)
    print(f"Saved snapshot to {HISTORY_FILE}")
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    print("\n📊 Top 5 by 24h Volume:")
    for m in report["top_volume_24h"][:5]:
        print(f"  ${m['volume24hr']:,.0f} - {m['question'][:60]}")
    
    print("\n🔥 Top 5 Hottest:")
    for m in report["hottest_markets"][:5]:
        print(f"  {m['heat_score']:.1f}% - {m['question'][:60]}")
    
    print("\n📈 Top 5 Movers (1h):")
    for m in report["top_movers_1h"][:5]:
        chg = m["price_change_1h"]
        arrow = "↑" if chg > 0 else "↓"
        print(f"  {arrow} {abs(chg):.1f}pp - {m['question'][:55]}")
    
    print("\n📉 Top 5 Movers (24h):")
    for m in report["top_movers_24h"][:5]:
        chg = m["price_change_24h"]
        arrow = "↑" if chg > 0 else "↓"
        print(f"  {arrow} {abs(chg):.1f}pp - {m['question'][:55]}")
    
    if report["volume_spikes"]:
        print("\n💰 Top 5 Volume Spikes:")
        for m in report["volume_spikes"][:5]:
            print(f"  +${m['volume_delta']:,.0f} - {m['question'][:55]}")


if __name__ == "__main__":
    main()
