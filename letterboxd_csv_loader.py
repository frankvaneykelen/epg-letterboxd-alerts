"""
Letterboxd CSV Loader Module
Loads watchlist and diary data from exported Letterboxd CSV files.
"""

import logging
import os
import csv
from typing import Set, Dict, Any, Optional
from pathlib import Path
from do_not_watchlist_loader import DoNotWatchListLoader

logger = logging.getLogger(__name__)

# Detect if running in Azure
def is_azure_environment():
    """Check if running in Azure Functions environment."""
    return (
        os.getenv('FUNCTIONS_WORKER_RUNTIME') is not None or
        os.getenv('WEBSITE_INSTANCE_ID') is not None or
        os.getenv('WEBSITE_SITE_NAME') is not None
    )

class LetterboxdCSVLoader:
    """Loads Letterboxd data from CSV exports (no API required)."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize CSV loader.

        Args:
            config: Configuration dictionary with 'letterboxd' section
        """
        self.config = config.get("letterboxd", {})
        
        # Get paths from config
        watchlist_csv = self.config.get("watchlist_csv", "data/watchlist.csv")
        diary_csv = self.config.get("diary_csv", "data/diary.csv")
        watched_csv = self.config.get("watched_csv", "data/watched.csv")
        
        # In Azure, replace data/ prefix with /tmp/ (extracted ZIP location)
        if is_azure_environment():
            self.watchlist_path = watchlist_csv.replace("data/", "/tmp/") if watchlist_csv else None
            self.diary_path = diary_csv.replace("data/", "/tmp/") if diary_csv else None
            self.watched_path = watched_csv.replace("data/", "/tmp/")
            logger.info(f"Running in Azure - using /tmp for CSV files")
        else:
            self.watchlist_path = watchlist_csv
            self.diary_path = diary_csv
            self.watched_path = watched_csv
        
        # Cache loaded data - store by (title, year) tuple
        self._watchlist_films: Set[tuple] = set()
        self._seen_films: Set[tuple] = set()
        self._loaded = False
        
        # Initialize do-not-watchlist loader (uses Table Storage)
        self._do_not_watchlist_loader = DoNotWatchListLoader()

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
        # Note: do-not-watchlist from Table Storage
        self._do_not_watchlist_loader.load_data()
        
        # Load watchlist (from extracted ZIP in /tmp/ or data/)
        if self.watchlist_path:
            if Path(self.watchlist_path).exists():
                if self._load_watchlist(self.watchlist_path):
                    logger.info(f"Loaded {len(self._watchlist_films)} films from watchlist CSV")
                else:
                    logger.warning("Failed to load watchlist CSV")
                    success = False
            else:
                logger.warning(f"Watchlist CSV not found: {self.watchlist_path}")
                success = False
        else:
            logger.info("No watchlist CSV configured")

        # Try loading watched.csv (preferred) or diary.csv as fallback (from extracted ZIP)
        watched_loaded = False
        if self.watched_path:
            watched_path = Path(self.watched_path)
            if watched_path.exists():
                if self._load_watched(self.watched_path):
                    logger.info(f"Loaded {len(self._seen_films)} films from watched CSV")
                    watched_loaded = True

        # Only try diary if watched.csv wasn't found or failed (from extracted ZIP)
        if not watched_loaded and self.diary_path:
            if Path(self.diary_path).exists():
                if self._load_diary(self.diary_path):
                    logger.info(f"Loaded {len(self._seen_films)} films from diary CSV")
                else:
                    logger.warning("Failed to load diary CSV")
            else:
                logger.warning(f"Diary CSV not found: {self.diary_path}")
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
        return self._do_not_watchlist_loader.is_on_do_not_watchlist(tmdb_title, tmdb_year)

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
            "do_not_watchlist_count": self._do_not_watchlist_loader.get_count(),
        }
