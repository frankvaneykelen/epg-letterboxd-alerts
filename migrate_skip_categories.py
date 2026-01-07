#!/usr/bin/env python3
"""
Migrate skip categories from JSON file to Azure Table Storage.
"""

import json
import sys
from pathlib import Path
from azure.data.tables import TableServiceClient
from azure.identity import DefaultAzureCredential

# Configuration
STORAGE_ACCOUNT_NAME = "ziggoepgletterboxd"
TABLE_NAME = "SkipCategories"
JSON_FILE = Path("data/skip-categories.json")


def migrate():
    """Migrate skip categories from JSON to Table Storage."""
    
    # Load JSON file
    print(f"Loading skip categories from {JSON_FILE}...")
    if not JSON_FILE.exists():
        print(f"Error: File not found: {JSON_FILE}")
        return False
    
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error loading JSON: {e}")
        return False
    
    categories = data.get('categories', [])
    if not isinstance(categories, list):
        print("Error: 'categories' must be a list")
        return False
    
    # Filter valid entries
    entries = []
    for category in categories:
        category = category.strip()
        if not category:
            continue
        entries.append({
            'Category': category
        })
    
    print(f"Found {len(entries)} valid categories")
    
    if not entries:
        print("No valid categories to upload")
        return False
    
    # Connect to Table Storage
    print(f"\nConnecting to Azure Table Storage...")
    credential = DefaultAzureCredential()
    table_service_url = f"https://{STORAGE_ACCOUNT_NAME}.table.core.windows.net"
    table_service_client = TableServiceClient(endpoint=table_service_url, credential=credential)
    table_client = table_service_client.get_table_client(table_name=TABLE_NAME)
    
    # Create table if it doesn't exist
    try:
        table_service_client.create_table_if_not_exists(table_name=TABLE_NAME)
        print(f"Table '{TABLE_NAME}' ready")
    except Exception as e:
        print(f"Warning: Could not ensure table exists: {e}")
    
    # Upload entries
    print(f"\nUploading categories to table '{TABLE_NAME}'...")
    success_count = 0
    error_count = 0
    
    for entry in entries:
        try:
            # Create entity with PartitionKey and RowKey
            # RowKey is the category name itself
            entity = {
                'PartitionKey': 'SkipCategory',
                'RowKey': entry['Category']
            }
            
            # Upsert (insert or update if exists)
            table_client.upsert_entity(entity=entity)
            print(f"  ✓ {entry['Category']}")
            success_count += 1
            
        except Exception as e:
            print(f"  ✗ Error uploading {entry['Category']}: {e}")
            error_count += 1
    
    # Summary
    print(f"\n{'='*60}")
    print(f"Migration complete!")
    print(f"  Success: {success_count}")
    print(f"  Errors:  {error_count}")
    print(f"{'='*60}")
    
    return error_count == 0


if __name__ == "__main__":
    success = migrate()
    sys.exit(0 if success else 1)
