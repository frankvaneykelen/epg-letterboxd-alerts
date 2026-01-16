"""
List series available on your streaming services.
Similar to list_streaming_movies.py but for TV series instead of movies.

Combines:
- Streaming Availability API (catalog data)
- TMDb API (ratings and metadata)
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
import unicodedata
from dotenv import load_dotenv

from streaming_client import StreamingClient
from tmdb_client import TMDbClient
from letterboxd_csv_loader import LetterboxdCSVLoader
from blob_html_writer import upload_html_to_blob

# Load environment variables
try:
    if not os.getenv('FUNCTIONS_WORKER_RUNTIME'):
        load_dotenv()
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def generate_streaming_series_page():
    """Generate HTML page of series available on streaming services."""
    
    # Initialize clients
    streaming_api_key = os.getenv('STREAMING_API_KEY')
    if not streaming_api_key:
        raise ValueError("STREAMING_API_KEY not found in environment variables")
    streaming_client = StreamingClient(streaming_api_key)
    
    # Load config for TMDb
    import json
    with open("config.json") as f:
        config = json.load(f)
    
    tmdb_client = TMDbClient(config)
    letterboxd_csv = LetterboxdCSVLoader(config)
    
    # Load Letterboxd CSV data if enabled
    letterboxd_cfg = config.get("letterboxd", {})
    if letterboxd_cfg.get("enabled", False):
        # Check if auto-import is enabled
        if letterboxd_cfg.get("auto_import", False):
            logger.info("Auto-importing latest Letterboxd export from Downloads...")
            try:
                from import_letterboxd import import_latest_letterboxd_export
                if import_latest_letterboxd_export():
                    logger.info("Letterboxd data auto-imported successfully")
                else:
                    logger.warning("Auto-import failed; will use existing CSV files if available")
            except Exception as e:
                logger.warning(f"Auto-import error: {e}; will use existing CSV files")
        
        if letterboxd_csv.load_data():
            stats = letterboxd_csv.get_stats()
            logger.info(f"Letterboxd loaded: {stats['watchlist_count']} watchlist, {stats['seen_count']} seen")
        else:
            logger.warning("Failed to load Letterboxd CSV data; continuing without it")
    
    # Get min_rating from config
    min_rating = config.get('filters', {}).get('min_rating', 6.5)
    logger.info(f"Using min_rating filter: {min_rating}")
    
    # Get streaming settings from config
    streaming_config = config.get('streaming', {})
    max_pages = streaming_config.get('max_pages_series', 100)
    catalogs = streaming_config.get('catalogs', ["netflix", "disney", "prime", "hbo"])
    
    logger.info(f"Using max_pages: {max_pages} (will fetch up to {max_pages * 20} series)")
    
    logger.info("Fetching series from streaming services...")
    
    # Get recent series (current year and previous year)
    series = streaming_client.get_current_year_series(
        catalogs=catalogs,
        rating_min=70,
        max_pages=max_pages
    )
    
    logger.info(f"Found {len(series)} series")
    
    # Process each series
    suggestions = []
    for idx, series_data in enumerate(series, 1):
        show = streaming_client.parse_show_data(series_data)
        
        title = show.get('title', 'Unknown')
        year = show.get('year', '-')
        services = show.get('streaming_services', [])
        service_names = ', '.join([s.get('name', 'Unknown') for s in services[:2]])
        if len(services) > 2:
            service_names += f" +{len(services)-2} more"
        
        logger.info(f"\n{'='*80}\nProcessing {idx}/{len(series)}: {title} ({year}) - {service_names}\n{'='*80}")
        
        # Check if series has subscription-based streaming (skip rent/buy only)
        subscription_services = [s for s in services if s.get('type') == 'subscription']
        if not subscription_services:
            logger.info(f"  ✗ Skipping: only available for rent/buy, not subscription")
            continue
        
        # Skip Prime Video series that require channel subscriptions (MUBI, etc.)
        has_valid_subscription = False
        for s in subscription_services:
            if s.get('addon'):
                logger.info(f"  ✗ Skipping {s.get('name')} option: requires {s.get('addon')} channel subscription")
            else:
                has_valid_subscription = True
        
        if not has_valid_subscription:
            logger.info(f"  ✗ Skipping: all subscription options require channel addons")
            continue
        
        # Get TMDb rating (more reliable than Streaming API rating)
        tmdb_id = show.get('tmdb_id')
        tmdb_rating = 0
        origin_country = None
        
        if tmdb_id and str(tmdb_id).isdigit():
            try:
                tmdb_data = tmdb_client.get_tv_series_details(tmdb_id)
                if tmdb_data:
                    tmdb_rating = tmdb_data.get('vote_average', 0)
                    # Get origin country (ISO 3166-1 alpha-2 codes)
                    origin_countries = tmdb_data.get('origin_country', [])
                    if origin_countries:
                        origin_country = ', '.join(origin_countries[:3])  # Show up to 3 countries
                    logger.info(f"  TMDb: rating={tmdb_rating:.1f}, country={origin_country or 'N/A'}, id={tmdb_id}")
            except Exception as e:
                logger.debug(f"  Failed to fetch TMDb data for {tmdb_id}: {e}")
                tmdb_rating = 0
        else:
            logger.info(f"  TMDb: No valid ID")
        
        # Check Letterboxd status (some miniseries/limited series are tracked on Letterboxd)
        is_on_watchlist = False
        is_seen = False
        
        if letterboxd_csv and title and year:
            # Check do-not-watchlist first
            if letterboxd_csv.is_on_do_not_watchlist(title, year):
                logger.info(f"  ✗ Skipping: on do-not-watchlist")
                continue
            
            is_on_watchlist = letterboxd_csv.is_on_watchlist(title, year)
            is_seen = letterboxd_csv.is_seen(title, year)
            logger.info(f"  Letterboxd: watchlist={is_on_watchlist}, seen={is_seen}")
        
        # Filter using min_rating from config (same as EPG)
        if tmdb_rating > 0 and tmdb_rating < min_rating:
            logger.info(f"  ✗ Rejected: rating {tmdb_rating:.1f} < {min_rating}")
            continue
        
        logger.info(f"  ✓ Added to suggestions")
        
        # Add to suggestions
        suggestions.append({
            'series': show,
            'tmdb_rating': tmdb_rating,
            'origin_country': origin_country,
            'is_on_watchlist': is_on_watchlist,
            'is_seen': is_seen
        })
    
    # Sort by available_since (descending, then TMDb rating)
    def parse_date(date_str):
        if not date_str:
            return datetime.min
        try:
            # If it's a string of digits, treat as unix timestamp (seconds)
            if str(date_str).isdigit():
                return datetime.utcfromtimestamp(int(date_str))
            # Otherwise try to parse as ISO date or datetime
            return datetime.fromisoformat(date_str)
        except Exception:
            return datetime.min

    suggestions.sort(
        key=lambda x: (
            parse_date(x['series'].get('available_since')),
            x['tmdb_rating']
        ),
        reverse=True
    )
    
    # Get country mapping from API
    country_map = streaming_client.get_countries()
    
    # Generate HTML
    _generate_html(suggestions, catalogs, min_rating, country_map)
    
    logger.info(f"Generated streaming series page with {len(suggestions)} shows")


def _generate_html(suggestions, catalogs, min_rating, country_map):
    """Generate HTML output."""
    timestamp = datetime.now()
    
    html_lines = []
    html_lines.append('<!DOCTYPE html>')
    html_lines.append('<html lang="en" data-bs-theme="dark">')
    html_lines.append('<head>')
    html_lines.append('    <meta charset="UTF-8">')
    html_lines.append('    <meta name="viewport" content="width=device-width, initial-scale=1.0">')
    html_lines.append('    <title>Streaming Series - Curated for @stereoparty</title>')
    html_lines.append('    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">')
    html_lines.append('    <style>')
    html_lines.append('        body { background-color: #0a0a0a; color: #e0e0e0; }')
    html_lines.append('        .table { --bs-table-bg: #1a1a1a; --bs-table-striped-bg: #222; }')
    html_lines.append('        .table td, .table th { border-color: #333; }')
    html_lines.append('        a { color: #4a9eff; text-decoration: none; }')
    html_lines.append('        a:hover { color: #6eb4ff; text-decoration: underline; }')
    html_lines.append('        .service-logo { height: 20px; margin-right: 5px; vertical-align: middle; }')
    html_lines.append('        .badge { margin-right: 5px; }')
    html_lines.append('        #scrollToTop { position: fixed; bottom: 20px; right: 20px; background: #4a9eff; color: white; border: none; border-radius: 50%; width: 50px; height: 50px; font-size: 20px; cursor: pointer; display: none; z-index: 1000; box-shadow: 0 2px 10px rgba(0,0,0,0.3); }')
    html_lines.append('        #scrollToTop:hover { background: #6eb4ff; }')
    html_lines.append('    </style>')
    html_lines.append('</head>')
    html_lines.append('<body>')
    html_lines.append('    <div class="container-fluid py-4">')
    
    # Header
    catalog_names = {
        'netflix': 'Netflix',
        'disney': 'Disney+',
        'prime': 'Prime Video',
        'skyshowtimenl': 'SkyShowtime',
        'hbo': 'HBO Max'
    }
    services_str = ', '.join([catalog_names.get(c, c) for c in catalogs])
    
    html_lines.append('        <nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-3">')
    html_lines.append('            <div class="container-fluid">')
    html_lines.append('                <span class="navbar-brand">Streaming Series - Curated for <a href="https://letterboxd.com/stereoparty">@stereoparty</a></span>')
    html_lines.append('            </div>')
    html_lines.append('        </nav>')
    
    html_lines.append(f'        <p class="text-muted">Generated: {timestamp.strftime("%Y-%m-%d %H:%M:%S")}</p>')
    html_lines.append(f'        <p class="text-muted">Found <strong>{len(suggestions)}</strong> series streaming on <strong>{services_str}</strong> in the <strong>Netherlands</strong> with a streaming rating higher than 7 and a TMDb rating higher than {min_rating}. Sorted by availability date descending.</p>')
    
    # Table
    html_lines.append('        <div class="table-responsive">')
    html_lines.append('            <table class="table table-striped table-hover">')
    html_lines.append('                <thead>')
    html_lines.append('                    <tr>')
    html_lines.append('                        <th>Title</th>')
    html_lines.append('                        <th>Available Since</th>')
    html_lines.append('                        <th>Poster</th>')
    html_lines.append('                        <th>Description</th>')
    html_lines.append('                        <th>TMDb Rating</th>')
    html_lines.append('                        <th>Year</th>')
    html_lines.append('                        <th>Country</th>')
    html_lines.append('                        <th>Genres</th>')
    html_lines.append('                        <th>Director</th>')
    html_lines.append('                        <th>Actors</th>')
    html_lines.append('                        <th>Streaming On</th>')
    html_lines.append('                    </tr>')
    html_lines.append('                </thead>')
    html_lines.append('                <tbody>')
    
    for suggestion in suggestions: # add [:25] to limit for testing
        series = suggestion['series']
        title = series['title']
        year = series['year'] or "-"
        # Show original title in parentheses if present and different
        original_title = series.get('original_title')
        if original_title:
            title_html = f'<strong>{title}</strong> <span class="text-muted" style="font-size:0.9em;">({original_title})</span>'
        else:
            title_html = f'<strong>{title}</strong>'

        # Available Since
        available_since = series.get('available_since')
        available_since_html = '-'
        if available_since:
            try:
                # If it's a string of digits, treat as unix timestamp (seconds)
                if str(available_since).isdigit():
                    dt = datetime.utcfromtimestamp(int(available_since))
                    available_since_html = dt.strftime('%Y-%m-%d')
                else:
                    # Try to parse as ISO date or datetime
                    dt = datetime.fromisoformat(available_since)
                    available_since_html = dt.strftime('%Y-%m-%d')
            except Exception:
                available_since_html = str(available_since)
        
        # Poster
        poster_html = "-"
        poster_url = series.get('poster_url')
        if poster_url:
            title_escaped = title.replace('"', '&quot;')
            poster_html = f'<img src="{poster_url}" alt="{title}" style="height: 60px; border-radius: 4px; cursor: pointer;" onclick="showPoster(\'{poster_url}\', \'{title_escaped}\')">'
        
        # Description
        description = series.get('description', '')
        description_html = description or '-'
        
        # TMDb rating with link
        tmdb_rating = suggestion['tmdb_rating']
        tmdb_id = series.get('tmdb_id')
        if tmdb_rating > 0 and tmdb_id:
            tmdb_url = f"https://www.themoviedb.org/tv/{tmdb_id}"
            rating_html = f'<a href="{tmdb_url}" target="tmdb">{tmdb_rating:.1f}</a>'
        else:
            rating_html = "-"
        
        # Genres
        genres = ", ".join(series['genres'][:3]) if series['genres'] else "-"
        
        # Director with Letterboxd link
        director = series.get('director', '-')
        if director and director != '-':
            normalized = unicodedata.normalize('NFD', director)
            ascii_name = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
            director_slug = ascii_name.lower().replace(" ", "-").replace(".", "").replace("'", "")
            director_html = f'<a href="https://letterboxd.com/director/{director_slug}/" target="letterboxd">{director}</a>'
        else:
            director_html = "-"
        
        # Actors
        actors = series.get('actors', [])
        actors_html = ", ".join(actors[:3]) if actors else "-"
        if len(actors) > 3:
            actors_html += f" +{len(actors)-3} more"
        
        # Streaming services with links and logos
        services = series.get('streaming_services', [])
        service_html_parts = []
        
        # Map of catalog IDs to service names for filtering
        catalog_service_map = {
            'netflix': 'Netflix',
            'disney': 'Disney+',
            'prime': 'Prime Video',
            'hbo': 'HBO Max',
            'skyshowtimenl': 'SkyShowtime'
        }
        allowed_services = set(catalog_service_map.get(c, c) for c in catalogs)
        
        # Show streaming service logos (dark theme) if available
        seen_services = set()
        for service in services:
            service_name = service.get('name', 'Unknown')
            service_type = service.get('type', 'subscription')
            # Skip rent/buy options
            if service_type in ['rent', 'buy']:
                continue
            # Skip services that require channel addons (MUBI, etc.)
            if service.get('addon'):
                continue
            # Skip services not in configured catalogs
            if service_name not in allowed_services:
                continue
            # Skip duplicates
            if service_name in seen_services:
                continue
            seen_services.add(service_name)
            service_link = service.get('link')
            # Try to get logo from imageSet (darkThemeImage preferred, fallback to lightThemeImage)
            logo_url = None
            if 'imageSet' in service and isinstance(service['imageSet'], dict):
                logo_url = service['imageSet'].get('darkThemeImage') or service['imageSet'].get('lightThemeImage')
            # Fallback: try to get from raw_data if not present
            if not logo_url and 'raw_data' in series:
                # Try to find the matching service in raw_data
                for raw_option in series['raw_data'].get('streamingOptions', {}).get('nl', []):
                    raw_service = raw_option.get('service', {})
                    if raw_service.get('name') == service_name:
                        if 'imageSet' in raw_service and isinstance(raw_service['imageSet'], dict):
                            logo_url = raw_service['imageSet'].get('darkThemeImage') or raw_service['imageSet'].get('lightThemeImage')
                        break
            if logo_url:
                img_tag = f'<img src="{logo_url}" alt="{service_name}" class="service-logo" title="{service_name}">' 
            else:
                img_tag = service_name
            if service_link:
                service_html_parts.append(f'<a href="{service_link}" target="_blank">{img_tag}</a>')
            else:
                service_html_parts.append(img_tag)
        services_html = "<br>".join(service_html_parts) if service_html_parts else "-"
        
        # Country (convert code to name using API country mapping)
        country_code = suggestion.get('origin_country') or '-'
        # If multiple codes, join names
        if country_code and country_code != '-':
            codes = [c.strip() for c in country_code.split(',')]
            country = ', '.join([country_map.get(c, c) for c in codes])
        else:
            country = '-'
        
        html_lines.append('                    <tr>')
        html_lines.append(f'                        <td>{title_html}</td>')
        html_lines.append(f'                        <td>{available_since_html}</td>')
        html_lines.append(f'                        <td>{poster_html}</td>')
        html_lines.append(f'                        <td style="max-width: 300px; font-size: 0.9em;">{description_html}</td>')
        html_lines.append(f'                        <td>{rating_html}</td>')
        html_lines.append(f'                        <td>{year}</td>')
        html_lines.append(f'                        <td>{country}</td>')
        html_lines.append(f'                        <td>{genres}</td>')
        html_lines.append(f'                        <td>{director_html}</td>')
        html_lines.append(f'                        <td style="max-width: 200px; font-size: 0.9em;">{actors_html}</td>')
        html_lines.append(f'                        <td>{services_html}</td>')
        html_lines.append('                    </tr>')
    
    html_lines.append('                </tbody>')
    html_lines.append('            </table>')
    html_lines.append('        </div>')
    html_lines.append('    </div>')
    
    # Poster modal
    html_lines.append('    <div class="modal fade" id="posterModal" tabindex="-1">')
    html_lines.append('        <div class="modal-dialog modal-dialog-centered">')
    html_lines.append('            <div class="modal-content bg-dark">')
    html_lines.append('                <div class="modal-header border-secondary">')
    html_lines.append('                    <h5 class="modal-title" id="posterModalLabel">Poster</h5>')
    html_lines.append('                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>')
    html_lines.append('                </div>')
    html_lines.append('                <div class="modal-body text-center">')
    html_lines.append('                    <img id="posterModalImage" src="" class="img-fluid" style="max-height: 80vh;">')
    html_lines.append('                </div>')
    html_lines.append('            </div>')
    html_lines.append('        </div>')
    html_lines.append('    </div>')
    
    # Scripts
    html_lines.append('    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>')
    html_lines.append('    <script>')
    html_lines.append('        function showPoster(url, title) {')
    html_lines.append('            document.getElementById("posterModalImage").src = url;')
    html_lines.append('            document.getElementById("posterModalLabel").textContent = title;')
    html_lines.append('            new bootstrap.Modal(document.getElementById("posterModal")).show();')
    html_lines.append('        }')
    html_lines.append('        window.onscroll = function() {')
    html_lines.append('            const btn = document.getElementById("scrollToTop");')
    html_lines.append('            if (document.body.scrollTop > 300 || document.documentElement.scrollTop > 300) {')
    html_lines.append('                btn.style.display = "block";')
    html_lines.append('            } else {')
    html_lines.append('                btn.style.display = "none";')
    html_lines.append('            }')
    html_lines.append('        };')
    html_lines.append('    </script>')
    html_lines.append('    <button id="scrollToTop" onclick="window.scrollTo({top: 0, behavior: \'smooth\'})">↑</button>')
    html_lines.append('</body>')
    html_lines.append('</html>')
    
    html_content = '\n'.join(html_lines)
    
    # Upload to blob storage (for Azure Functions and static website hosting)
    upload_html_to_blob(html_content, "streaming-series.html")
    
    # Only save local copy when running locally (not in Azure with read-only filesystem)
    is_azure = (os.environ.get('FUNCTIONS_WORKER_RUNTIME') or 
               os.environ.get('WEBSITE_INSTANCE_ID') or 
               os.environ.get('WEBSITE_SITE_NAME'))
    
    if not is_azure:
        try:
            local_path = Path("wwwroot") / "streaming-series.html"
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info(f"Saved local copy to {local_path}")
        except Exception as e:
            logger.warning(f"Could not save local copy: {e}")


if __name__ == "__main__":
    generate_streaming_series_page()
