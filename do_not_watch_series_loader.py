"""
Do-Not-Watch Series Table Storage Loader Module
Loads do-not-watch series from Azure Table Storage or local CSV fallback.
"""

import logging
import os
import csv
from pathlib import Path
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
    """Loads do-not-watch series from Azure Table Storage or local CSV."""

    def __init__(self, storage_account_name: str = "epgletterboxdprod", table_name: str = "DoNotWatchListSeries", csv_path: str = "data/do-not-watch-series.csv"):
        """
        Initialize loader.

        Args:
            storage_account_name: Azure Storage account name
            table_name: Table name (default: DoNotWatchListSeries)
            csv_path: Local CSV fallback path
        """
        self.storage_account_name = storage_account_name
        self.table_name = table_name
        self.csv_path = csv_path
        self._do_not_watch_series: Set[str] = set()
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
        
        logger.warning("No do-not-watch series data loaded")
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
                title = entity.get('Title', '').strip()
                if title:
                    self._do_not_watch_series.add(title.lower())
                    count += 1
            
            logger.info(f"Loaded {count} series from do-not-watch table")
            return True

        except Exception as e:
            logger.error(f"Error loading do-not-watch series from Table Storage: {e}")
            return False

    def _load_from_csv(self) -> bool:
        """Load from local CSV file."""
        try:
            csv_file = Path(self.csv_path)
            if not csv_file.exists():
                logger.debug(f"Do-not-watch series CSV not found: {self.csv_path}")
                return False

            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                count = 0
                for row in reader:
                    title = row.get('Title', '').strip()
                    if title:
                        self._do_not_watch_series.add(title.lower())
                        count += 1

            logger.info(f"Loaded {count} series from do-not-watch CSV")
            return True

        except Exception as e:
            logger.error(f"Error loading do-not-watch series CSV
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
