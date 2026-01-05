"""
Migration Script: Upload do-not-watchlist.csv to Azure Table Storage
One-time script to migrate existing CSV data to Table Storage.
"""

import csv
import sys
from pathlib import Path
from azure.data.tables import TableServiceClient
from azure.identity import DefaultAzureCredential

# Configuration
STORAGE_ACCOUNT_NAME = "epgletterboxdprod"
TABLE_NAME = "DoNotWatchListFilms"
CSV_PATH = "data/do-not-watchlist.csv"


def migrate_csv_to_table():
    """Upload CSV entries to Azure Table Storage."""
    
    # Check if CSV exists
    csv_file = Path(CSV_PATH)
    if not csv_file.exists():
        print(f"Error: CSV file not found at {CSV_PATH}")
        return False
    
    print(f"Reading CSV from {CSV_PATH}...")
    
    # Read CSV
    entries = []
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get('Name', '').strip()
            year_str = row.get('Year', '').strip()
            notes = (row.get('Notes') or '').strip()  # Handle None values
            
            if name and year_str:
                try:
                    year = int(year_str)
                    entries.append({
                        'Name': name,
                        'Year': year,
                        'Notes': notes
                    })
                except ValueError:
                    print(f"Warning: Invalid year '{year_str}' for {name}, skipping")
    
    print(f"Found {len(entries)} entries in CSV")
    
    if not entries:
        print("No valid entries to upload")
        return False
    
    # Connect to Table Storage
    print(f"\nConnecting to Azure Table Storage...")
    credential = DefaultAzureCredential()
    table_service_url = f"https://{STORAGE_ACCOUNT_NAME}.table.core.windows.net"
    table_service_client = TableServiceClient(endpoint=table_service_url, credential=credential)
    table_client = table_service_client.get_table_client(table_name=TABLE_NAME)
    
    # Upload entries
    print(f"\nUploading entries to table '{TABLE_NAME}'...")
    success_count = 0
    error_count = 0
    
    for entry in entries:
        try:
            # Create entity with PartitionKey and RowKey
            entity = {
                'PartitionKey': 'DoNotWatch',
                'RowKey': f"{entry['Name']}_{entry['Year']}",
                'Name': entry['Name'],
                'Year': entry['Year'],
                'Notes': entry['Notes']
            }
            
            # Upsert (insert or update if exists)
            table_client.upsert_entity(entity=entity)
            print(f"  ✓ {entry['Name']} ({entry['Year']})")
            success_count += 1
            
        except Exception as e:
            print(f"  ✗ Error uploading {entry['Name']}: {e}")
            error_count += 1
    
    print(f"\n{'='*60}")
    print(f"Migration complete!")
    print(f"  Success: {success_count}")
    print(f"  Errors:  {error_count}")
    print(f"{'='*60}")
    
    if success_count > 0:
        print(f"\nYou can now view/edit entries in Azure Portal:")
        print(f"  Storage Account: {STORAGE_ACCOUNT_NAME}")
        print(f"  Table: {TABLE_NAME}")
        print(f"  URL: https://portal.azure.com/#view/Microsoft_Azure_Storage/TableDataExplorer")
    
    return error_count == 0


if __name__ == "__main__":
    print("="*60)
    print("Do-Not-Watchlist CSV to Table Storage Migration")
    print("="*60)
    print()
    
    try:
        success = migrate_csv_to_table()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
