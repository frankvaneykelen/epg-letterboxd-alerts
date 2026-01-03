"""
Letterboxd CSV Loader Module
Loads watchlist and diary data from exported Letterboxd CSV files.
"""

import logging
import csv
from typing import Set, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class LetterboxdCSVLoader:
    """Loads Letterboxd data from CSV exports (no API required)."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize CSV loader.

        Args:
            config: Configuration dictionary with 'letterboxd' section
        """
        self.config = config.get("letterboxd", {})
        self.watchlist_path = self.config.get("watchlist_csv")
        self.diary_path = self.config.get("diary_csv")
        self.watched_path = self.config.get("watched_csv", "data/watched.csv")
        self.do_not_watchlist_path = self.config.get("do_not_watchlist_csv", "data/do-not-watchlist.csv")
        
        # Cache loaded data - store by (title, year) tuple
        self._watchlist_films: Set[tuple] = set()
        self._seen_films: Set[tuple] = set()
        self._do_not_watchlist_films: Set[tuple] = set()
        self._loaded = False

    def load_data(self) -> bool:
        """
        Load watchlist and diary CSVs into memory.

        Returns:
            True if data was loaded successfully, False otherwise
        """
        if self._loaded:
            return True

        success = True

        # Load do-not-watchlist (always try to load, even if no path configured)
        if self.do_not_watchlist_path:
            do_not_path = Path(self.do_not_watchlist_path)
            if do_not_path.exists():
                if self._load_do_not_watchlist(self.do_not_watchlist_path):
                    logger.info(f"Loaded {len(self._do_not_watchlist_films)} films from do-not-watchlist CSV")
                else:
                    logger.warning("Failed to load do-not-watchlist CSV")
            else:
                logger.debug("No do-not-watchlist CSV found (optional)")

        # Load watchlist
        if self.watchlist_path:
            if self._load_watchlist(self.watchlist_path):
                logger.info(f"Loaded {len(self._watchlist_films)} films from watchlist CSV")
            else:
                logger.warning("Failed to load watchlist CSV")
                success = False
        else:
            logger.info("No watchlist CSV configured")

        # Try loading watched.csv (preferred) or diary.csv as fallback
        watched_loaded = False
        if self.watched_path:
            watched_path = Path(self.watched_path)
            if watched_path.exists():
                if self._load_watched(self.watched_path):
                    logger.info(f"Loaded {len(self._seen_films)} films from watched CSV")
                    watched_loaded = True

        # Only try diary if watched.csv wasn't found or failed
        if not watched_loaded and self.diary_path:
            if self._load_diary(self.diary_path):
                logger.info(f"Loaded {len(self._seen_films)} films from diary CSV")
            else:
                logger.warning("Failed to load diary CSV")
                success = False

        self._loaded = success
        return success

    def _load_watchlist(self, path: str) -> bool:
        """Load watchlist from CSV.

        Expected columns: Date, Name, Year, Letterboxd URI

        Args:
            path: Path to watchlist.csv

        Returns:
            True if loaded successfully
        """
        try:
            csv_path = Path(path)
            if not csv_path.exists():
                logger.error(f"Watchlist CSV not found: {path}")
                return False

            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get('Name', '').strip()
                    year_str = row.get('Year', '').strip()
                    
                    if name and year_str:
                        try:
                            year = int(year_str)
                            self._watchlist_films.add((name, year))
                        except ValueError:
                            logger.warning(f"Invalid year in watchlist: {year_str} for {name}")
                            continue

            return True

        except Exception as e:
            logger.error(f"Error loading watchlist CSV: {e}")
            return False

    def _load_do_not_watchlist(self, path: str) -> bool:
        """Load do-not-watchlist from CSV.

        Expected columns: Name, Year

        Args:
            path: Path to do-not-watchlist.csv

        Returns:
            True if loaded successfully
        """
        try:
            csv_path = Path(path)
            if not csv_path.exists():
                logger.debug(f"Do-not-watchlist CSV not found: {path}")
                return False

            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get('Name', '').strip()
                    year_str = row.get('Year', '').strip()
                    
                    if name and year_str:
                        try:
                            year = int(year_str)
                            self._do_not_watchlist_films.add((name, year))
                        except ValueError:
                            logger.warning(f"Invalid year in do-not-watchlist: {year_str} for {name}")
                            continue

            return True

        except Exception as e:
            logger.error(f"Error loading do-not-watchlist CSV: {e}")
            return False

    def _load_watched(self, path: str) -> bool:
        """
        Load watched films CSV.
        
        Expected columns: Date, Name, Year, Letterboxd URI

        Args:
            path: Path to watched.csv

        Returns:
            True if loaded successfully
        """
        try:
            csv_path = Path(path)
            if not csv_path.exists():
                logger.error(f"Watched CSV not found: {path}")
                return False

            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get('Name', '').strip()
                    year_str = row.get('Year', '').strip()
                    
                    if name and year_str:
                        try:
                            year = int(year_str)
                            self._seen_films.add((name, year))
                        except ValueError:
                            logger.warning(f"Invalid year in watched: {year_str} for {name}")
                            continue

            return True

        except Exception as e:
            logger.error(f"Error loading watched CSV: {e}")
            return False

    def _load_diary(self, path: str) -> bool:
        """
        Load diary CSV with ratings.
        
        Expected columns: Date, Name, Year, Letterboxd URI, Rating

        Args:
            path: Path to diary.csv

        Returns:
            True if loaded successfully
        """
        try:
            csv_path = Path(path)
            if not csv_path.exists():
                logger.error(f"Diary CSV not found: {path}")
                return False

            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                row_count = 0
                for row in reader:
                    row_count += 1
                    name = row.get('Name', '').strip()
                    year_str = row.get('Year', '').strip()
                    
                    if name and year_str:
                        try:
                            year = int(year_str)
                            self._seen_films.add((name, year))
                        except ValueError:
                            logger.warning(f"Invalid year in diary: {year_str} for {name}")
                            continue
                
                if row_count == 0:
                    logger.warning(f"Diary CSV is empty: {path}")
                    return False

            return True

        except Exception as e:
            logger.error(f"Error loading diary CSV: {e}")
            return False

    def is_on_watchlist(self, tmdb_title: str, tmdb_year: int) -> bool:
        """
        Check if a film is on the watchlist by title and year (±1 year tolerance).

        Args:
            tmdb_title: TMDb movie title
            tmdb_year: Release year from TMDb

        Returns:
            True if on watchlist, False otherwise
        """
        if not self._loaded:
            self.load_data()
        
        # Check with ±1 year tolerance
        for year_offset in [-1, 0, 1]:
            if (tmdb_title, tmdb_year + year_offset) in self._watchlist_films:
                return True
        return False

    def is_seen(self, tmdb_title: str, tmdb_year: int) -> bool:
        """
        Check if a film has been watched by title and year (±1 year tolerance).

        Args:
            tmdb_title: TMDb movie title
            tmdb_year: Release year from TMDb

        Returns:
            True if seen, False otherwise
        """
        if not self._loaded:
            self.load_data()
        
        # Check with ±1 year tolerance
        for year_offset in [-1, 0, 1]:
            if (tmdb_title, tmdb_year + year_offset) in self._seen_films:
                return True
        return False

    def is_on_do_not_watchlist(self, tmdb_title: str, tmdb_year: int) -> bool:
        """
        Check if a film is on the do-not-watchlist by title and year (±1 year tolerance).

        Args:
            tmdb_title: TMDb movie title
            tmdb_year: Release year from TMDb

        Returns:
            True if on do-not-watchlist, False otherwise
        """
        if not self._loaded:
            self.load_data()
        
        # Check with ±1 year tolerance
        for year_offset in [-1, 0, 1]:
            if (tmdb_title, tmdb_year + year_offset) in self._do_not_watchlist_films:
                return True
        return False

    def get_stats(self) -> Dict[str, int]:
        """
        Get statistics about loaded data.

        Returns:
            Dictionary with counts of watchlist, seen, and rated films
        """
        if not self._loaded:
            self.load_data()
        
        return {
            "watchlist_count": len(self._watchlist_films),
            "seen_count": len(self._seen_films),
            "do_not_watchlist_count": len(self._do_not_watchlist_films),
        }
