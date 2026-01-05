"""
Do-Not-Watchlist Table Storage Loader Module
Loads do-not-watch films from Azure Table Storage.
"""

import logging
import os
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
    """Loads do-not-watch films from Azure Table Storage."""

    def __init__(self, storage_account_name: str = "epgletterboxdprod", table_name: str = "DoNotWatchListFilms"):
        """
        Initialize Table Storage loader.

        Args:
            storage_account_name: Azure Storage account name
            table_name: Table name (default: DoNotWatchListFilms)
        """
        self.storage_account_name = storage_account_name
        self.table_name = table_name
        self._do_not_watchlist_films: Set[tuple] = set()
        self._loaded = False

    def load_data(self) -> bool:
        """
        Load do-not-watchlist from Azure Table Storage.

        Returns:
            True if data was loaded successfully, False otherwise
        """
        if self._loaded:
            return True

        try:
            # Use Managed Identity in Azure, fallback to Azure CLI credentials locally
            credential = DefaultAzureCredential()
            
            # Create Table Service client
            table_service_url = f"https://{self.storage_account_name}.table.core.windows.net"
            table_service_client = TableServiceClient(endpoint=table_service_url, credential=credential)
            
            # Get table client
            table_client = table_service_client.get_table_client(table_name=self.table_name)
            
            # Query all entities (single partition, so this is efficient)
            entities = table_client.query_entities("PartitionKey eq 'DoNotWatch'")
            
            # Load into memory as (title, year) tuples
            count = 0
            for entity in entities:
                name = entity.get('Name', '').strip()
                year = entity.get('Year')
                
                if name and year:
                    self._do_not_watchlist_films.add((name, int(year)))
                    count += 1
            
            self._loaded = True
            logger.info(f"Loaded {count} films from do-not-watchlist table")
            return True

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
