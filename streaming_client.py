"""
Streaming Availability API client for querying streaming catalogs.
Uses the RapidAPI Streaming Availability service.
"""

import requests
import logging
from datetime import datetime
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class StreamingClient:
    """Client for Streaming Availability API (RapidAPI)."""
    
    def __init__(self, api_key: str):
        """
        Initialize the Streaming Availability client.
        
        Args:
            api_key: RapidAPI key for Streaming Availability API
        """
        self.api_key = api_key
        self.base_url = "https://streaming-availability.p.rapidapi.com"
        self.headers = {
            'x-rapidapi-host': 'streaming-availability.p.rapidapi.com',
            'x-rapidapi-key': api_key
        }
        self._countries_cache = None
    
    def get_countries(self) -> Dict[str, str]:
        """
        Get country codes and names from the API.
        Results are cached for the lifetime of the client instance.
        
        Returns:
            Dictionary mapping country codes to country names
        """
        if self._countries_cache is not None:
            return self._countries_cache
        
        try:
            endpoint = f"{self.base_url}/countries"
            response = requests.get(endpoint, headers=self.headers, timeout=10)
            response.raise_for_status()
            countries_data = response.json()
            
            # Convert array of {countryCode, name} to dict
            self._countries_cache = {c['countryCode']: c['name'] for c in countries_data}
            logger.info(f"Loaded {len(self._countries_cache)} countries from API")
            return self._countries_cache
        except Exception as e:
            logger.warning(f"Failed to fetch countries from API: {e}")
            # Return basic fallback
            return {
                'US': 'United States', 'GB': 'United Kingdom', 'FR': 'France', 'DE': 'Germany',
                'IT': 'Italy', 'ES': 'Spain', 'NL': 'Netherlands', 'JP': 'Japan',
                'KR': 'South Korea', 'CN': 'China', 'IN': 'India', 'CA': 'Canada',
                'AU': 'Australia', 'BE': 'Belgium', 'SE': 'Sweden', 'NO': 'Norway',
                'DK': 'Denmark', 'FI': 'Finland', 'RU': 'Russia', 'BR': 'Brazil'
            }
        
    def search_shows(
        self,
        country: str = "nl",
        catalogs: Optional[List[str]] = None,
        show_type: str = "movie",
        genres: Optional[List[str]] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        rating_min: Optional[int] = None,
        order_by: str = "release_date",
        order_direction: str = "desc",
        cursor: Optional[str] = None
    ) -> Dict:
        """
        Search for shows using filters.
        
        Args:
            country: Two-letter country code (default: "nl")
            catalogs: List of catalog IDs (e.g., ["netflix", "disney", "prime"])
            show_type: "movie" or "series"
            genres: List of genre IDs to filter by
            year_min: Minimum release year
            year_max: Maximum release year
            rating_min: Minimum rating (0-100)
            order_by: Field to order by (default: "original_title")
            order_direction: "asc" or "desc"
            cursor: Pagination cursor from previous response
            
        Returns:
            Dictionary with 'shows' list and 'nextCursor' for pagination
        """
        endpoint = f"{self.base_url}/shows/search/filters"
        
        params = {
            "country": country,
            "show_type": show_type,
            "order_by": order_by,
            "order_direction": order_direction,
            "output_language": "en"
        }
        
        # Add optional filters
        if catalogs:
            params["catalogs"] = ",".join(catalogs)
        if genres:
            params["genres"] = ",".join(genres)
        if year_min:
            params["year_min"] = year_min
        if year_max:
            params["year_max"] = year_max
        if rating_min:
            params["rating_min"] = rating_min
        if cursor:
            params["cursor"] = cursor
            
        try:
            response = requests.get(endpoint, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Streaming API error: {e}")
            return {"shows": [], "nextCursor": None}
    
    def get_all_shows(
        self,
        country: str = "nl",
        catalogs: Optional[List[str]] = None,
        show_type: str = "movie",
        genres: Optional[List[str]] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        rating_min: Optional[int] = None,
        max_pages: int = 10
    ) -> List[Dict]:
        """
        Get all shows matching filters (handles pagination automatically).
        
        Args:
            Same as search_shows(), plus:
            max_pages: Maximum number of pages to fetch (default: 10)
            
        Returns:
            List of all shows from all pages
        """
        all_shows = []
        cursor = None
        pages_fetched = 0
        
        while pages_fetched < max_pages:
            result = self.search_shows(
                country=country,
                catalogs=catalogs,
                show_type=show_type,
                genres=genres,
                year_min=year_min,
                year_max=year_max,
                rating_min=rating_min,
                cursor=cursor
            )
            
            shows = result.get("shows", [])
            if not shows:
                break
                
            all_shows.extend(shows)
            pages_fetched += 1
            
            # Check for next page
            cursor = result.get("nextCursor")
            if not cursor:
                break
                
            logger.info(f"Fetched page {pages_fetched}, total shows: {len(all_shows)}")
        
        logger.info(f"Retrieved {len(all_shows)} shows from Streaming API")
        return all_shows
    
    def get_current_year_movies(
        self,
        catalogs: Optional[List[str]] = None,
        exclude_genres: Optional[List[str]] = None,
        rating_min: Optional[int] = None,
        max_pages: int = 10
    ) -> List[Dict]:
        """
        Get movies from current and previous year.
        
        Args:
            catalogs: List of streaming services (default: your subscriptions)
            exclude_genres: Genres to exclude (default: ["talk", "news"])
            rating_min: Minimum rating 0-100 (optional, don't filter by default)
            max_pages: Maximum number of pages to fetch (default: 10, 20 shows per page)
            
        Returns:
            List of movie shows
        """
        current_year = datetime.now().year
        
        # Default to your subscriptions
        if catalogs is None:
            catalogs = ["netflix", "disney", "prime", "hbo"]
        
        # Log parameters once at the start
        logger.info(f"Fetching movies with: catalogs={catalogs}, year_min={current_year - 1}, year_max={current_year}, rating_min={rating_min}, max_pages={max_pages}")
        
        # Don't use genres filter - fetch all and filter client-side if needed
        # The API seems to have issues with too many parameters
        
        return self.get_all_shows(
            country="nl",
            catalogs=catalogs,
            show_type="movie",
            year_min=current_year - 1,
            year_max=current_year,
            rating_min=rating_min,
            max_pages=max_pages
        )
    
    def get_current_year_series(
        self,
        catalogs: Optional[List[str]] = None,
        rating_min: Optional[int] = None,
        max_pages: int = 10
    ) -> List[Dict]:
        """
        Get series from current and previous year.
        
        Args:
            catalogs: List of streaming services (default: your subscriptions)
            rating_min: Minimum rating 0-100 (optional)
            max_pages: Maximum number of pages to fetch (default: 10, 20 shows per page)
            
        Returns:
            List of series shows
        """
        current_year = datetime.now().year
        
        # Default to your subscriptions
        if catalogs is None:
            catalogs = ["netflix", "disney", "prime", "hbo"]
        
        # Log parameters once at the start
        logger.info(f"Fetching series with: catalogs={catalogs}, year_min={current_year - 1}, year_max={current_year}, rating_min={rating_min}, max_pages={max_pages}")
        
        return self.get_all_shows(
            country="nl",
            catalogs=catalogs,
            show_type="series",
            year_min=current_year - 1,
            year_max=current_year,
            rating_min=rating_min,
            max_pages=max_pages
        )
    
    def parse_show_data(self, show: Dict) -> Dict:
        """
        Parse Streaming API show data into a format similar to your EPG broadcasts.
        
        Args:
            show: Raw show data from Streaming API
            
        Returns:
            Parsed show data
        """
        # Extract basic info
        title = show.get("title", "")
        overview = show.get("overview", "")
        year = show.get("releaseYear")
        
        # Get genres (can be strings or dicts)
        genres_raw = show.get("genres", [])
        genres = []
        for g in genres_raw:
            if isinstance(g, dict):
                genres.append(g.get("name", ""))
            else:
                genres.append(str(g))
        
        # Get directors (can be strings or dicts)
        directors_raw = show.get("directors", [])
        directors = []
        for d in directors_raw:
            if isinstance(d, dict):
                directors.append(d.get("name", ""))
            else:
                directors.append(str(d))
        director = directors[0] if directors else None
        
        # Get cast (can be strings or dicts)
        cast_raw = show.get("cast", [])
        cast = []
        for c in cast_raw:
            if isinstance(c, dict):
                cast.append(c.get("name", ""))
            else:
                cast.append(str(c))
        
        # Get streaming options
        streaming_options = show.get("streamingOptions", {}).get("nl", [])
        services = []
        available_since_dates = []
        for option in streaming_options:
            service = option.get("service", {})
            service_id = service.get("id")
            service_name = service.get("name")
            addon = option.get("addon")
            available_since = option.get("availableSince")
            if service_id:
                services.append({
                    "id": service_id,
                    "name": service_name,
                    "type": option.get("type"),
                    "link": option.get("link"),
                    "addon": addon,
                    "available_since": available_since
                })
                if available_since:
                    available_since_dates.append(available_since)
        # Use the latest availableSince date among all valid streaming services
        available_since = max(available_since_dates) if available_since_dates else None
        # Get TMDb ID for cross-referencing with your existing system
        tmdb_id_raw = show.get("tmdbId")
        if tmdb_id_raw and isinstance(tmdb_id_raw, str) and '/' in tmdb_id_raw:
            tmdb_id = tmdb_id_raw.split('/')[-1]
        else:
            tmdb_id = tmdb_id_raw
        original_title = show.get("originalTitle", "")
        parsed = {
            "title": title,
            "description": overview,
            "year": year,
            "genres": genres,
            "director": director,
            "directors": directors,
            "actors": cast,
            "streaming_services": services,
            "tmdb_id": tmdb_id,
            "show_type": show.get("showType"),
            "imdb_id": show.get("imdbId"),
            "poster_url": show.get("imageSet", {}).get("verticalPoster", {}).get("w480"),
            "backdrop_url": show.get("imageSet", {}).get("horizontalPoster", {}).get("w720"),
            "rating": show.get("rating"),
            "available_since": available_since,
            "raw_data": show
        }
        if original_title and original_title != title:
            parsed["original_title"] = original_title
        return parsed


