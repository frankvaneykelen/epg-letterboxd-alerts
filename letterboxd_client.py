"""
Letterboxd Client Module
Queries Letterboxd watchlist and ratings via API.
"""

import logging
import os
from typing import Dict, Any, Optional
import requests

logger = logging.getLogger(__name__)


class LetterboxdClient:
    """Client for Letterboxd API."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Letterboxd client.

        Args:
            config: Configuration dictionary with 'letterboxd' section
        """
        self.config = config.get("letterboxd", {})
        self.oauth_token = os.getenv("LETTERBOXD_OAUTH_TOKEN")
        self.base_url = self.config.get("base_url", "https://letterboxd.com/api/v0")

        if not self.oauth_token:
            logger.warning("Letterboxd OAuth token not configured (set LETTERBOXD_OAUTH_TOKEN environment variable)")

        self.session = requests.Session()
        if self.oauth_token:
            self.session.headers.update(
                {"Authorization": f"Bearer {self.oauth_token}"}
            )

    def is_on_watchlist(self, movie_id: str) -> bool:
        """
        Check if a movie is on the user's watchlist.

        Args:
            movie_id: Letterboxd or external movie ID

        Returns:
            True if on watchlist, False otherwise
        """
        if not self.config.get("enabled", False):
            return False
        
        if not self.oauth_token:
            logger.warning("Cannot check watchlist: token not configured")
            return False

        try:
            # Example endpoint; adjust based on actual Letterboxd API
            url = f"{self.base_url}/me/watchlist"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            watchlist = response.json().get("items", [])
            return any(item.get("id") == movie_id for item in watchlist)

        except requests.RequestException as e:
            logger.error(f"Failed to check watchlist for {movie_id}: {e}")
            return False

    def is_seen(self, movie_id: str) -> bool:
        """
        Check if a movie has been marked as seen/watched.

        Args:
            movie_id: Letterboxd or external movie ID

        Returns:
            True if seen, False otherwise
        """
        if not self.config.get("enabled", False):
            return False
        
        if not self.oauth_token:
            logger.warning("Cannot check seen status: token not configured")
            return False

        try:
            # Example endpoint; adjust based on actual Letterboxd API
            url = f"{self.base_url}/me/films"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            films = response.json().get("items", [])
            return any(item.get("id") == movie_id for item in films)

        except requests.RequestException as e:
            logger.error(f"Failed to check seen status for {movie_id}: {e}")
            return False

    def get_community_rating(self, movie_id: str) -> Optional[float]:
        """
        Fetch the community average rating for a film.

        Args:
            movie_id: Letterboxd or external movie ID

        Returns:
            Average rating (0-5 scale) or None if unavailable
        """
        if not self.config.get("enabled", False):
            return None
        
        if not self.oauth_token:
            logger.warning("Cannot fetch rating: token not configured")
            return None

        try:
            # Example endpoint; adjust based on actual Letterboxd API
            url = f"{self.base_url}/films/{movie_id}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            data = response.json()
            rating = data.get("rating")
            if rating is not None:
                return float(rating)

            return None

        except requests.RequestException as e:
            logger.error(f"Failed to fetch rating for {movie_id}: {e}")
            return None

    def get_film_data(self, movie_id: str) -> Dict[str, Any] | None:
        """
        Fetch complete film data from Letterboxd.

        Args:
            movie_id: Letterboxd or external movie ID

        Returns:
            Film data dictionary or None if fetch fails
        """
        if not self.config.get("enabled", False):
            return None
        
        if not self.oauth_token:
            return None

        try:
            url = f"{self.base_url}/films/{movie_id}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            return response.json()

        except requests.RequestException as e:
            logger.error(f"Failed to fetch film data for {movie_id}: {e}")
            return None
