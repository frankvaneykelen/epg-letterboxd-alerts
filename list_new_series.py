"""
List all non-Film programmes from ziggogo.xml
Filters for first episodes (episode-num 1.0.) to find new series
Shows episode-num, categories, title, and date
Saves output to HTML file in data folder
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from urllib.parse import quote
import logging
import os
import requests
import yaml
import unicodedata
from dotenv import load_dotenv
import fetch_epg
from blob_config_loader import download_config_file
from blob_html_writer import upload_html_to_blob
from do_not_watch_series_loader import DoNotWatchSeriesLoader
from skip_categories_loader import SkipCategoriesLoader

# Load environment variables from .env file (only for local development)
try:
    load_dotenv()
except ModuleNotFoundError:
    # Azure Functions environment doesn't support __main__ import
    pass

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def search_tv_series(title: str, year: int = None, api_key: str = None, country: str = None, director: str = None, actors: list = None):
    """Search TMDb for TV series with metadata verification."""
    if not api_key:
        return None
    
    try:
        params = {
            "api_key": api_key,
            "query": title,
        }
        if year:
            params["first_air_date_year"] = year
        
        url = "https://api.themoviedb.org/3/search/tv"
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        results = response.json().get("results", [])
        
        if not results:
            return None
        
        # Log search results for debugging
        logger.info(f"TMDb search for '{title}' ({year}): found {len(results)} results")
        for i, result in enumerate(results[:3]):  # Log first 3 results
            result_year = result.get('first_air_date', '')[:4] if result.get('first_air_date') else 'N/A'
            logger.info(f"  [{i+1}] {result.get('name')} ({result_year}) - ID: {result.get('id')}")
        
        # Try to find best match
        best_match = None
        best_score = 0
        
        for result in results[:5]:  # Check top 5 results
            score = 0
            result_year = result.get('first_air_date', '')[:4]
            
            # Year match (exact or ±1 year)
            if year and result_year:
                try:
                    result_year_int = int(result_year)
                    if result_year_int == year:
                        score += 10  # Exact year match
                    elif abs(result_year_int - year) == 1:
                        score += 5  # Close year match
                except ValueError:
                    pass
            
            # Recency bonus (prefer newer shows when scores are tied)
            if result_year:
                try:
                    result_year_int = int(result_year)
                    if result_year_int >= 2020:
                        score += (result_year_int - 2020) * 0.2
                except ValueError:
                    pass
            
            # Country match
            if country and result.get('origin_country'):
                origin_countries = result.get('origin_country', [])
                if country in origin_countries:
                    score += 5
                    logger.info(f"  Country match for '{result.get('name')}': {country} in {origin_countries}")
            
            # Title similarity (exact match gets bonus)
            if result.get('name', '').lower() == title.lower():
                score += 3
            
            # First result gets slight preference
            if result == results[0]:
                score += 1
            
            logger.debug(f"  Score for '{result.get('name')}' ({result_year}): {score}")
            
            if score > best_score:
                best_score = score
                best_match = result
        
        if best_match:
            logger.info(f"  Selected: {best_match.get('name')} ({best_match.get('first_air_date', '')[:4]}) with score {best_score}")
        
        return best_match
    except Exception as e:
        logger.error(f"TMDb TV search failed for '{title}': {e}")
        return None

def list_non_films():
    """Parse ziggogo.xml and list all programmes without Film category."""
    
    logger.info("Starting series EPG processing...")
    
    # Load do-not-watch series list
    do_not_watch_loader = DoNotWatchSeriesLoader()
    do_not_watch_loader.load_data()
    logger.info(f"Loaded {do_not_watch_loader.get_count()} series to do-not-watch list")
    
    # Load skip categories
    skip_categories_loader = SkipCategoriesLoader(
        storage_account_name="ziggoepgletterboxd"
    )
    skip_categories_loader.load_data()
    logger.info(f"Loaded {len(skip_categories_loader.get_categories())} skip categories")
    
    # Determine paths based on environment
    is_azure = (os.environ.get('FUNCTIONS_WORKER_RUNTIME') or 
               os.environ.get('WEBSITE_INSTANCE_ID') or 
               os.environ.get('WEBSITE_SITE_NAME'))
    
    if is_azure:
        xml_output_path = "/tmp/ziggogo-series.xml"
    else:
        xml_output_path = "data/ziggogo-series.xml"
    
    # Fetch/update EPG data from Ziggo first
    try:
        logger.info("Fetching series EPG data from Ziggo...")
        fetch_epg.fetch_epg(
            channel_file="data/channels-series.txt",
            output_file=xml_output_path,
            scan_days=7  # 7 days for series (fewer programmes to fetch)
        )
        logger.info("Series EPG fetch completed successfully")
    except Exception as e:
        logger.error(f"EPG update failed: {e}", exc_info=True)
        logger.warning("Continuing with existing data...")
    
    # Load config for TMDb API key
    config_path = Path("config.json")
    api_key = None
    allowed_countries = None
    if config_path.exists():
        import json
        with open(config_path) as f:
            config = json.load(f)
            api_key = os.getenv("TMDB_API_KEY") or config.get("tmdb", {}).get("api_key")
            # Load country filter from config
            allowed_countries = config.get("filters", {}).get("countries", None)
            if allowed_countries:
                logger.info(f"Country filter enabled: {allowed_countries}")
    else:
        api_key = os.getenv("TMDB_API_KEY")
    
    xml_path = Path(xml_output_path)
    if not xml_path.exists():
        logger.error(f"Error: {xml_path} not found - cannot process series")
        return
    
    # Load channel filter from channels-series.txt (try blob storage first)
    channels_file = Path("data/channels-series.txt")
    channels_file_path = download_config_file("channels-series.txt", str(channels_file))
    allowed_channels = set()
    if Path(channels_file_path).exists():
        with open(channels_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if line and not line.startswith('#'):
                    allowed_channels.add(line)
        print(f"Loaded {len(allowed_channels)} channels from {channels_file_path}")
    else:
        print(f"Warning: {channels_file_path} not found, processing all channels")
    
    print("Parsing XML file...")
    tree = ET.parse(xml_path)
    root = tree.getroot()
    
    # Build channel ID to name and icon mapping
    channel_map = {}
    icon_map = {}
    for channel in root.findall("channel"):
        channel_id = channel.get("id", "")
        display_name = channel.find("display-name")
        if display_name is not None and display_name.text:
            channel_map[channel_id] = display_name.text
        icon_elem = channel.find("icon")
        if icon_elem is not None:
            icon_map[channel_id] = icon_elem.get("src", "")
    
    # Collect all non-film programmes
    programmes = []
    seen_titles = set()
    
    # Get total count for progress display
    all_programmes = root.findall('programme')
    total_count = len(all_programmes)
    
    for idx, programme in enumerate(all_programmes, 1):
        # Get channel name first to filter early
        channel_id = programme.get('channel', "")
        channel = channel_map.get(channel_id, channel_id if channel_id else "-")
        
        # Filter by allowed channels early (if channel filter is loaded)
        if allowed_channels and channel not in allowed_channels:
            continue
        
        # Get categories
        categories = [cat.text for cat in programme.findall('category') if cat.text]
        
        # Skip if Film is in categories
        if "Film" in categories:
            continue
        
        # Skip unwanted categories
        if skip_categories_loader.should_skip(categories):
            continue
        
        # Get title
        title_elem = programme.find('title')
        title = title_elem.text if title_elem is not None and title_elem.text else "-"
        
        # Check do-not-watch list first
        if do_not_watch_loader.is_on_do_not_watch_list(title):
            logger.info(f"  Skipping '{title}' - on do-not-watch list")
            continue
        
        print(f"\r[{idx:02d}/{total_count}] {title[:50]:<50}", end='', flush=True)
        
        # Get sub-title
        subtitle_elem = programme.find('sub-title')
        subtitle = subtitle_elem.text if subtitle_elem is not None and subtitle_elem.text else "-"
        
        # Get description
        desc_elem = programme.find('desc[@lang="nl"]', {'': ''})
        if desc_elem is None:
            desc_elem = programme.find('desc')
        description = desc_elem.text if desc_elem is not None and desc_elem.text else "-"
        
        # Skip duplicates based on title
        if title in seen_titles:
            continue
        seen_titles.add(title)
        
        # Get date
        date_elem = programme.find('date')
        date = date_elem.text if date_elem is not None and date_elem.text else "-"
        
        # Only include current year (2026) and previous year (2025)
        current_year = datetime.now().year
        if date != "-":
            try:
                year = int(date)
                if year not in [current_year, current_year - 1]:
                    continue
            except ValueError:
                continue  # Skip if date is not a valid year
        
        # Get episode-num
        episode_elem = programme.find('episode-num')
        episode = episode_elem.text if episode_elem is not None and episode_elem.text else "-"
        
        # Only include first episodes (various patterns indicating season 1, episode 1)
        # xmltv_ns format is season.episode.part (0-indexed)
        first_episode_patterns = ["0.0.", "0.1.", "1.0.", "1.1."]
        if episode not in first_episode_patterns:
            continue
        
        # Get director
        credits_elem = programme.find('credits')
        director = "-"
        if credits_elem is not None:
            director_elem = credits_elem.find('director')
            if director_elem is not None and director_elem.text:
                director = director_elem.text
        
        # Get actors
        actors = []
        if credits_elem is not None:
            actor_elems = credits_elem.findall('actor')
            actors = [a.text for a in actor_elems if a.text][:3]  # Limit to 3
        
        # Get country
        country_elem = programme.find('country')
        country = country_elem.text if country_elem is not None and country_elem.text else "-"
        
        # Filter by allowed countries (if configured)
        # Note: Series without country data (country == "-") are always included to avoid
        # filtering out older EPG data that may not have country information
        if allowed_countries and country != "-":
            if country not in allowed_countries:
                logger.debug(f"  Skipping '{title}' - country '{country}' not in allowed list {allowed_countries}")
                continue
        
        # Get start time
        start_str = programme.get('start', '')
        start_time = None
        if start_str:
            try:
                # Format: 20260103200000 +0100
                start_time = datetime.strptime(start_str[:14], "%Y%m%d%H%M%S")
            except Exception:
                pass
        
        # Format categories
        cat_str = ", ".join(categories) if categories else "-"
        
        # Try to find TMDb data
        tmdb_data = None
        rating = "-"
        if api_key and date != "-":
            try:
                year = int(date)
                # Pass additional metadata for better matching
                tmdb_data = search_tv_series(title, year, api_key, country, director, actors)
                if not tmdb_data:
                    # Try without year
                    tmdb_data = search_tv_series(title, None, api_key, country, director, actors)
                
                if tmdb_data:
                    vote_avg = tmdb_data.get("vote_average", 0)
                    if vote_avg:
                        rating = f"{vote_avg:.1f}"
            except (ValueError, Exception) as e:
                logger.debug(f"TMDb lookup failed for {title}: {e}")
        
        programmes.append({
            'title': title,
            'subtitle': subtitle,
            'description': description,
            'episode': episode,
            'date': date,
            'categories': cat_str,
            'rating': rating,
            'tmdb_data': tmdb_data,
            'director': director,
            'actors': actors,
            'country': country,
            'channel': channel,
            'channel_id': channel_id,
            'start_time': start_time
        })
    
    # Sort by start_time (date ascending)
    # Use a far-future date for items without start_time to sort them last
    programmes.sort(key=lambda x: x['start_time'] or datetime(9999, 12, 31))
    non_film_count = len(programmes)
    
    # TEMPORARY: Limit to first x movies for testing
    # programmes = programmes[:25]
    # logger.info(f"⚠️ TESTING MODE: Limited to first {len(programmes)} series")
        
    print()  # New line after progress
    print(f"Found {non_film_count} new series across {len(set(p['channel'] for p in programmes))} channels")
    
    # Generate HTML
    html_lines = []
    html_lines.append('<!DOCTYPE html>')
    html_lines.append('<html lang="en" data-bs-theme="dark">')
    html_lines.append('<head>')
    html_lines.append('    <meta charset="UTF-8">')
    html_lines.append('    <meta name="viewport" content="width=device-width, initial-scale=1.0">')
    html_lines.append('    <title>Series Premieres - Curated for @stereoparty</title>')
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
    html_lines.append(_build_nav_menu('new-series.html'))
    html_lines.append(f'        <p class="text-muted">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | Total new series: {non_film_count}</p>')
    html_lines.append('        <p class="text-muted">Showing only first episodes (0.0., 0.1., 1.0., 1.1.) from non-Film programmes</p>')
    html_lines.append('        <div class="table-responsive">')
    html_lines.append('            <table class="table table-striped table-hover">')
    html_lines.append('                <thead>')
    html_lines.append('                    <tr>')
    html_lines.append('                        <th>Title</th>')
    html_lines.append('                        <th>Poster</th>')
    html_lines.append('                        <th>Subtitle / Description</th>')
    html_lines.append('                        <th>Episode</th>')
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
    
    for prog in programmes:
        search_url = f"https://www.ziggogo.tv/nl/epg/initial/search/{quote(prog['title'])}%20"
        
        # Build Letterboxd search link
        lb_search_parts = [quote(p, safe='') for p in [prog['title'], prog['date']] if p and p != "-"]
        lb_search_query = "+".join(lb_search_parts)
        lb_search_url = f"https://letterboxd.com/search/films/{lb_search_query}/?adult"
        lb_link = f'<a href="{lb_search_url}" target="letterboxd">🔍</a>'
        
        # Build title link
        title_html = f'<a href="{search_url}" target="ziggogo">{prog["title"]}</a>'
        
        # Build poster image from TMDb
        poster_html = "-"
        if prog['tmdb_data'] and prog['tmdb_data'].get('poster_path'):
            poster_path = prog['tmdb_data']['poster_path']
            thumb_url = f"https://image.tmdb.org/t/p/w92{poster_path}"
            full_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
            title_escaped = prog['title'].replace('"', '&quot;')
            poster_html = f'<img src="{thumb_url}" alt="{prog["title"]}" style="height: 60px; border-radius: 4px; cursor: pointer;" onclick="showPoster(\'{full_url}\', \'{title_escaped}\')">'
        
        # Build rating with TMDb link
        if prog['tmdb_data']:
            tmdb_id = prog['tmdb_data'].get('id')
            tmdb_url = f"https://www.themoviedb.org/tv/{tmdb_id}"
            rating = f'<a href="{tmdb_url}" target="tmdb">{prog["rating"]}</a>'
        else:
            rating = prog['rating']
        
        # Year
        year = prog['date']
        
        # Genre (first non-Film category)
        genre = "-"
        if prog['categories'] != "-":
            cats = prog['categories'].split(", ")
            for cat in cats:
                if cat != "Film":
                    genre = cat
                    break
        
        # Bold Dramaseries
        if genre == "Dramaseries":
            genre = f"<strong>{genre}</strong>"
        
        # Country
        country = prog['country']
        
        # Build director link to Letterboxd
        if prog['director'] != "-":
            normalized = unicodedata.normalize('NFD', prog['director'])
            ascii_name = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
            director_slug = ascii_name.lower().replace(" ", "-").replace(".", "").replace("'", "")
            director = f'<a href="https://letterboxd.com/director/{director_slug}/" target="letterboxd">{prog["director"]}</a>'
        else:
            director = "-"
        
        # Build actor links to Letterboxd
        if prog['actors']:
            actor_links = []
            for actor in prog['actors'][:3]:
                normalized = unicodedata.normalize('NFD', actor)
                ascii_name = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
                actor_slug = ascii_name.lower().replace(" ", "-").replace(".", "").replace("'", "")
                actor_links.append(f'<a href="https://letterboxd.com/actor/{actor_slug}/" target="letterboxd">{actor}</a>')
            actors = ", ".join(actor_links)
        else:
            actors = "-"
        
        # Channel with logo
        channel = prog['channel']
        channel_id = prog.get('channel_id', '')
        channel_icon = icon_map.get(channel_id, '')
        if channel_icon:
            channel_html = f'<img src="{channel_icon}" alt="{channel}" title="{channel}" style="height: 24px; vertical-align: middle;">'
        else:
            channel_html = channel
        
        # Date and Time
        if prog['start_time']:
            bcast_date = prog['start_time'].strftime("%Y-%m-%d")
            bcast_time = prog['start_time'].strftime("%H:%M")
        else:
            bcast_date = "-"
            bcast_time = "-"
        
        # Combine subtitle and description
        subtitle_desc = ""
        if prog["subtitle"] != "-" and prog["description"] != "-":
            subtitle_desc = f"{prog['subtitle']}<br><small class='text-muted'>{prog['description']}</small>"
        elif prog["subtitle"] != "-":
            subtitle_desc = prog["subtitle"]
        elif prog["description"] != "-":
            subtitle_desc = f"<small class='text-muted'>{prog['description']}</small>"
        else:
            subtitle_desc = "-"
        
        html_lines.append('                    <tr>')
        html_lines.append(f'                        <td>{title_html}</td>')
        html_lines.append(f'                        <td>{poster_html}</td>')
        html_lines.append(f'                        <td>{subtitle_desc}</td>')
        html_lines.append(f'                        <td>{prog["episode"]}</td>')
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
    
    html_content = '\n'.join(html_lines)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    
    # Upload to blob storage (for Azure Functions and static website hosting)
    upload_success = upload_html_to_blob(html_content, "new-series.html")  # Uses $web container by default
    
    # Only save local copies when running locally (not in Azure with read-only filesystem)
    is_azure = (os.environ.get('FUNCTIONS_WORKER_RUNTIME') or 
               os.environ.get('WEBSITE_INSTANCE_ID') or 
               os.environ.get('WEBSITE_SITE_NAME'))
    
    if not is_azure:
        # Save local copy for development/backup
        try:
            local_path = Path("wwwroot") / "new-series.html"
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            logger.info(f"Saved local copy to {local_path}")
        except Exception as e:
            logger.warning(f"Could not save local copy: {e}")
        
        # Save timestamped copy to data folder
        try:
            data_path = Path("data") / f"new-series-{timestamp}.html"
            data_path.parent.mkdir(parents=True, exist_ok=True)
            with open(data_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            logger.info(f"Saved timestamped copy to {data_path}")
        except Exception as e:
            logger.warning(f"Could not save timestamped copy: {e}")
    
    if upload_success:
        print(f"Successfully uploaded new-series.html to blob storage ({non_film_count} programmes)")
    else:
        print(f"Failed to upload to blob storage (saved {non_film_count} programmes to local files)")
    
    # Also generate grouped views
    _generate_grouped_views(programmes, icon_map, timestamp)


def _generate_grouped_views(programmes, icon_map, timestamp):
    """Generate channel and genre grouped views."""
    from collections import defaultdict
    
    # Generate by-channel view
    _generate_by_channel_view(programmes, icon_map, timestamp)
    
    # Generate by-genre view
    _generate_by_genre_view(programmes, icon_map, timestamp)


def _build_nav_menu(active_page):
    """Build navigation menu with active page highlighted."""
    pages = [
        ('new-series.html', 'Chronological'),
        ('new-series-per-channel.html', 'By Channel'),
        ('new-series-per-genre.html', 'By Genre'),
        ('index.html', '← Films')
    ]
    
    nav_html = []
    nav_html.append('        <nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-3">')
    nav_html.append('            <div class="container-fluid">')
    nav_html.append('                <span class="navbar-brand">Series Premieres - Curated for <a href="https://letterboxd.com/stereoparty">@stereoparty</a></span>')
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


def _generate_by_channel_view(programmes, icon_map, timestamp):
    """Generate new-series-per-channel.html grouped by channel."""
    from collections import defaultdict
    
    # Group programmes by channel
    by_channel = defaultdict(list)
    for prog in programmes:
        by_channel[prog['channel']].append(prog)
    
    # Sort channels A-Z
    sorted_channels = sorted(by_channel.keys())
    
    # Build HTML
    html_lines = []
    html_lines.append('<!DOCTYPE html>')
    html_lines.append('<html lang="en" data-bs-theme="dark">')
    html_lines.append('<head>')
    html_lines.append('    <meta charset="UTF-8">')
    html_lines.append('    <meta name="viewport" content="width=device-width, initial-scale=1.0">')
    html_lines.append('    <title>Series Premieres - Curated for @stereoparty - By Channel</title>')
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
    html_lines.append(_build_nav_menu('new-series-per-channel.html'))
    html_lines.append(f'        <p class="text-muted">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | Total: {len(programmes)} series across {len(sorted_channels)} channels</p>')
    
    # Generate a table for each channel
    for channel in sorted_channels:
        progs = by_channel[channel]
        html_lines.append(f'        <div class="channel-section">')
        html_lines.append(f'            <h2>{channel} ({len(progs)})</h2>')
        html_lines.append('            <div class="table-responsive">')
        html_lines.append(_build_programme_table(progs, icon_map))
        html_lines.append('            </div>')
        html_lines.append('        </div>')
    
    html_lines.append('    </div>')
    html_lines.append(_build_poster_modal())
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
    upload_html_to_blob(html_content, "new-series-per-channel.html")
    _save_local_html(html_content, "new-series-per-channel.html", timestamp)
    print(f"Generated new-series-per-channel.html ({len(sorted_channels)} channels)")


def _generate_by_genre_view(programmes, icon_map, timestamp):
    """Generate new-series-per-genre.html grouped by genre."""
    from collections import defaultdict
    
    # Group programmes by first non-Film genre
    by_genre = defaultdict(list)
    for prog in programmes:
        genre = "-"
        if prog['categories'] != "-":
            cats = prog['categories'].split(", ")
            for cat in cats:
                if cat != "Film":
                    genre = cat
                    break
        by_genre[genre].append(prog)
    
    # Sort genres A-Z
    sorted_genres = sorted(by_genre.keys())
    
    # Build HTML
    html_lines = []
    html_lines.append('<!DOCTYPE html>')
    html_lines.append('<html lang="en" data-bs-theme="dark">')
    html_lines.append('<head>')
    html_lines.append('    <meta charset="UTF-8">')
    html_lines.append('    <meta name="viewport" content="width=device-width, initial-scale=1.0">')
    html_lines.append('    <title>Series Premieres - Curated for @stereoparty - By Genre</title>')
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
    html_lines.append(_build_nav_menu('new-series-per-genre.html'))
    html_lines.append(f'        <p class="text-muted">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | Total: {len(programmes)} series across {len(sorted_genres)} genres</p>')
    
    # Generate a table for each genre
    for genre in sorted_genres:
        progs = by_genre[genre]
        html_lines.append(f'        <div class="genre-section">')
        html_lines.append(f'            <h2>{genre} ({len(progs)})</h2>')
        html_lines.append('            <div class="table-responsive">')
        html_lines.append(_build_programme_table(progs, icon_map))
        html_lines.append('            </div>')
        html_lines.append('        </div>')
    
    html_lines.append('    </div>')
    html_lines.append(_build_poster_modal())
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
    upload_html_to_blob(html_content, "new-series-per-genre.html")
    _save_local_html(html_content, "new-series-per-genre.html", timestamp)
    print(f"Generated new-series-per-genre.html ({len(sorted_genres)} genres)")


def _build_programme_table(programmes, icon_map):
    """Build HTML table for a list of programmes."""
    table_lines = []
    table_lines.append('                <table class="table table-striped table-hover">')
    table_lines.append('                    <thead>')
    table_lines.append('                        <tr>')
    table_lines.append('                            <th>Title</th>')
    table_lines.append('                            <th>Poster</th>')
    table_lines.append('                            <th>Subtitle / Description</th>')
    table_lines.append('                            <th>Episode</th>')
    table_lines.append('                            <th>Rating</th>')
    table_lines.append('                            <th>LB</th>')
    table_lines.append('                            <th>Year</th>')
    table_lines.append('                            <th>Genre</th>')
    table_lines.append('                            <th>Cntry</th>')
    table_lines.append('                            <th>Director</th>')
    table_lines.append('                            <th>Actors</th>')
    table_lines.append('                            <th>Channel</th>')
    table_lines.append('                            <th>Date</th>')
    table_lines.append('                            <th>Time (CET)</th>')
    table_lines.append('                        </tr>')
    table_lines.append('                    </thead>')
    table_lines.append('                    <tbody>')
    
    for prog in programmes:
        table_lines.append(_build_table_row(prog, icon_map))
    
    table_lines.append('                    </tbody>')
    table_lines.append('                </table>')
    
    return '\n'.join(table_lines)


def _build_table_row(prog, icon_map):
    """Build a single table row for a programme."""
    search_url = f"https://www.ziggogo.tv/nl/epg/initial/search/{quote(prog['title'])}%20"
    
    # Letterboxd search link
    lb_search_parts = [quote(p, safe='') for p in [prog['title'], prog['date']] if p and p != "-"]
    lb_search_query = "+".join(lb_search_parts)
    lb_search_url = f"https://letterboxd.com/search/films/{lb_search_query}/?adult"
    lb_link = f'<a href="{lb_search_url}" target="letterboxd">🔍</a>'
    
    # Title link
    title_html = f'<a href="{search_url}" target="ziggogo">{prog["title"]}</a>'
    
    # Poster image
    poster_html = "-"
    if prog['tmdb_data'] and prog['tmdb_data'].get('poster_path'):
        poster_path = prog['tmdb_data']['poster_path']
        thumb_url = f"https://image.tmdb.org/t/p/w92{poster_path}"
        full_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
        title_escaped = prog['title'].replace('"', '&quot;')
        poster_html = f'<img src="{thumb_url}" alt="{prog["title"]}" style="height: 60px; border-radius: 4px; cursor: pointer;" onclick="showPoster(\'{full_url}\', \'{title_escaped}\')">'
    
    # Rating with TMDb link
    if prog['tmdb_data']:
        tmdb_id = prog['tmdb_data'].get('id')
        tmdb_url = f"https://www.themoviedb.org/tv/{tmdb_id}"
        rating = f'<a href="{tmdb_url}" target="tmdb">{prog["rating"]}</a>'
    else:
        rating = prog['rating']
    
    # Genre
    genre = "-"
    if prog['categories'] != "-":
        cats = prog['categories'].split(", ")
        for cat in cats:
            if cat != "Film":
                genre = cat
                break
    if genre == "Dramaseries":
        genre = f"<strong>{genre}</strong>"
    
    # Director link
    if prog['director'] != "-":
        normalized = unicodedata.normalize('NFD', prog['director'])
        ascii_name = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
        director_slug = ascii_name.lower().replace(" ", "-").replace(".", "").replace("'", "")
        director = f'<a href="https://letterboxd.com/director/{director_slug}/" target="letterboxd">{prog["director"]}</a>'
    else:
        director = "-"
    
    # Actor links
    if prog['actors']:
        actor_links = []
        for actor in prog['actors'][:3]:
            normalized = unicodedata.normalize('NFD', actor)
            ascii_name = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
            actor_slug = ascii_name.lower().replace(" ", "-").replace(".", "").replace("'", "")
            actor_links.append(f'<a href="https://letterboxd.com/actor/{actor_slug}/" target="letterboxd">{actor}</a>')
        actors = ", ".join(actor_links)
    else:
        actors = "-"
    
    # Channel with logo
    channel_id = prog.get('channel_id', '')
    channel_icon = icon_map.get(channel_id, '')
    if channel_icon:
        channel_html = f'<img src="{channel_icon}" alt="{prog["channel"]}" title="{prog["channel"]}" style="height: 24px; vertical-align: middle;">'
    else:
        channel_html = prog['channel']
    
    # Date and Time
    if prog['start_time']:
        bcast_date = prog['start_time'].strftime("%Y-%m-%d")
        bcast_time = prog['start_time'].strftime("%H:%M")
    else:
        bcast_date = "-"
        bcast_time = "-"
    
    # Subtitle and description
    if prog["subtitle"] != "-" and prog["description"] != "-":
        subtitle_desc = f"{prog['subtitle']}<br><small class='text-muted'>{prog['description']}</small>"
    elif prog["subtitle"] != "-":
        subtitle_desc = prog["subtitle"]
    elif prog["description"] != "-":
        subtitle_desc = f"<small class='text-muted'>{prog['description']}</small>"
    else:
        subtitle_desc = "-"
    
    row_html = []
    row_html.append('                        <tr>')
    row_html.append(f'                            <td>{title_html}</td>')
    row_html.append(f'                            <td>{poster_html}</td>')
    row_html.append(f'                            <td>{subtitle_desc}</td>')
    row_html.append(f'                            <td>{prog["episode"]}</td>')
    row_html.append(f'                            <td>{rating}</td>')
    row_html.append(f'                            <td>{lb_link}</td>')
    row_html.append(f'                            <td>{prog["date"]}</td>')
    row_html.append(f'                            <td>{genre}</td>')
    row_html.append(f'                            <td>{prog["country"]}</td>')
    row_html.append(f'                            <td>{director}</td>')
    row_html.append(f'                            <td>{actors}</td>')
    row_html.append(f'                            <td>{channel_html}</td>')
    row_html.append(f'                            <td>{bcast_date}</td>')
    row_html.append(f'                            <td>{bcast_time}</td>')
    row_html.append('                        </tr>')
    
    return '\n'.join(row_html)


def _build_poster_modal():
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


def _save_local_html(html_content, filename, timestamp):
    """Save HTML file locally if not in Azure."""
    is_azure = (os.environ.get('FUNCTIONS_WORKER_RUNTIME') or 
               os.environ.get('WEBSITE_INSTANCE_ID') or 
               os.environ.get('WEBSITE_SITE_NAME'))
    
    if not is_azure:
        try:
            local_path = Path("wwwroot") / filename
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            logger.info(f"Saved local copy to {local_path}")
        except Exception as e:
            logger.warning(f"Could not save local copy: {e}")


if __name__ == "__main__":
    list_non_films()
