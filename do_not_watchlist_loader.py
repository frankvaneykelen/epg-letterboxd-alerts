"""
Do-Not-Watchlist Table Storage Loader Module
Loads do-not-watch films from Azure Table Storage or local CSV fallback.
"""

import logging
import os
import csv
from pathlib import Path
from typing import Set, Optional
from azure.data.tables import TableServiceClient
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)


def is_azure_environment():
    """Check if running in Azure Functions environment."""
    return (
        os.getenv('FUNCTIONS_WORKER_RUNTIME') is not None or
        os.getenv('WEBSITE_INSTANCE_ID') is not None or
        os.getenv('WEBSITE_SITE_NAME') is not None
    )


class DoNotWatchListLoader:
    """Loads do-not-watch films from Azure Table Storage or local CSV."""

    def __init__(self, storage_account_name: str = "epgletterboxdprod", table_name: str = "DoNotWatchListFilms", csv_path: str = "data/do-not-watchlist.csv"):
        """
        Initialize loader.

        Args:
            storage_account_name: Azure Storage account name
            table_name: Table name (default: DoNotWatchListFilms)
            csv_path: Local CSV fallback path
        """
        self.storage_account_name = storage_account_name
        self.table_name = table_name
        self.csv_path = csv_path
        self._do_not_watchlist_films: Set[tuple] = set()
        self._loaded = False

    def load_data(self) -> bool: or local CSV.
        
        In Azure: loads from Table Storage
        Locally: loads from CSV file

        Returns:
            True if data was loaded successfully, False otherwise
        """
        if self._loaded:
            return True

        # Try Azure Table Storage first (if in Azure environment)
        if is_azure_environment():
            if self._load_from_table():
                self._loaded = True
                return True
            logger.warning("Failed to load from Table Storage, falling back to CSV")
        
        # Fallback to local CSV
        if self._load_from_csv():
            self._loaded = True
            return True
        
        logger.warning("No do-not-watchlist data loaded")
        return False

    def _load_from_table(self) -> bool:
        """Load from Azure Table Storage."""
        try:
            credential = DefaultAzureCredential()
            table_service_url = f"https://{self.storage_account_name}.table.core.windows.net"
            table_service_client = TableServiceClient(endpoint=table_service_url, credential=credential)
            table_client = table_service_client.get_table_client(table_name=self.table_name)
            
            entities = table_client.query_entities("PartitionKey eq 'DoNotWatch'")
            
            count = 0
            for entity in entities:
                name = entity.get('Name', '').strip()
                year = entity.get('Year')
                
                if name and year:
                    self._do_not_watchlist_films.add((name, int(year)))
                    count += 1
            
            logger.info(f"Loaded {count} films from do-not-watchlist table")
            return True

        except Exception as e:
            logger.error(f"Error loading do-not-watchlist from Table Storage: {e}")
            return False

    def _load_from_csv(self) -> bool:
        """Load from local CSV file."""
        try:
            csv_file = Path(self.csv_path)
            if not csv_file.exists():
                logger.debug(f"Do-not-watchlist CSV not found: {self.csv_path}")
                return False

            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                count = 0
                for row in reader:
                    name = row.get('Name', '').strip()
                    year_str = row.get('Year', '').strip()
                    
                    if name and year_str:
                        try:
                            year = int(year_str)
                            self._do_not_watchlist_films.add((name, year))
                            count += 1
                        except ValueError:
                            logger.warning(f"Invalid year in do-not-watchlist: {year_str} for {name}")

            logger.info(f"Loaded {count} films from do-not-watchlist CSV")
            return True

        except Exception as e:
            logger.error(f"Error loading do-not-watchlist CSV
        except Exception as e:
            logger.error(f"Error loading do-not-watchlist from Table Storage: {e}")
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

    def get_count(self) -> int:
        """
        Get count of films in do-not-watchlist.

        Returns:
            Number of films
        """
        if not self._loaded:
            self.load_data()
        return len(self._do_not_watchlist_films)
