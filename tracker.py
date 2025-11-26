#!/usr/bin/env python3
"""
Polymarket Ukraine War Activity Tracker
Tracks: top volume markets, sudden price movers, volume spikes
Runs hourly via GitHub Actions
"""

import json
import os
import requests
from datetime import datetime, timezone
from pathlib import Path

# API endpoints
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# Ukraine war tag ID (from your existing setup)
UKRAINE_TAG_ID = "ukraine-map"

# Output files
OUTPUT_FILE = "polymarket-activity.json"
HISTORY_FILE = "price-history.json"

# Rate limiting
REQUEST_DELAY = 0.1  # 100ms between requests


def fetch_ukraine_markets():
    """Fetch all open Ukraine war markets from Gamma API"""
    print("Fetching Ukraine war markets...")
    
    all_markets = []
    offset = 0
    limit = 100
    
    while True:
        url = f"{GAMMA_API}/markets"
        params = {
            "tag_id": UKRAINE_TAG_ID,
            "related_tags": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset
        }
        
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            markets = response.json()
            
            if not markets:
                break
                
            all_markets.extend(markets)
            print(f"  Fetched {len(markets)} markets (total: {len(all_markets)})")
            
            if len(markets) < limit:
                break
                
            offset += limit
            
        except Exception as e:
            print(f"  Error fetching markets: {e}")
            break
    
    return all_markets


def fetch_price_history(token_id, interval="1d", fidelity=60):
    """Fetch price history for a CLOB token"""
    url = f"{CLOB_API}/prices-history"
    params = {
        "market": token_id,
        "interval": interval,
        "fidelity": fidelity  # minutes between data points
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            return data.get("history", [])
    except Exception as e:
        pass
    
    return []


def calculate_price_changes(markets):
    """Calculate 1h, 6h, 24h price changes for each market"""
    print("Calculating price changes...")
    
    results = []
    
    for i, market in enumerate(markets):
        if i % 10 == 0:
            print(f"  Processing {i+1}/{len(markets)}...")
        
        # Get CLOB token IDs (Yes token is typically first)
        clob_token_ids = market.get("clobTokenIds", [])
        if not clob_token_ids:
            continue
        
        yes_token_id = clob_token_ids[0]
        
        # Fetch 24h price history with 1-minute fidelity for recent, hourly for older
        history = fetch_price_history(yes_token_id, interval="1d", fidelity=5)
        
        if not history or len(history) < 2:
            continue
        
        # Current price (latest)
        current_price = history[-1].get("p", 0)
        current_time = history[-1].get("t", 0)
        
        # Find prices at different intervals
        price_1h_ago = None
        price_6h_ago = None
        price_24h_ago = None
        
        now = current_time
        
        for point in reversed(history):
            t = point.get("t", 0)
            p = point.get("p", 0)
            age_hours = (now - t) / 3600
            
            if price_1h_ago is None and age_hours >= 1:
                price_1h_ago = p
            if price_6h_ago is None and age_hours >= 6:
                price_6h_ago = p
            if price_24h_ago is None and age_hours >= 24:
                price_24h_ago = p
                break
        
        # Calculate changes
        def calc_change(old, new):
            if old is None or old == 0:
                return None
            return round((new - old) / old * 100, 2)
        
        change_1h = calc_change(price_1h_ago, current_price)
        change_6h = calc_change(price_6h_ago, current_price)
        change_24h = calc_change(price_24h_ago, current_price)
        
        # Absolute point change (more intuitive for prediction markets)
        def calc_point_change(old, new):
            if old is None:
                return None
            return round((new - old) * 100, 1)  # Convert to percentage points
        
        points_1h = calc_point_change(price_1h_ago, current_price)
        points_6h = calc_point_change(price_6h_ago, current_price)
        points_24h = calc_point_change(price_24h_ago, current_price)
        
        results.append({
            "market": market,
            "current_price": round(current_price * 100, 1),  # As percentage
            "change_1h_pct": change_1h,
            "change_6h_pct": change_6h,
            "change_24h_pct": change_24h,
            "points_1h": points_1h,
            "points_6h": points_6h,
            "points_24h": points_24h,
            "price_1h_ago": round(price_1h_ago * 100, 1) if price_1h_ago else None,
            "price_24h_ago": round(price_24h_ago * 100, 1) if price_24h_ago else None
        })
        
        import time
        time.sleep(REQUEST_DELAY)
    
    return results


def load_previous_snapshot():
    """Load previous snapshot for delta calculations"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_current_snapshot(markets):
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


def calculate_volume_spikes(markets, previous_snapshot):
    """Calculate volume spikes vs previous snapshot"""
    spikes = []
    
    prev_markets = previous_snapshot.get("markets", {})
    prev_time = previous_snapshot.get("timestamp", "")
    
    for m in markets:
        slug = m.get("slug", "")
        current_vol = m.get("volumeNum", 0) or 0
        
        if slug in prev_markets:
            prev_vol = prev_markets[slug].get("volumeNum", 0) or 0
            vol_delta = current_vol - prev_vol
            
            # Calculate relative spike (avoid division by zero)
            if prev_vol > 0:
                vol_spike_pct = round((vol_delta / prev_vol) * 100, 2)
            else:
                vol_spike_pct = 0 if vol_delta == 0 else 100
            
            spikes.append({
                "market": m,
                "volume_delta": round(vol_delta, 2),
                "volume_spike_pct": vol_spike_pct,
                "current_volume": current_vol,
                "previous_volume": prev_vol
            })
    
    return spikes


def build_activity_report(markets, price_data, volume_spikes, previous_snapshot):
    """Build the final activity report"""
    
    # Top markets by 24h volume
    top_volume = sorted(
        [m for m in markets if m.get("volume24hr")],
        key=lambda x: x.get("volume24hr", 0),
        reverse=True
    )[:20]
    
    # Top markets by total volume
    top_total_volume = sorted(
        [m for m in markets if m.get("volumeNum")],
        key=lambda x: x.get("volumeNum", 0),
        reverse=True
    )[:20]
    
    # Hottest markets (24h volume as % of total - shows which are heating up)
    hot_markets = []
    for m in markets:
        vol_24h = m.get("volume24hr", 0) or 0
        vol_total = m.get("volumeNum", 0) or 0
        if vol_total > 1000:  # Minimum $1000 total volume
            heat = (vol_24h / vol_total) * 100 if vol_total > 0 else 0
            hot_markets.append({
                "market": m,
                "heat_score": round(heat, 2),
                "volume_24h": vol_24h,
                "volume_total": vol_total
            })
    
    hot_markets = sorted(hot_markets, key=lambda x: x["heat_score"], reverse=True)[:20]
    
    # Top price movers (absolute point change)
    top_movers_1h = sorted(
        [p for p in price_data if p["points_1h"] is not None],
        key=lambda x: abs(x["points_1h"]),
        reverse=True
    )[:15]
    
    top_movers_24h = sorted(
        [p for p in price_data if p["points_24h"] is not None],
        key=lambda x: abs(x["points_24h"]),
        reverse=True
    )[:15]
    
    # Top volume spikes (since last snapshot)
    top_volume_spikes = sorted(
        [s for s in volume_spikes if s["volume_delta"] > 100],  # Min $100 new volume
        key=lambda x: x["volume_delta"],
        reverse=True
    )[:15]
    
    def simplify_market(m):
        """Extract key fields from market object"""
        return {
            "slug": m.get("slug", ""),
            "question": m.get("question", ""),
            "volume24hr": round(m.get("volume24hr", 0) or 0, 2),
            "volumeNum": round(m.get("volumeNum", 0) or 0, 2),
            "lastTradePrice": m.get("lastTradePrice"),
            "endDate": m.get("endDate"),
            "outcomes": m.get("outcomes", [])
        }
    
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "previous_snapshot": previous_snapshot.get("timestamp", "none"),
        "total_markets": len(markets),
        
        "top_volume_24h": [
            {
                **simplify_market(m),
                "rank": i + 1
            }
            for i, m in enumerate(top_volume)
        ],
        
        "top_volume_total": [
            {
                **simplify_market(m),
                "rank": i + 1
            }
            for i, m in enumerate(top_total_volume)
        ],
        
        "hottest_markets": [
            {
                **simplify_market(h["market"]),
                "heat_score": h["heat_score"],
                "rank": i + 1
            }
            for i, h in enumerate(hot_markets)
        ],
        
        "top_movers_1h": [
            {
                **simplify_market(p["market"]),
                "current_price": p["current_price"],
                "price_1h_ago": p["price_1h_ago"],
                "points_change": p["points_1h"],
                "pct_change": p["change_1h_pct"],
                "rank": i + 1
            }
            for i, p in enumerate(top_movers_1h)
        ],
        
        "top_movers_24h": [
            {
                **simplify_market(p["market"]),
                "current_price": p["current_price"],
                "price_24h_ago": p["price_24h_ago"],
                "points_change": p["points_24h"],
                "pct_change": p["change_24h_pct"],
                "rank": i + 1
            }
            for i, p in enumerate(top_movers_24h)
        ],
        
        "volume_spikes": [
            {
                **simplify_market(s["market"]),
                "volume_delta": s["volume_delta"],
                "volume_spike_pct": s["volume_spike_pct"],
                "rank": i + 1
            }
            for i, s in enumerate(top_volume_spikes)
        ]
    }
    
    return report


def main():
    print("=" * 60)
    print("Polymarket Ukraine War Activity Tracker")
    print(f"Running at: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    
    # Fetch all Ukraine war markets
    markets = fetch_ukraine_markets()
    print(f"\nFound {len(markets)} open markets")
    
    if not markets:
        print("No markets found, exiting")
        return
    
    # Load previous snapshot for delta calculations
    previous_snapshot = load_previous_snapshot()
    if previous_snapshot:
        print(f"Previous snapshot: {previous_snapshot.get('timestamp', 'unknown')}")
    else:
        print("No previous snapshot found (first run)")
    
    # Calculate price changes (this takes a while due to API calls)
    price_data = calculate_price_changes(markets)
    print(f"Got price data for {len(price_data)} markets")
    
    # Calculate volume spikes
    volume_spikes = calculate_volume_spikes(markets, previous_snapshot)
    print(f"Calculated volume spikes for {len(volume_spikes)} markets")
    
    # Build activity report
    report = build_activity_report(markets, price_data, volume_spikes, previous_snapshot)
    
    # Save report
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved report to {OUTPUT_FILE}")
    
    # Save current snapshot for next run
    save_current_snapshot(markets)
    print(f"Saved snapshot to {HISTORY_FILE}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    print("\n📊 Top 5 by 24h Volume:")
    for m in report["top_volume_24h"][:5]:
        print(f"  ${m['volume24hr']:,.0f} - {m['question'][:60]}...")
    
    print("\n🔥 Top 5 Hottest (24h vol / total vol):")
    for m in report["hottest_markets"][:5]:
        print(f"  {m['heat_score']:.1f}% - {m['question'][:60]}...")
    
    print("\n📈 Top 5 Movers (1h):")
    for m in report["top_movers_1h"][:5]:
        direction = "↑" if m["points_change"] > 0 else "↓"
        print(f"  {direction} {abs(m['points_change']):.1f}pp ({m['current_price']:.0f}%) - {m['question'][:50]}...")
    
    print("\n📈 Top 5 Movers (24h):")
    for m in report["top_movers_24h"][:5]:
        direction = "↑" if m["points_change"] > 0 else "↓"
        print(f"  {direction} {abs(m['points_change']):.1f}pp ({m['current_price']:.0f}%) - {m['question'][:50]}...")
    
    if report["volume_spikes"]:
        print("\n💰 Top 5 Volume Spikes (since last run):")
        for m in report["volume_spikes"][:5]:
            print(f"  +${m['volume_delta']:,.0f} - {m['question'][:55]}...")


if __name__ == "__main__":
    main()
