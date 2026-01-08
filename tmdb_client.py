"""
TMDb Client Module
Normalizes film titles and fetches metadata via The Movie Database API.
"""

import logging
import os
from typing import Dict, Any, Optional
import requests

logger = logging.getLogger(__name__)


class TMDbClient:
    """Client for The Movie Database (TMDb) API."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize TMDb client.

        Args:
            config: Configuration dictionary with 'tmdb' section
        """
        self.config = config.get("tmdb", {})
        self.api_key = os.getenv("TMDB_API_KEY")
        self.base_url = self.config.get("base_url", "https://api.themoviedb.org/3")

        if not self.api_key:
            logger.warning("TMDb API key not configured (set TMDB_API_KEY environment variable)")

    def search_movie(self, title: str, year: Optional[int] = None) -> Dict[str, Any] | None:
        """
        Search for a movie by title.

        Args:
            title: Movie title to search for
            year: Optional release year to narrow search

        Returns:
            Movie data dictionary or None if not found
        """
        if not self.api_key:
            logger.warning("Cannot search: TMDb API key not configured")
            return None

        try:
            params = {
                "api_key": self.api_key,
                "query": title,
            }
            if year:
                params["year"] = year

            url = f"{self.base_url}/search/movie"
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            results = response.json().get("results", [])
            if results:
                best_match = results[0]
                logger.info(f"Found TMDb match for '{title}': {best_match.get('title')}")
                return best_match

            logger.info(f"No TMDb match found for '{title}'")
            return None

        except requests.RequestException as e:
            logger.error(f"TMDb search failed for '{title}': {e}")
            return None

    def get_movie_details(self, movie_id: int) -> Dict[str, Any] | None:
        """
        Get detailed movie information by ID.

        Args:
            movie_id: TMDb movie ID

        Returns:
            Movie details dictionary or None if fetch fails
        """
        if not self.api_key:
            return None

        try:
            params = {"api_key": self.api_key}
            url = f"{self.base_url}/movie/{movie_id}"
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            return response.json()

        except requests.RequestException as e:
            logger.error(f"Failed to fetch TMDb details for movie {movie_id}: {e}")
            return None

    def normalize_title(self, title: str, year: Optional[int] = None) -> Dict[str, Any] | None:
        """
        Normalize a film title against TMDb to get canonical ID and metadata.
        If no match found with exact year, tries year+1, year-1, then no year.

        Args:
            title: Film title to normalize
            year: Optional release year

        Returns:
            Dictionary with normalized data (id, title, release_date, etc.) or None
        """
        # Try exact year first
        movie = self.search_movie(title, year)
        
        # If no match and year provided, try year+1 and year-1
        if not movie and year:
            logger.info(f"No match for '{title}' ({year}), trying year+1")
            movie = self.search_movie(title, year + 1)
            
            if not movie:
                logger.info(f"No match for '{title}' ({year+1}), trying year-1")
                movie = self.search_movie(title, year - 1)
            
            if not movie:
                logger.info(f"No match for '{title}' with year variations, trying without year")
                movie = self.search_movie(title, None)
        
        if not movie:
            return None

        movie_id = movie.get("id")
        details = self.get_movie_details(movie_id)

        if not details:
            return {
                "tmdb_id": movie_id,
                "title": movie.get("title"),
                "release_date": movie.get("release_date"),
                "vote_average": movie.get("vote_average"),
                "vote_count": movie.get("vote_count"),
                "poster_path": movie.get("poster_path"),
            }

        return {
            "tmdb_id": details.get("id"),
            "title": details.get("title"),
            "release_date": details.get("release_date"),
            "overview": details.get("overview"),
            "genres": [g.get("name") for g in details.get("genres", [])],
            "vote_average": details.get("vote_average"),
            "vote_count": details.get("vote_count"),
            "poster_path": details.get("poster_path"),
        }

    def search_tv_series(self, title: str, year: Optional[int] = None, country: Optional[str] = None) -> Dict[str, Any] | None:
        """
        Search for a TV series by title.

        Args:
            title: TV series title to search for
            year: Optional first air date year to narrow search
            country: Optional origin country to improve matching

        Returns:
            TV series data dictionary or None if not found
        """
        if not self.api_key:
            logger.warning("Cannot search: TMDb API key not configured")
            return None

        try:
            params = {
                "api_key": self.api_key,
                "query": title,
            }
            if year:
                params["first_air_date_year"] = year

            url = f"{self.base_url}/search/tv"
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            results = response.json().get("results", [])
            
            if not results:
                logger.info(f"No TMDb TV series match found for '{title}'")
                return None

            # Score and rank results
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
                
                # Country match
                if country and result.get('origin_country'):
                    origin_countries = result.get('origin_country', [])
                    if country in origin_countries:
                        score += 5
                
                # Title similarity (exact match gets bonus)
                if result.get('name', '').lower() == title.lower():
                    score += 3
                
                # First result gets slight preference
                if result == results[0]:
                    score += 1
                
                if score > best_score:
                    best_score = score
                    best_match = result

            if best_match:
                logger.info(f"Found TMDb TV series match for '{title}': {best_match.get('name')}")
                return best_match

            # Fallback to first result if no good match
            logger.info(f"Using first result for '{title}': {results[0].get('name')}")
            return results[0]

        except requests.RequestException as e:
            logger.error(f"TMDb TV series search failed for '{title}': {e}")
            return None

    def get_tv_series_details(self, series_id: int) -> Dict[str, Any] | None:
        """
        Get detailed TV series information by ID.

        Args:
            series_id: TMDb TV series ID

        Returns:
            TV series details dictionary or None if fetch fails
        """
        if not self.api_key:
            return None

        try:
            params = {"api_key": self.api_key}
            url = f"{self.base_url}/tv/{series_id}"
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            return response.json()

        except requests.RequestException as e:
            logger.error(f"Failed to fetch TMDb TV series details for {series_id}: {e}")
            return None

    def normalize_tv_series(self, title: str, year: Optional[int] = None, country: Optional[str] = None) -> Dict[str, Any] | None:
        """
        Normalize a TV series title against TMDb to get canonical ID and metadata.
        If no match found with exact year, tries year+1, year-1, then no year.

        Args:
            title: TV series title to normalize
            year: Optional first air date year
            country: Optional origin country for better matching

        Returns:
            Dictionary with normalized data (id, name, first_air_date, etc.) or None
        """
        # Try exact year first
        series = self.search_tv_series(title, year, country)
        
        # If no match and year provided, try year+1 and year-1
        if not series and year:
            logger.info(f"No match for '{title}' ({year}), trying year+1")
            series = self.search_tv_series(title, year + 1, country)
            
            if not series:
                logger.info(f"No match for '{title}' ({year+1}), trying year-1")
                series = self.search_tv_series(title, year - 1, country)
            
            if not series:
                logger.info(f"No match for '{title}' with year variations, trying without year")
                series = self.search_tv_series(title, None, country)
        
        if not series:
            return None

        series_id = series.get("id")
        details = self.get_tv_series_details(series_id)

        if not details:
            return {
                "tmdb_id": series_id,
                "name": series.get("name"),
                "first_air_date": series.get("first_air_date"),
                "vote_average": series.get("vote_average"),
                "vote_count": series.get("vote_count"),
                "poster_path": series.get("poster_path"),
            }

        return {
            "tmdb_id": details.get("id"),
            "name": details.get("name"),
            "first_air_date": details.get("first_air_date"),
            "overview": details.get("overview"),
            "genres": [g.get("name") for g in details.get("genres", [])],
            "vote_average": details.get("vote_average"),
            "vote_count": details.get("vote_count"),
            "poster_path": details.get("poster_path"),
            "origin_country": details.get("origin_country"),
        }
