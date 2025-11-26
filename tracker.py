#!/usr/bin/env python3
"""
Polymarket Ukraine War Activity Tracker
Tracks: volume leaders, price movers, hottest markets
Runs hourly via GitHub Actions
"""

import json
import os
import requests
import time
from datetime import datetime, timezone

GAMMA_API = "https://gamma-api.polymarket.com"
TAG_SLUG = "ukraine-map"

OUTPUT_FILE = "polymarket-activity.json"
HISTORY_FILE = "price-history.json"

REQUEST_DELAY = 0.15


def resolve_tag_id(slug):
    """Resolve tag slug to numeric ID"""
    print(f"Resolving tag slug: {slug}")
    
    # Try direct slug endpoint first
    try:
        r = requests.get(f"{GAMMA_API}/tags/slug/{slug}", timeout=15)
        if r.status_code == 200:
            data = r.json()
            tag_id = data.get("id")
            print(f"  Found tag ID: {tag_id}")
            return tag_id
    except Exception as e:
        print(f"  Slug endpoint failed: {e}")
    
    # Fallback: search all tags
    print("  Falling back to tag list search...")
    try:
        r = requests.get(f"{GAMMA_API}/tags", timeout=30)
        r.raise_for_status()
        tags = r.json()
        
        for t in tags:
            if t.get("slug") == slug or slug in t.get("label", "").lower():
                tag_id = t.get("id")
                print(f"  Found tag ID via search: {tag_id} ({t.get('label')})")
                return tag_id
    except Exception as e:
        print(f"  Tag list search failed: {e}")
    
    return None


def fetch_markets(tag_id):
    """Fetch all open markets for a tag"""
    print(f"Fetching markets for tag ID: {tag_id}")
    
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
            print(f"  Fetched {len(markets)} markets (total: {len(all_markets)})")
            
            if len(markets) < limit:
                break
            
            offset += limit
            time.sleep(REQUEST_DELAY)
            
        except Exception as e:
            print(f"  Error fetching markets: {e}")
            break
    
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


def build_report(markets, previous_snapshot):
    """Build activity report using API-provided fields"""
    
    def simplify(m):
        return {
            "slug": m.get("slug", ""),
            "question": m.get("question", ""),
            "volume24hr": round(m.get("volume24hr") or 0, 2),
            "volumeNum": round(m.get("volumeNum") or 0, 2),
            "lastTradePrice": m.get("lastTradePrice"),
            "endDate": m.get("endDate"),
        }
    
    # Top by 24h volume
    top_volume_24h = sorted(
        [m for m in markets if m.get("volume24hr")],
        key=lambda x: x.get("volume24hr", 0),
        reverse=True
    )[:20]
    
    # Top by total volume
    top_volume_total = sorted(
        [m for m in markets if m.get("volumeNum")],
        key=lambda x: x.get("volumeNum", 0),
        reverse=True
    )[:20]
    
    # Hottest: 24h volume as % of total (which markets are heating up)
    hot = []
    for m in markets:
        v24 = m.get("volume24hr") or 0
        vtotal = m.get("volumeNum") or 0
        if vtotal > 1000:
            heat = (v24 / vtotal) * 100
            hot.append({"market": m, "heat_score": round(heat, 2)})
    hot = sorted(hot, key=lambda x: x["heat_score"], reverse=True)[:20]
    
    # Top movers 1h (using API field)
    movers_1h = sorted(
        [m for m in markets if m.get("oneHourPriceChange") is not None],
        key=lambda x: abs(x.get("oneHourPriceChange", 0)),
        reverse=True
    )[:15]
    
    # Top movers 24h (using API field)
    movers_24h = sorted(
        [m for m in markets if m.get("oneDayPriceChange") is not None],
        key=lambda x: abs(x.get("oneDayPriceChange", 0)),
        reverse=True
    )[:15]
    
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
    spikes = sorted(spikes, key=lambda x: x["delta"], reverse=True)[:15]
    
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
    
    # Resolve tag
    tag_id = resolve_tag_id(TAG_SLUG)
    if not tag_id:
        print("ERROR: Could not resolve tag ID")
        return
    
    # Fetch markets
    markets = fetch_markets(tag_id)
    print(f"\nFound {len(markets)} open markets")
    
    if not markets:
        print("No markets found, exiting")
        return
    
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
