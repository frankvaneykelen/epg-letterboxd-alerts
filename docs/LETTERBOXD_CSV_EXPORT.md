# Letterboxd CSV Export Instructions

## How to Export Your Letterboxd Data

Letterboxd allows you to export your watchlist and diary/watched films as CSV files. These can be used by epg-letterboxd-alerts without needing API access.

### Export Watchlist

1. Go to https://letterboxd.com/[your-username]/watchlist/
2. Click **Export** at the bottom of the page
3. Save the file as `letterboxd_watchlist.csv`

### Export Diary/Watched Films

1. Go to https://letterboxd.com/[your-username]/films/
2. Click **Export** at the bottom of the page
3. Save the file as `letterboxd_diary.csv`

### File Placement

Create a `data/` folder in your project root and place the CSV files there:

```
epg-letterboxd-alerts/
├── data/
│   ├── letterboxd_watchlist.csv
│   └── letterboxd_diary.csv
├── config.json
└── ...
```

Or update the paths in `config.json`:

```json
{
  "letterboxd": {
    "enabled": true,
    "mode": "csv",
    "watchlist_csv": "path/to/your/letterboxd_watchlist.csv",
    "diary_csv": "path/to/your/letterboxd_diary.csv"
  }
}
```

### Enable Letterboxd Integration

In `config.json`, set:

```json
{
  "letterboxd": {
    "enabled": true
  }
}
```

### CSV Format Requirements

The CSV exports from Letterboxd must include a `tmdbID` or `TMDb ID` column for matching with EPG data. Recent Letterboxd exports include this by default.

**Watchlist columns:** Name, Year, Letterboxd URI, tmdbID  
**Diary columns:** Name, Year, Letterboxd URI, Rating, tmdbID

### Keep Data Updated

Re-export your CSVs periodically to keep your watchlist and seen status current. The function will reload them each time it runs.

### Gitignore

The `data/` folder is already in `.gitignore` to prevent accidentally committing your personal data.
