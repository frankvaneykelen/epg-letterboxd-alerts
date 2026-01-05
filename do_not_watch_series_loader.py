"""
Do-Not-Watch Series Table Storage Loader Module
Loads do-not-watch series from Azure Table Storage (title-only, no year).
"""

import logging
import os
from typing import Set
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


class DoNotWatchSeriesLoader:
    """Loads do-not-watch series from Azure Table Storage."""

    def __init__(self, storage_account_name: str = "epgletterboxdprod", table_name: str = "DoNotWatchListSeries"):
        """
        Initialize Table Storage loader.

        Args:
            storage_account_name: Azure Storage account name
            table_name: Table name (default: DoNotWatchListSeries)
        """
        self.storage_account_name = storage_account_name
        self.table_name = table_name
        self._do_not_watch_series: Set[str] = set()
        self._loaded = False

    def load_data(self) -> bool:
        """
        Load do-not-watch series from Azure Table Storage.

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
            
            # Load into memory as title set (case-insensitive)
            count = 0
            for entity in entities:
                title = entity.get('Title', '').strip()
                
                if title:
                    # Store in lowercase for case-insensitive matching
                    self._do_not_watch_series.add(title.lower())
                    count += 1
            
            self._loaded = True
            logger.info(f"Loaded {count} series from do-not-watch table")
            return True

        except Exception as e:
            logger.error(f"Error loading do-not-watch series from Table Storage: {e}")
            return False

    def is_on_do_not_watch_list(self, title: str) -> bool:
        """
        Check if a series is on the do-not-watch list by title (case-insensitive).

        Args:
            title: Series title

        Returns:
            True if on do-not-watch list, False otherwise
        """
        if not self._loaded:
            self.load_data()
        
        return title.lower() in self._do_not_watch_series

    def get_count(self) -> int:
        """
        Get count of series in do-not-watch list.

        Returns:
            Number of series
        """
        if not self._loaded:
            self.load_data()
        return len(self._do_not_watch_series)
