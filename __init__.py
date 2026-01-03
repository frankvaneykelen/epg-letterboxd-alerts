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

# Load environment variables from .env file (for local development)
load_dotenv()

from epg_parser import EPGParser
from tmdb_client import TMDbClient
from letterboxd_client import LetterboxdClient
from letterboxd_csv_loader import LetterboxdCSVLoader
from tvheadend_client import TVHeadendClient

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
    letterboxd_client: LetterboxdClient,
    letterboxd_csv: LetterboxdCSVLoader,
    tvheadend_client: TVHeadendClient,
    config: dict,
) -> list:
    """
    Process EPG broadcasts and generate recording suggestions.

    Args:
        epg_broadcasts: List of EPGBroadcast objects
        tmdb_client: TMDb client instance
        letterboxd_client: Letterboxd client instance
        tvheadend_client: TVHeadend client instance
        config: Configuration dictionary

    Returns:
        List of recording suggestions
    """
    suggestions = []
    filters = config.get("filters", {})
    min_rating = filters.get("min_rating", 0.0)
    letterboxd_cfg = config.get("letterboxd", {})
    letterboxd_enabled = letterboxd_cfg.get("enabled", False)
    
    total_movies = len(epg_broadcasts)

    for idx, broadcast in enumerate(epg_broadcasts, 1):
        # Format broadcast date as YYYY-MM-DD
        broadcast_date = broadcast.start_time.strftime("%Y-%m-%d")
        logger.info(f"\n{'='*80}")
        logger.info(f"Processing movie {idx}/{total_movies}: {broadcast.title} ({broadcast.channel_name}, {broadcast_date})")
        logger.info(f"{'='*80}")

        # Normalize title with TMDb
        tmdb_data = tmdb_client.normalize_title(broadcast.title)
        if not tmdb_data:
            logger.warning(f"Could not normalize title: {broadcast.title}")
            continue

        movie_id = tmdb_data.get("tmdb_id")

        if letterboxd_enabled:
            letterboxd_mode = letterboxd_cfg.get("mode", "csv")
            
            if letterboxd_mode == "csv":
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
                    user_rating = letterboxd_csv.get_user_rating(tmdb_title, tmdb_year)
                else:
                    on_watchlist = False
                    is_seen = False
                    user_rating = None
                    
                rating = user_rating or tmdb_data.get("vote_average") or 0.0
                rating_source = "letterboxd_csv" if user_rating else "tmdb"
                
                logger.info(
                    f"  Letterboxd (CSV) - watchlist: {on_watchlist}, seen: {is_seen}, rating: {rating} ({rating_source})"
                )
            else:
                # Use API (requires OAuth token)
                on_watchlist = letterboxd_client.is_on_watchlist(str(movie_id))
                is_seen = letterboxd_client.is_seen(str(movie_id))
                rating = letterboxd_client.get_community_rating(str(movie_id)) or 0.0
                rating_source = "letterboxd_api"
                
                logger.info(
                    f"  Letterboxd (API) - watchlist: {on_watchlist}, seen: {is_seen}, rating: {rating}"
                )

            should_record = (
                on_watchlist or not is_seen or rating >= min_rating
            )
        else:
            # Letterboxd disabled: use TMDb vote_average as rating fallback
            # BUT still check watched.csv to avoid recommending already-watched movies
            tmdb_title = tmdb_data.get("title")
            release_date = tmdb_data.get("release_date", "")
            tmdb_year = None
            if release_date:
                try:
                    tmdb_year = int(release_date[:4])
                except (ValueError, TypeError):
                    pass
            
            on_watchlist = False
            is_seen = False
            if tmdb_title and tmdb_year:
                # Check do-not-watchlist first
                if letterboxd_csv.is_on_do_not_watchlist(tmdb_title, tmdb_year):
                    logger.info(f"  Skipping '{tmdb_title}' ({tmdb_year}) - on do-not-watchlist")
                    continue
                
                is_seen = letterboxd_csv.is_seen(tmdb_title, tmdb_year)
                logger.info(f"  Checking watched: title='{tmdb_title}', year={tmdb_year}, seen={is_seen}")
            
            rating = tmdb_data.get("vote_average") or 0.0
            rating_source = "tmdb"

            logger.info(
                f"  Letterboxd disabled; using TMDb rating: {rating}, seen: {is_seen}"
            )

            should_record = not is_seen and rating >= min_rating

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

            # Attempt to schedule recording if TVHeadend is enabled
            if tvheadend_client.enabled:
                # This is a placeholder; real implementation would map channel to TVHeadend UUID
                channel_uuid = broadcast.channel  # In practice, need channel mapping
                scheduled = tvheadend_client.schedule_recording(
                    channel_uuid=channel_uuid,
                    title=broadcast.title,
                    start_time=broadcast.start_time,
                    end_time=broadcast.end_time,
                    metadata={"description": broadcast.description},
                )
                suggestion["scheduled"] = scheduled

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
    utc_timestamp = datetime.utcnow().replace(microsecond=0).isoformat()
    logger.info(f"epg-letterboxd-alerts function triggered at {utc_timestamp}")

    if mytimer.past_due:
        logger.warning("Function is running late!")

    try:
        # Load configuration
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        config = load_config(config_path)

        # Initialize clients
        epg_parser = EPGParser(config)
        tmdb_client = TMDbClient(config)
        letterboxd_client = LetterboxdClient(config)
        letterboxd_csv = LetterboxdCSVLoader(config)
        tvheadend_client = TVHeadendClient(config)
        
        # Load Letterboxd CSV data if enabled and in CSV mode
        letterboxd_cfg = config.get("letterboxd", {})
        if letterboxd_cfg.get("enabled", False) and letterboxd_cfg.get("mode") == "csv":
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
                    f"{stats['seen_count']} seen, {stats['rated_count']} rated"
                )
            else:
                logger.warning("Failed to load Letterboxd CSV data; continuing without it")

        # Test TVHeadend connection if enabled
        if tvheadend_client.enabled:
            if not tvheadend_client.test_connection():
                logger.warning("TVHeadend connection failed; recording will be disabled")
                tvheadend_client.enabled = False

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

        # # TEMPORARY: Limit to first x movies for testing
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
                watched_csv_timestamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")

        # Process broadcasts and generate suggestions
        suggestions = process_broadcasts(
            broadcasts,
            tmdb_client,
            letterboxd_client,
            letterboxd_csv,
            tvheadend_client,
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
        html_lines.append('    <title>Recording Suggestions</title>')
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
        html_lines.append('        <h1 class="mb-3">Recording Suggestions</h1>')
        html_lines.append(f'        <p class="text-muted">Generated: {now.strftime("%Y-%m-%d %H:%M:%S")} | Total suggestions: {len(suggestions)}</p>')
        html_lines.append('        <div class="table-responsive">')
        html_lines.append('            <table class="table table-striped table-hover">')
        html_lines.append('                <thead>')
        html_lines.append('                    <tr>')
        html_lines.append('                        <th>Title</th>')
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
            # Build title with subtitle in parentheses
            title_text = broadcast.title
            if broadcast.subtitle:
                title_text = f"{broadcast.title} ({broadcast.subtitle})"
            full_title = broadcast.title
            search_url = f"https://www.ziggogo.tv/nl/epg/initial/search/{quote(full_title)}%20"
            description = broadcast.description if broadcast.description else ""
            # Escape for HTML
            description_escaped = description.replace('"', '&quot;').replace("'", '&#39;')
            title_html = f'<a href="{search_url}" target="ziggogo" title="{description_escaped}">{title_text}</a>'
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
                tmdb_data = suggestion.get('tmdb_data', {})
                tmdb_id = tmdb_data.get('tmdb_id')
                if tmdb_id:
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
            channel = broadcast.channel_name if broadcast.channel_name else "-"
            bcast_date = broadcast.start_time.strftime("%Y-%m-%d")
            bcast_time = broadcast.start_time.strftime("%H:%M")
            # Build Letterboxd search link
            tmdb_data = suggestion.get('tmdb_data', {})
            tmdb_title = tmdb_data.get('title', broadcast.title)
            tmdb_year = year if year != "-" else ""
            # Escape each part individually, then join with +
            lb_search_parts = [quote(p, safe='') for p in [tmdb_title, tmdb_year] if p]
            lb_search_query = "+".join(lb_search_parts)
            lb_search_url = f"https://letterboxd.com/search/films/{lb_search_query}/?adult"
            lb_link = f'<a href="{lb_search_url}" target="letterboxd">🔍</a>'
            
            html_lines.append('                    <tr>')
            html_lines.append(f'                        <td>{title_html}</td>')
            html_lines.append(f'                        <td>{rating}</td>')
            html_lines.append(f'                        <td>{lb_link}</td>')
            html_lines.append(f'                        <td>{year}</td>')
            html_lines.append(f'                        <td>{genre}</td>')
            html_lines.append(f'                        <td>{country}</td>')
            html_lines.append(f'                        <td>{director}</td>')
            html_lines.append(f'                        <td>{actors}</td>')
            html_lines.append(f'                        <td>{channel}</td>')
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
        if letterboxd_cfg.get("enabled", False) and letterboxd_csv:
            try:
                stats = letterboxd_csv.get_stats()
                timestamp_text = f" on {watched_csv_timestamp}" if watched_csv_timestamp else ""
                html_lines.append(f'                <li><strong>Letterboxd Data:</strong> {stats["watchlist_count"]} watchlist items, {stats["seen_count"]} watched films, {stats["rated_count"]} rated films (exported from <a href="https://letterboxd.com/settings/data/" target="_blank">letterboxd.com/settings/data/</a>{timestamp_text})</li>')
            except:
                timestamp_text = f" on {watched_csv_timestamp}" if watched_csv_timestamp else ""
                html_lines.append(f'                <li><strong>Letterboxd Data:</strong> CSV export for watchlist and watched films (from <a href="https://letterboxd.com/settings/data/" target="_blank">letterboxd.com/settings/data/</a>{timestamp_text})</li>')
        else:
            # Get stats even when Letterboxd is disabled
            try:
                stats = letterboxd_csv.get_stats()
                watched_count = stats.get("seen_count", 0)
                do_not_count = stats.get("do_not_watchlist_count", 0)
                timestamp_text = f" on {watched_csv_timestamp}" if watched_csv_timestamp else ""
                html_lines.append(f'                <li><strong>Filtering:</strong> Excludes films from <strong>watched.csv</strong> ({watched_count} already-watched movies) and <strong>do-not-watchlist.csv</strong> ({do_not_count} movies). Data exported from <a href="https://letterboxd.com/settings/data/" target="_blank">letterboxd.com/settings/data/</a>{timestamp_text}</li>')
            except:
                timestamp_text = f" on {watched_csv_timestamp}" if watched_csv_timestamp else ""
                html_lines.append(f'                <li><strong>Filtering:</strong> Excludes already-watched films from watched.csv and do-not-watchlist.csv. Data exported from <a href="https://letterboxd.com/settings/data/" target="_blank">letterboxd.com/settings/data/</a>{timestamp_text}</li>')
        
        html_lines.append('            </ul>')
        html_lines.append('        </div>')
        
        html_lines.append('    </div>')
        html_lines.append('    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>')
        html_lines.append('</body>')
        html_lines.append('</html>')
        
        # Save to HTML file
        filename = f"recording-suggestions-{timestamp}.html"
        filepath = Path("data") / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(html_lines))
        
        logger.info(f"\nSaved recording suggestions to {filepath}")
        
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
