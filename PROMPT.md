# Prompt for GitHub Copilot in VS Code

You are helping me build a Python Azure Function project called **epg-letterboxd-alerts**.  
The goal: combine Ziggo’s EPG (XMLTV) with Letterboxd film data to generate personalized “What to Record” alerts and optionally schedule recordings via TVHeadend.

## Requirements
- Language: Python 3.10+
- Framework: Azure Functions (TimerTrigger)
- Repo layout:
  - `epg_parser.py` → parse Ziggo XMLTV feed
  - `tmdb_client.py` → normalize film titles via TMDb API
  - `letterboxd_client.py` → check watchlist/seen status via Letterboxd API (OAuth)
  - `tvheadend_client.py` → schedule recordings via TVHeadend JSON API
  - `__init__.py` → main Azure Function entrypoint
- Config: `config.json` with API keys, credentials, language preferences, rating threshold
- CI/CD: GitHub Actions workflow to deploy to Azure Functions

## Functionality
1. Fetch Ziggo XMLTV EPG (use `ziggogo-epg` or similar as input).
2. Parse broadcasts, filter by language/subtitle metadata (English/Dutch).
3. Normalize titles with TMDb to get canonical IDs.
4. Enrich with Letterboxd:
   - Check if film is on my watchlist.
   - Check if film is already marked as seen.
   - Fetch community rating.
5. Decision engine:
   - If language/subtitles match AND (on watchlist OR not seen OR rating ≥ threshold) → suggest recording.
6. Output:
   - Log suggestions.
   - Optionally call TVHeadend API to schedule recording.
   - Future: push notifications (Azure Notification Hubs).

## Style
- Write clean, modular Python code.
- Include docstrings and comments.
- Use `requests` for API calls.
- Keep functions small and testable.
- Generate starter code and scaffolding — I’ll extend later.

## Deliverables
- Starter Azure Function (`__init__.py`) with TimerTrigger.
- Example implementations for `epg_parser.py`, `tmdb_client.py`, `letterboxd_client.py`, `tvheadend_client.py`.
- Sample `config.json` structure.
- `requirements.txt` with dependencies.
- GitHub Actions workflow (`deploy.yml`) for CI/CD to Azure Functions.

---
Please generate the initial code scaffolding and files based on the above requirements.