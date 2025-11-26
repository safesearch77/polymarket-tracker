# Polymarket Ukraine War Activity Tracker

Tracks Ukraine war prediction markets on Polymarket, updating hourly via GitHub Actions.

## Output Data (`polymarket-activity.json`)

### Rankings Provided:

1. **`top_volume_24h`** - Markets with highest trading volume in last 24 hours
2. **`top_volume_total`** - Markets with highest all-time volume
3. **`hottest_markets`** - Markets where 24h volume is highest % of total volume (heating up)
4. **`top_movers_1h`** - Biggest price changes in last 1 hour (percentage points)
5. **`top_movers_24h`** - Biggest price changes in last 24 hours (percentage points)
6. **`volume_spikes`** - Markets with biggest volume increase since last hourly snapshot

### Sample Output Structure:

```json
{
  "generated_at": "2025-11-26T00:15:00Z",
  "previous_snapshot": "2025-11-25T23:15:00Z",
  "total_markets": 45,
  
  "top_volume_24h": [
    {
      "slug": "will-russia-capture-pokrovsk",
      "question": "Will Russia capture all of Pokrovsk by...",
      "volume24hr": 125000,
      "volumeNum": 850000,
      "lastTradePrice": 0.45,
      "rank": 1
    }
  ],
  
  "top_movers_1h": [
    {
      "slug": "will-russia-capture-kupiansk",
      "question": "Will Russia capture Kupiansk...",
      "current_price": 32.5,
      "price_1h_ago": 28.0,
      "points_change": 4.5,
      "pct_change": 16.07,
      "rank": 1
    }
  ],
  
  "hottest_markets": [
    {
      "slug": "will-russia-capture-vovchansk",
      "question": "...",
      "heat_score": 8.5,
      "rank": 1
    }
  ]
}
```

## How It Works

1. **Fetches markets** from Polymarket Gamma API using `tag_id=ukraine-map`
2. **Gets price history** from CLOB API for each market's Yes token
3. **Calculates deltas** by comparing to previous hourly snapshot
4. **Outputs rankings** to `polymarket-activity.json`

## Files

- `tracker.py` - Main Python script
- `polymarket-activity.json` - Current activity report (updated hourly)
- `price-history.json` - Snapshot for delta calculations (don't delete)
- `.github/workflows/update-activity.yml` - GitHub Actions workflow

## Usage

### Manual Run
```bash
pip install requests
python tracker.py
```

### GitHub Actions
Runs automatically every hour at :15 past the hour.

## Data Sources

- **Gamma API**: `https://gamma-api.polymarket.com/markets?tag_id=ukraine-map`
- **CLOB API**: `https://clob.polymarket.com/prices-history`

## Integration with Ukraine War Map

The output JSON can be fetched by the map to display:
- Trending markets panel
- Price movement alerts
- Volume spike indicators

```javascript
const ACTIVITY_URL = 'https://raw.githubusercontent.com/YOUR_USERNAME/polymarket-tracker/main/polymarket-activity.json';
const activity = await fetch(ACTIVITY_URL).then(r => r.json());
```
