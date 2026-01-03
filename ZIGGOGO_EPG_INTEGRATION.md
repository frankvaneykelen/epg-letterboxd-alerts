# ZiggoGo EPG Integration

## ⚠️ Important Update: Ziggo API Changes

As of January 2026, Ziggo's API endpoints appear to require authentication or have changed. The integration is getting **403 Forbidden** errors when trying to access the channel list.

## Alternative Solutions

### Option 1: Use Your Own XMLTV Feed

If you already have an XMLTV source (from your router, IPTV provider, or another EPG service), you can skip the ziggogo-epg integration entirely:

1. **Disable Ziggo EPG grabbing** in `config.json`:
```json
{
  "ziggo": {
    "enabled": false
  }
}
```

2. **Place your XMLTV file** in `data/ziggogo.xml` or configure a different path

3. **Update epg_parser.py** to read from your static XMLTV file instead of fetching

### Option 2: Alternative EPG Sources

- **M3U Playlist with EPG**: Many IPTV providers include EPG URLs
- **TVHeadend**: If you have TVHeadend, it can provide XMLTV
- **Other EPG services**: xmltv.org, SchedulesDirect, etc.

### Option 3: Wait for ziggogo-epg Library Fix

The `jbogers/ziggogo-epg` repository may be updated to handle the new API requirements. Monitor that repository for updates.

## What We Built (When It Was Working)

The integration includes all the necessary components, but they're currently blocked by the API:

- ✅ HTTP headers mimicking browser requests
- ✅ Session management with retries
- ✅ SQLite caching for efficiency
- ✅ XMLTV generation
- ❌ Access to Ziggo's API (currently blocked with 403)

## Recommended Path Forward

For now, I recommend:

1. **Find an alternative XMLTV source** for Dutch TV channels
2. **Configure the parser** to read from that source
3. **Continue with Letterboxd integration** which is working fine

The rest of your project (TMDb matching, Letterboxd CSV loading, filtering, etc.) works perfectly - you just need an EPG data source.

Would you like help:
- Setting up a static XMLTV file reader?
- Finding alternative EPG sources?
- Modifying the code to work with a different EPG format?


## What Changed

### 1. Dependencies Added
- `pytz` - Timezone handling
- `lxml` - XML processing
- `pyyaml` - Configuration file parsing

### 2. New Files Created

**classes/ziggoepggrabber.py**
- Simplified wrapper around ziggogo-epg core functionality
- Handles EPG data fetching, caching, and XMLTV generation
- Uses SQLite database for caching to minimize server requests

**classes/tvsystemio.py**  
- File-based I/O for reading channel lists and writing XMLTV files
- Supports channel filtering (only grabs EPG for channels you want)

**classes/xmltvwriter.py**
- Generates XMLTV format from database
- Produces standard XMLTV with channels, programmes, descriptions, categories

**configs/ziggo-nl.yml**
- Configuration for Ziggo Netherlands
- Contains URLs for channel list, programme segments, and details
- Timezone set to Europe/Amsterdam

**data/channels.txt**
- List of TV channels to track
- Pre-populated with popular Dutch channels (NPO, RTL, Film1, etc.)
- You can edit this to add/remove channels

### 3. Modified Files

**config.json**
```json
{
  "ziggo": {
    "enabled": true,
    "channel_file": "data/channels.txt",
    "xmltv_file": "data/ziggogo.xml",
    "database_file": "data/ziggogoepg_cache.sqlite3",
    "scan_days": 7,
    "configuration": "ziggo-nl"
  }
}
```

**epg_parser.py**
- Now uses ziggogo-epg library instead of expecting a direct URL
- Automatically fetches EPG data from Ziggo servers
- Caches data in SQLite database for efficiency

**requirements.txt**
- Added pytz, lxml, pyyaml

**.gitignore**
- Excludes *.sqlite3 and *.xml (generated EPG files)

## How It Works

1. **Channel List**: Reads `data/channels.txt` to know which channels to track
2. **Fetch EPG**: Connects to Ziggo's web API to download EPG segments
3. **Cache Data**: Stores raw data in SQLite database (`data/ziggogoepg_cache.sqlite3`)
4. **Generate XMLTV**: Converts cached data to standard XMLTV format
5. **Parse & Filter**: Extracts broadcasts, filters by language/subtitles
6. **Match Films**: Compares with Letterboxd watchlist and TMDb ratings
7. **Suggest Recordings**: Generates list of films worth recording

## Configuration

### Ziggo Settings

```json
{
  "ziggo": {
    "enabled": true,              // Enable/disable EPG fetching
    "channel_file": "data/channels.txt",  // Channel filter list
    "xmltv_file": "data/ziggogo.xml",     // Generated XMLTV output
    "database_file": "data/ziggogoepg_cache.sqlite3",  // Cache database
    "scan_days": 7,               // Number of days to fetch (1-14)
    "configuration": "ziggo-nl"   // Config file name (without .yml)
  }
}
```

### Customizing Channels

Edit `data/channels.txt`:
```txt
# Add your favorite channels
NPO 1
NPO 2
RTL 4
Film1 Premiere
# etc.
```

To see all available channels, you can run the grabber once without a channel filter and it will fetch all channels.

## Usage

### First Run (Grab Channel List)

To see all available channels:
```powershell
python -m classes.ziggoepggrabber
```

### Normal Operation

Just run the main function:
```powershell
python __init__.py
```

The EPG will be automatically fetched, cached, and parsed.

### Incremental Updates

The SQLite cache means subsequent runs are much faster:
- First run: Downloads ~7 days of EPG data (can take a few minutes)
- Later runs: Only fetches new data since last run (much faster)

It's recommended to run this **at most twice per day** to avoid overloading Ziggo's servers.

### Regenerate XMLTV from Cache

If you just want to regenerate the XMLTV file without re-fetching data:
```python
from classes.tvsystemio import ChannelFileIo
from classes.ziggoepggrabber import ZiggoGoEpgGrabber

tv_io = ChannelFileIo("data/channels.txt", "data/ziggogo.xml")
grabber = ZiggoGoEpgGrabber(tv_io, 7, "ziggo-nl", "data/ziggogoepg_cache.sqlite3")
grabber.grab(generate_only=True)  # Only regenerate, don't fetch new data
```

## Data Flow

```
Ziggo Servers → ziggogo-epg → SQLite Cache → XMLTV File → EPG Parser → Letterboxd Matcher → Recording Suggestions
```

## Cache Management

**Database**: `data/ziggogoepg_cache.sqlite3`
- Stores channels, programmes, and programme details
- Optimized with SQLite indexes
- Automatically cleaned up (old data removed)

**XMLTV File**: `data/ziggogo.xml`
- Standard XMLTV format
- Can be used with other tools (Kodi, Plex, etc.)
- Regenerated on each run

## Troubleshooting

### "Failed to fetch EPG"
- Check internet connection
- Ziggo's API may be temporarily down
- Try again later

### "No channels found"
- Edit `data/channels.txt` to add channels
- Make sure channel names match exactly (case-insensitive)
- Common names: "NPO 1", "RTL 4", "Film1 Premiere"

### "SQLite database locked"
- Another process is using the database
- Close any other instances of the script
- Delete `data/ziggogoepg_cache.sqlite3` to start fresh

### First run is slow
- Normal! Downloading 7 days of EPG for multiple channels takes time
- Subsequent runs use the cache and are much faster
- Consider reducing `scan_days` to 3-5 for faster testing

## Credits

This integration uses concepts from:
- **jbogers/ziggogo-epg**: Unofficial Ziggo EPG grabber
- Ziggo's web API endpoints (reverse-engineered from their online TV service)

## Legal Notice

This tool uses unofficial, reverse-engineered API endpoints. It is not endorsed by or affiliated with Ziggo/VodafoneZiggo. Use responsibly and in accordance with Ziggo's terms of service.
