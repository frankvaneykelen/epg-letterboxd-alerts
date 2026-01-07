"""
Loader for skip categories from Azure Table Storage or local JSON fallback.
"""

import json
import logging
from pathlib import Path
from typing import Set
from azure.data.tables import TableServiceClient
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)


class SkipCategoriesLoader:
    """Load skip categories from Table Storage with JSON fallback."""
    
    def __init__(self, storage_account_name: str, table_name: str = "SkipCategories", 
                 fallback_file: str = "data/skip-categories.json"):
        """
        Initialize the loader.
        
        Args:
            storage_account_name: Azure Storage account name
            table_name: Table Storage table name
            fallback_file: Path to local JSON fallback file
        """
        self.storage_account_name = storage_account_name
        self.table_name = table_name
        self.fallback_file = Path(fallback_file)
        self._skip_categories: Set[str] = set()
    
    def load_data(self) -> bool:
        """
        Load skip categories from Table Storage or local JSON.
        
        Returns:
            True if data was loaded successfully, False otherwise
        """
        # Try Table Storage first
        if self._load_from_table():
            return True
        
        # Fall back to local JSON
        logger.warning("Falling back to local JSON file")
        return self._load_from_json()
    
    def _load_from_table(self) -> bool:
        """Load from Azure Table Storage."""
        try:
            credential = DefaultAzureCredential()
            table_service_url = f"https://{self.storage_account_name}.table.core.windows.net"
            table_service_client = TableServiceClient(endpoint=table_service_url, credential=credential)
            table_client = table_service_client.get_table_client(table_name=self.table_name)
            
            entities = table_client.query_entities("PartitionKey eq 'SkipCategory'")
            
            count = 0
            skipped = 0
            for entity in entities:
                category = entity.get('RowKey', '').strip()
                if category:
                    self._skip_categories.add(category)
                    count += 1
                    logger.debug(f"  Loaded skip category: {category}")
                else:
                    skipped += 1
                    logger.warning(f"  Skipped entity with empty RowKey: {entity}")
            
            if skipped > 0:
                logger.warning(f"Skipped {skipped} entities with empty RowKeys")
            logger.info(f"Loaded {count} skip categories from Table Storage")
            return True

        except Exception as e:
            logger.error(f"Error loading skip categories from Table Storage: {e}")
            return False
    
    def _load_from_json(self) -> bool:
        """Load from local JSON file."""
        try:
            if not self.fallback_file.exists():
                logger.error(f"Fallback file not found: {self.fallback_file}")
                return False
            
            with open(self.fallback_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            categories = data.get('categories', [])
            if not isinstance(categories, list):
                logger.error(f"Invalid JSON format: 'categories' must be a list")
                return False
            
            self._skip_categories = set(cat.strip() for cat in categories if cat.strip())
            logger.info(f"Loaded {len(self._skip_categories)} skip categories from JSON")
            return True
            
        except Exception as e:
            logger.error(f"Error loading skip categories from JSON: {e}")
            return False
    
    def should_skip(self, categories: list[str]) -> bool:
        """
        Check if any of the given categories should be skipped.
        
        Args:
            categories: List of category names to check
            
        Returns:
            True if any category matches skip list
        """
        return any(cat in self._skip_categories for cat in categories)
    
    def get_categories(self) -> Set[str]:
        """Get the set of skip categories."""
        return self._skip_categories.copy()
