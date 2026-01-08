"""
EPG-Letterboxd Alerts Azure Function
Main entry point for the TimerTrigger Azure Function.
"""

import json
import logging
import os
import unicodedata
from pathlib import Path
from datetime import datetime
from urllib.parse import quote
from dotenv import load_dotenv

import azure.functions as func

# Check for required Azure dependencies
try:
    from azure.storage.blob import ContainerClient
    from azure.identity import DefaultAzureCredential
except ImportError as e:
    raise ImportError(
        "Missing required Azure dependencies. Install with: pip install azure-storage-blob azure-identity"
    ) from e

# Load environment variables from .env file (for local development only)
# Skip in Azure Functions environment to avoid __main__ import error
try:
    if not os.getenv('FUNCTIONS_WORKER_RUNTIME'):
        load_dotenv()
except Exception:
    # Silently skip if load_dotenv fails (happens in Azure Functions)
    pass

from epg_parser import EPGParser
from tmdb_client import TMDbClient
from letterboxd_csv_loader import LetterboxdCSVLoader
from blob_html_writer import upload_html_to_blob

logger = logging.getLogger(__name__)


def load_config(config_path: str = "config.json") -> dict:
    """
    Load configuration from JSON file.

    Args:
        config_path: Path to config.json file

    Returns:
        Configuration dictionary
    """
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
        logger.info("Configuration loaded successfully")
        return config
    except FileNotFoundError:
        logger.error(f"Configuration file not found: {config_path}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in configuration file: {e}")
        raise


def process_broadcasts(
    epg_broadcasts: list,
    tmdb_client: TMDbClient,
    letterboxd_csv: LetterboxdCSVLoader,
    config: dict,
) -> list:
    """
    Process EPG broadcasts and generate recording suggestions.

    Args:
        epg_broadcasts: List of EPGBroadcast objects
        tmdb_client: TMDb client instance
        letterboxd_csv: Letterboxd CSV loader instance
        config: Configuration dictionary

    Returns:
        List of recording suggestions
    """
    suggestions = []
    filters = config.get("filters", {})
    min_rating = filters.get("min_rating", 0.0)
    
    total_movies = len(epg_broadcasts)

    for idx, broadcast in enumerate(epg_broadcasts, 1):
        # Format broadcast date as YYYY-MM-DD
        broadcast_date = broadcast.start_time.strftime("%Y-%m-%d")
        logger.info(f"\n{'='*80}")
        logger.info(f"Processing movie {idx}/{total_movies}: {broadcast.title} ({broadcast.channel_name}, {broadcast_date})")
        logger.info(f"{'='*80}")

        # Normalize title with TMDb (pass year from EPG if available)
        release_year = None
        if broadcast.date:
            try:
                release_year = int(broadcast.date)
            except (ValueError, TypeError):
                logger.warning(f"Could not parse year from broadcast.date: {broadcast.date}")
        
        tmdb_data = tmdb_client.normalize_title(broadcast.title, year=release_year)
        if not tmdb_data:
            logger.warning(f"No TMDb match found - will suggest based on EPG data only: {broadcast.title}")
            # Still suggest the broadcast, but with EPG data only
            tmdb_title = broadcast.title
            tmdb_year = release_year
            
            # Check Letterboxd even without TMDb match
            if tmdb_title and tmdb_year:
                if letterboxd_csv.is_on_do_not_watchlist(tmdb_title, tmdb_year):
                    logger.info(f"  Skipping '{tmdb_title}' ({tmdb_year}) - on do-not-watchlist")
                    continue
                
                on_watchlist = letterboxd_csv.is_on_watchlist(tmdb_title, tmdb_year)
                is_seen = letterboxd_csv.is_seen(tmdb_title, tmdb_year)
            else:
                on_watchlist = False
                is_seen = False
            
            rating = 0.0
            rating_source = "none"
            
            logger.info(
                f"  Letterboxd (CSV) - watchlist: {on_watchlist}, seen: {is_seen}, rating: {rating} ({rating_source})"
            )
            
            # Suggest if on watchlist or not seen (no rating filter without TMDb)
            should_record = on_watchlist or not is_seen
            
            if should_record:
                suggestion = {
                    "broadcast": broadcast,
                    "tmdb_data": None,
                    "on_watchlist": on_watchlist,
                    "is_seen": is_seen,
                    "rating": rating,
                    "rating_source": rating_source,
                    "scheduled": False,
                }
                suggestions.append(suggestion)
                logger.info(f"  ✓ Recording suggested for: {broadcast.title} (no TMDb match)")
            else:
                logger.info(f"  ✗ Skipping: {broadcast.title}")
            
            continue

        movie_id = tmdb_data.get("tmdb_id")

        # Use CSV data (local, no API) - match by title and year
        tmdb_title = tmdb_data.get("title")
        release_date = tmdb_data.get("release_date", "")
        tmdb_year = None
        if release_date:
            try:
                tmdb_year = int(release_date[:4])
            except (ValueError, TypeError):
                pass
        
        if tmdb_title and tmdb_year:
            # Check do-not-watchlist first
            if letterboxd_csv.is_on_do_not_watchlist(tmdb_title, tmdb_year):
                logger.info(f"  Skipping '{tmdb_title}' ({tmdb_year}) - on do-not-watchlist")
                continue
            
            on_watchlist = letterboxd_csv.is_on_watchlist(tmdb_title, tmdb_year)
            is_seen = letterboxd_csv.is_seen(tmdb_title, tmdb_year)
        else:
            on_watchlist = False
            is_seen = False
            
        rating = tmdb_data.get("vote_average") or 0.0
        rating_source = "tmdb"
        
        logger.info(
            f"  Letterboxd (CSV) - watchlist: {on_watchlist}, seen: {is_seen}, rating: {rating} ({rating_source})"
        )

        should_record = on_watchlist or (not is_seen and rating >= min_rating)

        if should_record:
            suggestion = {
                "broadcast": broadcast,
                "tmdb_data": tmdb_data,
                "on_watchlist": on_watchlist,
                "is_seen": is_seen,
                "rating": rating,
                "rating_source": rating_source,
                "scheduled": False,
            }

            suggestions.append(suggestion)
            logger.info(f"  ✓ Recording suggested for: {broadcast.title}")
        else:
            logger.info(f"  ✗ Skipping: {broadcast.title}")

    return suggestions


def main(mytimer: func.TimerRequest) -> None:
    """
    Main Azure Function entry point (TimerTrigger).

    Args:
        mytimer: TimerRequest object from Azure Functions runtime
    """
    try:
        utc_timestamp = datetime.utcnow().replace(microsecond=0).isoformat()
        logger.info(f"epg-letterboxd-alerts function triggered at {utc_timestamp}")

        if mytimer.past_due:
            logger.warning("Function is running late!")
    except Exception as e:
        logger.error(f"Error in function preamble: {e}", exc_info=True)
        raise

    try:
        # Load configuration
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        logger.info(f"Loading config from: {config_path}")
        logger.info(f"Current directory: {os.getcwd()}")
        logger.info(f"__file__ is: {__file__}")
        config = load_config(config_path)

        # Initialize clients
        epg_parser = EPGParser(config)
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
                logger.info(
                    f"Letterboxd CSV loaded: {stats['watchlist_count']} watchlist, "
                    f"{stats['seen_count']} seen"
                )
            else:
                logger.warning("Failed to load Letterboxd CSV data; continuing without it")

        # Fetch and parse EPG
        logger.info("Fetching EPG data...")
        xmltv_file_path = epg_parser.fetch_epg()
        broadcasts = epg_parser.parse_xmltv(xmltv_file_path)

        # Filter for movies only (Film category)
        broadcasts = epg_parser.filter_movies(broadcasts)

        # Apply language filters
        filters = config.get("filters", {})
        languages = filters.get("languages", [])
        require_subtitles = not filters.get("include_subtitles", True)
        broadcasts = epg_parser.filter_broadcasts(
            broadcasts,
            languages=languages,
            require_subtitles=require_subtitles,
        )

        logger.info(f"Filtered EPG to {len(broadcasts)} movie broadcasts")

        # TEMPORARY: Limit to first x movies for testing
        # broadcasts = broadcasts[:25]
        # logger.info(f"⚠️ TESTING MODE: Limited to first {len(broadcasts)} movies")
        
        # Store total for HTML report
        total_broadcasts_processed = len(broadcasts)
        
        # Get watched.csv timestamp for HTML report
        watched_csv_timestamp = None
        watched_csv_path = letterboxd_csv.watched_path if letterboxd_csv else "data/watched.csv"
        if watched_csv_path:
            watched_path = Path(watched_csv_path)
            if watched_path.exists():
                mtime = watched_path.stat().st_mtime
                watched_csv_timestamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

        # Process broadcasts and generate suggestions
        suggestions = process_broadcasts(
            broadcasts,
            tmdb_client,
            letterboxd_csv,
            config,
        )

        # Filter out past broadcasts and sort by start time
        now = datetime.now()
        suggestions = [s for s in suggestions if s["broadcast"].start_time > now]
        suggestions.sort(key=lambda s: s["broadcast"].start_time)

        # Build HTML content
        timestamp = now.strftime("%Y%m%d-%H%M%S")
        
        html_lines = []
        html_lines.append('<!DOCTYPE html>')
        html_lines.append('<html lang="en" data-bs-theme="dark">')
        html_lines.append('<head>')
        html_lines.append('    <meta charset="UTF-8">')
        html_lines.append('    <meta name="viewport" content="width=device-width, initial-scale=1.0">')
        html_lines.append('    <title>Ziggo Films to Record - Curated for @stereoparty</title>')
        html_lines.append('    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">')
        html_lines.append('    <style>')
        html_lines.append('        body { background-color: #0a0a0a; color: #e0e0e0; }')
        html_lines.append('        .table { --bs-table-bg: #1a1a1a; --bs-table-striped-bg: #222; }')
        html_lines.append('        .table td, .table th { border-color: #333; }')
        html_lines.append('        a { color: #4a9eff; text-decoration: none; }')
        html_lines.append('        a:hover { color: #6eb4ff; text-decoration: underline; }')
        html_lines.append('    </style>')
        html_lines.append('</head>')
        html_lines.append('<body>')
        html_lines.append('    <div class="container-fluid py-4">')
        html_lines.append(_build_film_nav_menu('index.html'))
        html_lines.append(f'        <p class="text-muted">Generated: {now.strftime("%Y-%m-%d %H:%M:%S")} | Total suggestions: {len(suggestions)}</p>')
        html_lines.append('        <div class="table-responsive">')
        html_lines.append('            <table class="table table-striped table-hover">')
        html_lines.append('                <thead>')
        html_lines.append('                    <tr>')
        html_lines.append('                        <th>Title</th>')
        html_lines.append('                        <th>Poster</th>')
        html_lines.append('                        <th>Subtitle / Description</th>')
        html_lines.append('                        <th>Rating</th>')
        html_lines.append('                        <th>LB</th>')
        html_lines.append('                        <th>Year</th>')
        html_lines.append('                        <th>Genre</th>')
        html_lines.append('                        <th>Cntry</th>')
        html_lines.append('                        <th>Director</th>')
        html_lines.append('                        <th>Actors</th>')
        html_lines.append('                        <th>Channel</th>')
        html_lines.append('                        <th>Date</th>')
        html_lines.append('                        <th>Time (CET)</th>')
        html_lines.append('                    </tr>')
        html_lines.append('                </thead>')
        html_lines.append('                <tbody>')
        
        for suggestion in suggestions:
            broadcast = suggestion["broadcast"]
            # Build title link (without subtitle)
            full_title = broadcast.title
            search_url = f"https://www.ziggogo.tv/nl/epg/initial/search/{quote(full_title)}%20"
            title_html = f'<a href="{search_url}" target="ziggogo">{broadcast.title}</a>'
            
            # Build poster image from TMDb
            poster_html = "-"
            tmdb_data = suggestion.get('tmdb_data')
            if tmdb_data and tmdb_data.get('poster_path'):
                poster_path = tmdb_data['poster_path']
                thumb_url = f"https://image.tmdb.org/t/p/w92{poster_path}"
                full_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
                title_escaped = broadcast.title.replace('"', '&quot;')
                poster_html = f'<img src="{thumb_url}" alt="{broadcast.title}" style="height: 60px; border-radius: 4px; cursor: pointer;" onclick="showPoster(\'{full_url}\', \'{title_escaped}\')">'
            
            # Combine subtitle and description
            subtitle_desc = ""
            if broadcast.subtitle and broadcast.subtitle != "-" and broadcast.description and broadcast.description != "-":
                subtitle_desc = f"{broadcast.subtitle}<br><small class='text-muted'>{broadcast.description}</small>"
            elif broadcast.subtitle and broadcast.subtitle != "-":
                subtitle_desc = broadcast.subtitle
            elif broadcast.description and broadcast.description != "-":
                subtitle_desc = f"<small class='text-muted'>{broadcast.description}</small>"
            else:
                subtitle_desc = "-"
            
            year = broadcast.date if broadcast.date else "-"
            # Get non-Film genre
            genre = ""
            for cat in broadcast.categories:
                if cat != "Film":
                    genre = cat
                    break
            # Build rating link to TMDb
            if suggestion['rating']:
                rating_text = f"{suggestion['rating']:.1f}"
                tmdb_data = suggestion.get('tmdb_data')
                if tmdb_data and tmdb_data.get('tmdb_id'):
                    tmdb_id = tmdb_data.get('tmdb_id')
                    tmdb_url = f"https://www.themoviedb.org/movie/{tmdb_id}"
                    rating = f'<a href="{tmdb_url}" target="tmdb">{rating_text}</a>'
                else:
                    rating = rating_text
            else:
                rating = "-"
            country = broadcast.country if broadcast.country else "-"
            # Build director link to Letterboxd
            if broadcast.director:
                # Normalize Unicode (remove accents) and create slug
                normalized = unicodedata.normalize('NFD', broadcast.director)
                ascii_name = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
                director_slug = ascii_name.lower().replace(" ", "-").replace(".", "").replace("'", "")
                director = f'<a href="https://letterboxd.com/director/{director_slug}/" target="letterboxd">{broadcast.director}</a>'
            else:
                director = "-"
            # Build actor links to Letterboxd
            if broadcast.actors:
                actor_links = []
                for actor in broadcast.actors[:3]:
                    # Normalize Unicode (remove accents) and create slug
                    normalized = unicodedata.normalize('NFD', actor)
                    ascii_name = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
                    actor_slug = ascii_name.lower().replace(" ", "-").replace(".", "").replace("'", "")
                    actor_links.append(f'<a href="https://letterboxd.com/actor/{actor_slug}/" target="letterboxd">{actor}</a>')
                actors = ", ".join(actor_links)
            else:
                actors = "-"
            
            # Channel with logo
            channel = broadcast.channel_name if broadcast.channel_name else "-"
            channel_icon = broadcast.channel_icon if hasattr(broadcast, 'channel_icon') else ""
            if channel_icon:
                channel_html = f'<img src="{channel_icon}" alt="{channel}" title="{channel}" style="height: 24px; vertical-align: middle;">'
            else:
                channel_html = channel
            
            bcast_date = broadcast.start_time.strftime("%Y-%m-%d")
            bcast_time = broadcast.start_time.strftime("%H:%M")
            # Build Letterboxd search link
            tmdb_data = suggestion.get('tmdb_data')
            if tmdb_data and tmdb_data.get('title'):
                tmdb_title = tmdb_data.get('title')
            else:
                tmdb_title = broadcast.title
            tmdb_year = year if year != "-" else ""
            # Escape each part individually, then join with +
            lb_search_parts = [quote(p, safe='') for p in [tmdb_title, tmdb_year] if p]
            lb_search_query = "+".join(lb_search_parts)
            lb_search_url = f"https://letterboxd.com/search/films/{lb_search_query}/?adult"
            lb_link = f'<a href="{lb_search_url}" target="letterboxd">🔍</a>'
            
            html_lines.append('                    <tr>')
            html_lines.append(f'                        <td>{title_html}</td>')
            html_lines.append(f'                        <td>{poster_html}</td>')
            html_lines.append(f'                        <td>{subtitle_desc}</td>')
            html_lines.append(f'                        <td>{rating}</td>')
            html_lines.append(f'                        <td>{lb_link}</td>')
            html_lines.append(f'                        <td>{year}</td>')
            html_lines.append(f'                        <td>{genre}</td>')
            html_lines.append(f'                        <td>{country}</td>')
            html_lines.append(f'                        <td>{director}</td>')
            html_lines.append(f'                        <td>{actors}</td>')
            html_lines.append(f'                        <td>{channel_html}</td>')
            html_lines.append(f'                        <td>{bcast_date}</td>')
            html_lines.append(f'                        <td>{bcast_time}</td>')
            html_lines.append('                    </tr>')
        
        html_lines.append('                </tbody>')
        html_lines.append('            </table>')
        html_lines.append('        </div>')
        
        # Add explanation section
        html_lines.append('        <div class="mt-4">')
        html_lines.append('            <h5>About this list</h5>')
        html_lines.append('            <p class="text-muted small">')
        html_lines.append('                This list was automatically generated for <a href="https://letterboxd.com/stereoparty/" target="_blank">letterboxd.com/stereoparty</a> using the following sources:')
        html_lines.append('            </p>')
        html_lines.append('            <ul class="text-muted small">')
        html_lines.append(f'                <li><strong>EPG Data:</strong> Ziggo GO TV Guide (processed {total_broadcasts_processed} movie broadcasts)</li>')
        html_lines.append('                <li><strong>Movie Metadata:</strong> The Movie Database (TMDb) for ratings, release years, and movie IDs</li>')
        
        # Add Letterboxd stats if available
        # Add Letterboxd stats
        try:
            stats = letterboxd_csv.get_stats()
            timestamp_text = f" on {watched_csv_timestamp}" if watched_csv_timestamp else ""
            html_lines.append(f'                <li><strong>Letterboxd Data:</strong> {stats["watchlist_count"]} watchlist items, {stats["seen_count"]} watched films, {stats["rated_count"]} rated films, {stats["do_not_watchlist_count"]} blocked films (exported from <a href="https://letterboxd.com/settings/data/" target="_blank">letterboxd.com/settings/data/</a>{timestamp_text})</li>')
        except:
            timestamp_text = f" on {watched_csv_timestamp}" if watched_csv_timestamp else ""
            html_lines.append(f'                <li><strong>Letterboxd Data:</strong> CSV export for watchlist and watched films (from <a href="https://letterboxd.com/settings/data/" target="_blank">letterboxd.com/settings/data/</a>{timestamp_text})</li>')
        
        html_lines.append('                <li>Tip for using the www.ziggogo.tv EPG search link: removed the trailing space in the search box to trigger the search</li>')
        html_lines.append('            </ul>')
        html_lines.append('        </div>')
        
        html_lines.append('    </div>')
        html_lines.append('    ')
        html_lines.append('    <!-- Poster Modal -->')
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
        html_lines.append('    ')
        html_lines.append('    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>')
        html_lines.append('    <script>')
        html_lines.append('        function showPoster(url, title) {')
        html_lines.append('            document.getElementById("posterModalImage").src = url;')
        html_lines.append('            document.getElementById("posterModalLabel").textContent = title;')
        html_lines.append('            new bootstrap.Modal(document.getElementById("posterModal")).show();')
        html_lines.append('        }')
        html_lines.append('    </script>')
        html_lines.append('</body>')
        html_lines.append('</html>')
        
        html_content = "\n".join(html_lines)
        
        # Upload to blob storage (for Azure Functions and static website hosting)
        upload_success = upload_html_to_blob(html_content, "index.html")  # Uses $web container by default
        
        # Only save local copies when running locally (not in Azure with read-only filesystem)
        is_azure = (os.environ.get('FUNCTIONS_WORKER_RUNTIME') or 
                   os.environ.get('WEBSITE_INSTANCE_ID') or 
                   os.environ.get('WEBSITE_SITE_NAME'))
        
        if not is_azure:
            # Save local copy for development/backup
            try:
                local_path = Path("wwwroot") / "index.html"
                local_path.parent.mkdir(parents=True, exist_ok=True)
                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                logger.info(f"Saved local copy to {local_path}")
            except Exception as e:
                logger.warning(f"Could not save local copy: {e}")
            
            # Save timestamped copy to data folder
            try:
                data_path = Path("data") / f"recording-suggestions-{timestamp}.html"
                data_path.parent.mkdir(parents=True, exist_ok=True)
                with open(data_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                logger.info(f"Saved timestamped copy to {data_path}")
            except Exception as e:
                logger.warning(f"Could not save timestamped copy: {e}")
        
        if upload_success:
            logger.info("Successfully uploaded index.html to blob storage")
        else:
            logger.warning("Failed to upload to blob storage (local files still available)")
        
        # Also generate grouped views
        _generate_grouped_film_views(suggestions, timestamp)
        
        # Log results to console
        logger.info(f"\nGenerated {len(suggestions)} recording suggestions")
        logger.info("\n" + "="*150)
        logger.info(f"{'Title':<35} {'Year':<6} {'Genre':<5} {'Rating':<7} {'Cntry':<5} {'Director':<18} {'Actors':<35} {'Channel':<18} {'Date':<12} {'Time (CET)':<10}")
        logger.info("="*150)
        for suggestion in suggestions:
            broadcast = suggestion["broadcast"]
            # Build title with subtitle in parentheses
            title_text = broadcast.title
            if broadcast.subtitle:
                title_text = f"{broadcast.title} ({broadcast.subtitle})"
            title = title_text[:32] + "..." if len(title_text) > 35 else title_text
            year = broadcast.date if broadcast.date else "-"
            # Get non-Film genre
            genre = ""
            for cat in broadcast.categories:
                if cat != "Film":
                    genre = cat
                    break
            rating = f"{suggestion['rating']:.1f}" if suggestion['rating'] else "-"
            country = broadcast.country if broadcast.country else "-"
            director = broadcast.director[:15] + "..." if len(broadcast.director) > 18 else broadcast.director
            actors_list = broadcast.actors[:3] if broadcast.actors else []
            actors = ", ".join(actors_list[:3]) if actors_list else "-"
            actors_display = actors[:32] + "..." if len(actors) > 35 else actors
            channel = broadcast.channel_name[:15] + "..." if len(broadcast.channel_name) > 18 else broadcast.channel_name
            bcast_date = broadcast.start_time.strftime("%Y-%m-%d")
            bcast_time = broadcast.start_time.strftime("%H:%M")
            logger.info(f"{title:<35} {year:<6} {genre:<5} {rating:<7} {country:<5} {director:<18} {actors_display:<35} {channel:<18} {bcast_date:<12} {bcast_time:<10}")
        logger.info("="*150)

        # TODO: Send notifications (Azure Notification Hubs integration)
        # TODO: Store suggestions in database (Cosmos DB integration)

        logger.info("epg-letterboxd-alerts function completed successfully")

    except Exception as e:
        logger.error(f"Function execution failed: {e}", exc_info=True)
        raise


def _generate_grouped_film_views(suggestions, timestamp):
    """Generate channel and genre grouped views for films."""
    from collections import defaultdict
    
    # Generate alphabetical view
    _generate_films_alphabetical_view(suggestions, timestamp)
    
    # Generate by-channel view
    _generate_films_by_channel_view(suggestions, timestamp)
    
    # Generate by-genre view
    _generate_films_by_genre_view(suggestions, timestamp)


def _build_film_nav_menu(active_page):
    """Build navigation menu for film pages with active page highlighted."""
    pages = [
        ('index.html', 'Chronological'),
        ('index-alphabetical.html', 'Alphabetical'),
        ('index-per-channel.html', 'By Channel'),
        ('index-per-genre.html', 'By Genre'),
        ('new-series.html', 'Series →')
    ]
    
    nav_html = []
    nav_html.append('        <nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-3">')
    nav_html.append('            <div class="container-fluid">')
    nav_html.append('                <span class="navbar-brand">Ziggo Films to Record - Curated for <a href="https://letterboxd.com/stereoparty">@stereoparty</a></span>')
    nav_html.append('                <div class="navbar-nav">')
    
    for page, label in pages:
        if page == active_page:
            nav_html.append(f'                    <span class="nav-link active">{label}</span>')
        else:
            nav_html.append(f'                    <a class="nav-link" href="{page}">{label}</a>')
    
    nav_html.append('                </div>')
    nav_html.append('            </div>')
    nav_html.append('        </nav>')
    
    return '\n'.join(nav_html)

def _build_film_table(suggestions):
    """Build HTML table for a list of film suggestions."""
    table_html = []
    table_html.append('<table class="table table-striped table-bordered align-middle">')
    table_html.append('    <thead>')
    table_html.append('        <tr>')
    table_html.append('            <th>Title</th>')
    table_html.append('            <th>Poster</th>')
    table_html.append('            <th>Subtitle/Description</th>')
    table_html.append('            <th>Rating</th>')
    table_html.append('            <th>LB</th>')
    table_html.append('            <th>Year</th>')
    table_html.append('            <th>Genre</th>')
    table_html.append('            <th>Country</th>')
    table_html.append('            <th>Director</th>')
    table_html.append('            <th>Actors</th>')
    table_html.append('            <th>Channel</th>')
    table_html.append('            <th>Date</th>')
    table_html.append('            <th>Time</th>')
    table_html.append('        </tr>')
    table_html.append('    </thead>')
    table_html.append('    <tbody>')
    for suggestion in suggestions:
        table_html.append(_build_film_table_row(suggestion))
    table_html.append('    </tbody>')
    table_html.append('</table>')
    return '\n'.join(table_html)

def _build_film_table(suggestions):
    """Build HTML table for a list of film suggestions."""
    table_html = []
    table_html.append('<table class="table table-striped table-bordered align-middle">')
    table_html.append('    <thead>')
    table_html.append('        <tr>')
    table_html.append('            <th>Title</th>')
    table_html.append('            <th>Poster</th>')
    table_html.append('            <th>Subtitle/Description</th>')
    table_html.append('            <th>Rating</th>')
    table_html.append('            <th>LB</th>')
    table_html.append('            <th>Year</th>')
    table_html.append('            <th>Genre</th>')
    table_html.append('            <th>Country</th>')
    table_html.append('            <th>Director</th>')
    table_html.append('            <th>Actors</th>')
    table_html.append('            <th>Channel</th>')
    table_html.append('            <th>Date</th>')
    table_html.append('            <th>Time</th>')
    table_html.append('        </tr>')
    table_html.append('    </thead>')
    table_html.append('    <tbody>')
    for suggestion in suggestions:
        table_html.append(_build_film_table_row(suggestion))
    table_html.append('    </tbody>')
    table_html.append('</table>')
    return '\n'.join(table_html)

def _generate_films_alphabetical_view(suggestions, timestamp):
    """Generate HTML view sorted alphabetically by title."""
    # Sort suggestions by title (case-insensitive)
    sorted_suggestions = sorted(suggestions, key=lambda s: s['broadcast'].title.lower())
    
    # Build HTML
    html_lines = []
    html_lines.append('<!DOCTYPE html>')
    html_lines.append('<html lang="en" data-bs-theme="dark">')
    html_lines.append('<head>')
    html_lines.append('    <meta charset="UTF-8">')
    html_lines.append('    <meta name="viewport" content="width=device-width, initial-scale=1.0">')
    html_lines.append('    <title>Ziggo Films to Record - Curated for @stereoparty - Alphabetical</title>')
    html_lines.append('    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">')
    html_lines.append('    <style>')
    html_lines.append('        body { background-color: #0a0a0a; color: #e0e0e0; }')
    html_lines.append('        .table { --bs-table-bg: #1a1a1a; --bs-table-striped-bg: #222; }')
    html_lines.append('        .table td, .table th { border-color: #333; }')
    html_lines.append('        a { color: #4a9eff; text-decoration: none; }')
    html_lines.append('        a:hover { color: #6eb4ff; text-decoration: underline; }')
    html_lines.append('    </style>')
    html_lines.append('</head>')
    html_lines.append('<body>')
    html_lines.append('    <div class="container-fluid py-4">')
    html_lines.append(_build_film_nav_menu('index-alphabetical.html'))
    html_lines.append(f'        <p class="text-muted">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | Total: {len(sorted_suggestions)} films</p>')
    html_lines.append('        <div class="table-responsive">')
    html_lines.append(_build_film_table(sorted_suggestions))
    html_lines.append('        </div>')
    html_lines.append('    </div>')
    html_lines.append('</body>')
    html_lines.append('</html>')
    
    html_content = '\n'.join(html_lines)

    # Write to local file
    output_path = "data/index-alphabetical.html"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    logger.info(f"Generated alphabetical film view: {output_path}")

    # Upload to blob storage
    try:
        from blob_html_writer import BlobHtmlWriter
        blob_writer = BlobHtmlWriter()
        blob_writer.write_html('index-alphabetical.html', html_content)
        logger.info("Uploaded alphabetical film view to blob storage")
    except Exception as e:
        logger.error(f"Failed to upload alphabetical film view to blob storage: {e}")

def _generate_films_by_channel_view(suggestions, timestamp):
    """Generate index-per-channel.html grouped by channel."""
    from collections import defaultdict
    
    # Group suggestions by channel
    by_channel = defaultdict(list)
    for suggestion in suggestions:
        channel = suggestion['broadcast'].channel_name
        by_channel[channel].append(suggestion)
    
    # Sort channels A-Z
    sorted_channels = sorted(by_channel.keys())
    
    # Build HTML
    html_lines = []
    html_lines.append('<!DOCTYPE html>')
    html_lines.append('<html lang="en" data-bs-theme="dark">')
    html_lines.append('<head>')
    html_lines.append('    <meta charset="UTF-8">')
    html_lines.append('    <meta name="viewport" content="width=device-width, initial-scale=1.0">')
    html_lines.append('    <title>Ziggo Films to Record - Curated for @stereoparty - By Channel</title>')
    html_lines.append('    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">')
    html_lines.append('    <style>')
    html_lines.append('        body { background-color: #0a0a0a; color: #e0e0e0; }')
    html_lines.append('        .table { --bs-table-bg: #1a1a1a; --bs-table-striped-bg: #222; }')
    html_lines.append('        .table td, .table th { border-color: #333; }')
    html_lines.append('        a { color: #4a9eff; text-decoration: none; }')
    html_lines.append('        a:hover { color: #6eb4ff; text-decoration: underline; }')
    html_lines.append('        .channel-section { margin-bottom: 3rem; }')
    html_lines.append('    </style>')
    html_lines.append('</head>')
    html_lines.append('<body>')
    html_lines.append('    <div class="container-fluid py-4">')
    html_lines.append(_build_film_nav_menu('index-per-channel.html'))
    html_lines.append(f'        <p class="text-muted">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | Total: {len(suggestions)} films across {len(sorted_channels)} channels</p>')
    
    # Generate a table for each channel
    for channel in sorted_channels:
        films = by_channel[channel]
        html_lines.append(f'        <div class="channel-section">')
        html_lines.append(f'            <h2>{channel} ({len(films)})</h2>')
        html_lines.append('            <div class="table-responsive">')
        html_lines.append(_build_film_table(films))
        html_lines.append('            </div>')
        html_lines.append('        </div>')
    
    html_lines.append('    </div>')
    html_lines.append(_build_film_poster_modal())
    html_lines.append('    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>')
    html_lines.append('    <script>')
    html_lines.append('        function showPoster(url, title) {')
    html_lines.append('            document.getElementById("posterModalImage").src = url;')
    html_lines.append('            document.getElementById("posterModalLabel").textContent = title;')
    html_lines.append('            new bootstrap.Modal(document.getElementById("posterModal")).show();')
    html_lines.append('        }')
    html_lines.append('    </script>')
    html_lines.append('</body>')
    html_lines.append('</html>')
    
    html_content = '\n'.join(html_lines)
    
    # Upload and save
    upload_html_to_blob(html_content, "index-per-channel.html")
    _save_film_local_html(html_content, "index-per-channel.html", timestamp)
    logger.info(f"Generated index-per-channel.html ({len(sorted_channels)} channels)")


def _generate_films_by_genre_view(suggestions, timestamp):
    """Generate index-per-genre.html grouped by genre."""
    from collections import defaultdict
    
    # Group suggestions by first genre
    by_genre = defaultdict(list)
    for suggestion in suggestions:
        genre = "-"
        if suggestion['broadcast'].categories:
            genre = suggestion['broadcast'].categories[0]
        by_genre[genre].append(suggestion)
    
    # Sort genres A-Z
    sorted_genres = sorted(by_genre.keys())
    
    # Build HTML
    html_lines = []
    html_lines.append('<!DOCTYPE html>')
    html_lines.append('<html lang="en" data-bs-theme="dark">')
    html_lines.append('<head>')
    html_lines.append('    <meta charset="UTF-8">')
    html_lines.append('    <meta name="viewport" content="width=device-width, initial-scale=1.0">')
    html_lines.append('    <title>Ziggo Films to Record - Curated for @stereoparty - By Genre</title>')
    html_lines.append('    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">')
    html_lines.append('    <style>')
    html_lines.append('        body { background-color: #0a0a0a; color: #e0e0e0; }')
    html_lines.append('        .table { --bs-table-bg: #1a1a1a; --bs-table-striped-bg: #222; }')
    html_lines.append('        .table td, .table th { border-color: #333; }')
    html_lines.append('        a { color: #4a9eff; text-decoration: none; }')
    html_lines.append('        a:hover { color: #6eb4ff; text-decoration: underline; }')
    html_lines.append('        .genre-section { margin-bottom: 3rem; }')
    html_lines.append('    </style>')
    html_lines.append('</head>')
    html_lines.append('<body>')
    html_lines.append('    <div class="container-fluid py-4">')
    html_lines.append(_build_film_nav_menu('index-per-genre.html'))
    html_lines.append(f'        <p class="text-muted">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | Total: {len(suggestions)} films across {len(sorted_genres)} genres</p>')
    
    # Generate a table for each genre
    for genre in sorted_genres:
        films = sorted(by_genre[genre], key=lambda s: s['broadcast'].title.lower())
        html_lines.append(f'        <div class="genre-section">')
        html_lines.append(f'            <h2>{genre} ({len(films)})</h2>')
        html_lines.append('            <div class="table-responsive">')
        html_lines.append(_build_film_table(films))
        html_lines.append('            </div>')
        html_lines.append('        </div>')
    
    html_lines.append('    </div>')
    html_lines.append(_build_film_poster_modal())
    html_lines.append('    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>')
    html_lines.append('    <script>')
    html_lines.append('        function showPoster(url, title) {')
    html_lines.append('            document.getElementById("posterModalImage").src = url;')
    html_lines.append('            document.getElementById("posterModalLabel").textContent = title;')
    html_lines.append('            new bootstrap.Modal(document.getElementById("posterModal")).show();')
    html_lines.append('        }')
    html_lines.append('    </script>')
    html_lines.append('</body>')
    html_lines.append('</html>')
    
    html_content = '\n'.join(html_lines)
    
    # Upload and save
    upload_html_to_blob(html_content, "index-per-genre.html")
    _save_film_local_html(html_content, "index-per-genre.html", timestamp)
    logger.info(f"Generated index-per-genre.html ({len(sorted_genres)} genres)")

    tmdb_title = broadcast.title
    tmdb_year = year if year != "-" else ""
    # Escape each part individually, then join with +
    lb_search_parts = [quote(p, safe='') for p in [tmdb_title, tmdb_year] if p]
    lb_search_query = "+".join(lb_search_parts)
    lb_search_url = f"https://letterboxd.com/search/films/{lb_search_query}/?adult"
    lb_link = f'<a href="{lb_search_url}" target="letterboxd">🔍</a>'
    
    # Poster image
    poster_html = "-"
    if suggestion.get('tmdb_data') and suggestion['tmdb_data'].get('poster_path'):
        poster_path = suggestion['tmdb_data']['poster_path']
        thumb_url = f"https://image.tmdb.org/t/p/w92{poster_path}"
        full_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
        title_escaped = title.replace('"', '&quot;')
        poster_html = f'<img src="{thumb_url}" alt="{title}" style="height: 60px; border-radius: 4px; cursor: pointer;" onclick="showPoster(\'{full_url}\', \'{title_escaped}\')">'
    
    # Rating with TMDb link
    rating_val = suggestion.get('rating')
    if rating_val and suggestion.get('tmdb_data'):
        tmdb_id = suggestion['tmdb_data'].get('id')
        tmdb_url = f"https://www.themoviedb.org/movie/{tmdb_id}"
        rating = f'<a href="{tmdb_url}" target="tmdb">{rating_val:.1f}</a>'
    elif rating_val:
        rating = f'{rating_val:.1f}'
    else:
        rating = "-"
    
    # Genre
    genre = broadcast.categories[0] if broadcast.categories else "-"
    
    # Country
    country = broadcast.country if broadcast.country else "-"
    
    # Director link
    if broadcast.director:
        import unicodedata
        normalized = unicodedata.normalize('NFD', broadcast.director)
        ascii_name = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
        director_slug = ascii_name.lower().replace(" ", "-").replace(".", "").replace("'", "")
        director = f'<a href="https://letterboxd.com/director/{director_slug}/" target="letterboxd">{broadcast.director}</a>'
    else:
        director = "-"
    
    # Actor links
    if broadcast.actors:
        import unicodedata
        actor_links = []
        for actor in broadcast.actors[:3]:
            normalized = unicodedata.normalize('NFD', actor)
            ascii_name = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
            actor_slug = ascii_name.lower().replace(" ", "-").replace(".", "").replace("'", "")
            actor_links.append(f'<a href="https://letterboxd.com/actor/{actor_slug}/" target="letterboxd">{actor}</a>')
        actors = ", ".join(actor_links)
    else:
        actors = "-"
    
    # Channel
    channel = broadcast.channel_name
    
    # Date and Time
    bcast_date = broadcast.start_time.strftime("%Y-%m-%d")
    bcast_time = broadcast.start_time.strftime("%H:%M")
    
    # Subtitle and description
    subtitle_desc = ""
    if broadcast.subtitle and broadcast.description:
        subtitle_desc = f"{broadcast.subtitle}<br><small class='text-muted'>{broadcast.description}</small>"
    elif broadcast.subtitle:
        subtitle_desc = broadcast.subtitle
    elif broadcast.description:
        subtitle_desc = f"<small class='text-muted'>{broadcast.description}</small>"
    else:
        subtitle_desc = "-"
    
    row_html = []
    row_html.append('                        <tr>')
    row_html.append(f'                            <td>{title_html}</td>')
    row_html.append(f'                            <td>{poster_html}</td>')
    row_html.append(f'                            <td>{subtitle_desc}</td>')
    row_html.append(f'                            <td>{rating}</td>')
    row_html.append(f'                            <td>{lb_link}</td>')
    row_html.append(f'                            <td>{year}</td>')
    row_html.append(f'                            <td>{genre}</td>')
    row_html.append(f'                            <td>{country}</td>')
    row_html.append(f'                            <td>{director}</td>')
    row_html.append(f'                            <td>{actors}</td>')
    row_html.append(f'                            <td>{channel}</td>')
    row_html.append(f'                            <td>{bcast_date}</td>')
    row_html.append(f'                            <td>{bcast_time}</td>')
    row_html.append('                        </tr>')
    
    return '\n'.join(row_html)


def _build_film_poster_modal():
    """Build the Bootstrap modal for poster viewing."""
    modal_lines = []
    modal_lines.append('    <!-- Poster Modal -->')
    modal_lines.append('    <div class="modal fade" id="posterModal" tabindex="-1">')
    modal_lines.append('        <div class="modal-dialog modal-dialog-centered">')
    modal_lines.append('            <div class="modal-content bg-dark">')
    modal_lines.append('                <div class="modal-header border-secondary">')
    modal_lines.append('                    <h5 class="modal-title" id="posterModalLabel">Poster</h5>')
    modal_lines.append('                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>')
    modal_lines.append('                </div>')
    modal_lines.append('                <div class="modal-body text-center">')
    modal_lines.append('                    <img id="posterModalImage" src="" class="img-fluid" style="max-height: 80vh;">')
    modal_lines.append('                </div>')
    modal_lines.append('            </div>')
    modal_lines.append('        </div>')
    modal_lines.append('    </div>')
    
    return '\n'.join(modal_lines)


def _save_film_local_html(html_content, filename, timestamp):
    """Save HTML file locally if not in Azure."""
    is_azure = (os.environ.get('FUNCTIONS_WORKER_RUNTIME') or 
               os.environ.get('WEBSITE_INSTANCE_ID') or 
               os.environ.get('WEBSITE_SITE_NAME'))
    
    if not is_azure:
        try:
            local_path = Path("wwwroot") / filename
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info(f"Saved local copy to {local_path}")
        except Exception as e:
            logger.warning(f"Could not save local copy: {e}")


# For local testing / development
if __name__ == "__main__":
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s'  # Simple format without logger names
    )

    class MockTimer:
        past_due = False

    main(MockTimer())
