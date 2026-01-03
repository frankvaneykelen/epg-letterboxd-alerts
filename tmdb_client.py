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
            }

        return {
            "tmdb_id": details.get("id"),
            "title": details.get("title"),
            "release_date": details.get("release_date"),
            "overview": details.get("overview"),
            "genres": [g.get("name") for g in details.get("genres", [])],
            "vote_average": details.get("vote_average"),
            "vote_count": details.get("vote_count"),
        }
