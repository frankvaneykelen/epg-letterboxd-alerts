"""
Letterboxd ZIP Import Utility
Automatically extracts the latest Letterboxd export ZIP from Azure Blob Storage
or Downloads folder, and copies CSV files to the data/ folder.
"""

import os
import zipfile
import shutil
from pathlib import Path
from datetime import datetime
import logging
import tempfile

logger = logging.getLogger(__name__)

# Azure Blob Storage settings
AZURE_STORAGE_ACCOUNT = "epgletterboxdprod"
AZURE_CONTAINER_NAME = "downloads"
AZURE_BLOB_URL = f"https://{AZURE_STORAGE_ACCOUNT}.blob.core.windows.net/{AZURE_CONTAINER_NAME}/"


# Detect if running in Azure
def is_azure_environment():
    """Check if running in Azure Functions environment."""
    return (
        os.getenv('FUNCTIONS_WORKER_RUNTIME') is not None or
        os.getenv('WEBSITE_INSTANCE_ID') is not None or
        os.getenv('WEBSITE_SITE_NAME') is not None
    )

def get_output_folder():
    """Get appropriate output folder based on environment."""
    if is_azure_environment():
        return "/tmp"
    return "data"


def download_from_blob_storage() -> Path | None:
    """
    Download the latest Letterboxd ZIP from Azure Blob Storage.
    Uses DefaultAzureCredential for authentication (Managed Identity in Azure, Azure CLI locally).
    
    Returns:
        Path to downloaded ZIP file or None if failed
    """
    try:
        from azure.storage.blob import ContainerClient
        from azure.identity import DefaultAzureCredential
        from azure.core.exceptions import ResourceNotFoundError
        
        logger.info("Checking Azure Blob Storage for Letterboxd exports...")
        
        # Use DefaultAzureCredential - works with Managed Identity in Azure and Azure CLI locally
        credential = DefaultAzureCredential()
        
        # Create container client with authentication
        container_client = ContainerClient(
            account_url=f"https://{AZURE_STORAGE_ACCOUNT}.blob.core.windows.net",
            container_name=AZURE_CONTAINER_NAME,
            credential=credential
        )
        
        # List all letterboxd ZIP files
        letterboxd_blobs = []
        for blob in container_client.list_blobs(name_starts_with="letterboxd-"):
            if blob.name.endswith('.zip'):
                letterboxd_blobs.append(blob)
        
        if not letterboxd_blobs:
            logger.info("No Letterboxd ZIPs found in Azure Blob Storage")
            return None
        
        # Find the latest blob by last_modified time
        latest_blob = max(letterboxd_blobs, key=lambda b: b.last_modified)
        logger.info(f"Found latest blob: {latest_blob.name} (modified: {latest_blob.last_modified})")
        
        # Download to temp file
        temp_dir = Path(tempfile.gettempdir())
        download_path = temp_dir / latest_blob.name
        
        logger.info(f"Downloading {latest_blob.name} from blob storage...")
        blob_client = container_client.get_blob_client(latest_blob.name)
        
        with open(download_path, "wb") as f:
            download_stream = blob_client.download_blob()
            f.write(download_stream.readall())
        
        logger.info(f"Downloaded to {download_path}")
        return download_path
        
    except ImportError:
        logger.warning("azure-storage-blob or azure-identity not installed, skipping blob storage check")
        return None
    except ResourceNotFoundError:
        logger.warning("Azure Blob Storage container not found or not accessible")
        return None
    except Exception as e:
        logger.warning(f"Failed to download from blob storage: {e}")
        return None


def find_latest_letterboxd_zip(downloads_folder: str = None) -> Path | None:
    """
    Find the most recent Letterboxd ZIP file in Downloads folder.

    Args:
        downloads_folder: Path to Downloads folder (defaults to 'downloads' in repo root)

    Returns:
        Path to the latest ZIP file or None if not found
    """
    if downloads_folder is None:
        # Default to downloads folder in repo root
        downloads_path = Path("downloads")
        if not downloads_path.exists():
            logger.error(f"Downloads folder not found: {downloads_path.absolute()}")
            return None
    else:
        downloads_path = Path(downloads_folder)
        if not downloads_path.exists():
            logger.error(f"Downloads folder not found: {downloads_folder}")
            return None

    # Find all Letterboxd ZIP files
    letterboxd_zips = list(downloads_path.glob("letterboxd-*.zip"))
    
    if not letterboxd_zips:
        logger.warning("No Letterboxd ZIP files found in Downloads")
        return None

    # Sort by modification time (most recent first)
    latest_zip = max(letterboxd_zips, key=lambda p: p.stat().st_mtime)
    
    logger.info(f"Found latest Letterboxd ZIP: {latest_zip.name}")
    return latest_zip


def extract_letterboxd_csvs(zip_path: Path, output_folder: str = "data") -> bool:
    """
    Extract CSV files from Letterboxd ZIP to data folder.

    Args:
        zip_path: Path to the Letterboxd ZIP file
        output_folder: Destination folder for CSV files (default: 'data')

    Returns:
        True if extraction was successful, False otherwise
    """
    output_path = Path(output_folder)
    output_path.mkdir(exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # List all files in the ZIP
            all_files = zip_ref.namelist()
            logger.info(f"ZIP contains {len(all_files)} files")

            # Files we want to extract
            target_files = ['diary.csv', 'watched.csv', 'watchlist.csv']
            extracted_count = 0

            for file_name in all_files:
                # Get the base filename (in case files are in subdirectories)
                base_name = os.path.basename(file_name)
                
                # Only extract files from the root directory (no subdirectories)
                if base_name in target_files and '/' not in file_name.rstrip('/'):
                    # Extract to temp location first
                    zip_ref.extract(file_name, output_path)
                    
                    # If file was in a subdirectory, move it to the root of data/
                    extracted_file = output_path / file_name
                    target_file = output_path / base_name
                    
                    if extracted_file != target_file:
                        shutil.move(str(extracted_file), str(target_file))
                        # Clean up empty subdirectories
                        try:
                            extracted_file.parent.rmdir()
                        except OSError:
                            pass
                    
                    logger.info(f"Extracted: {base_name}")
                    extracted_count += 1

            if extracted_count == 0:
                logger.warning("No CSV files found in ZIP")
                return False

            logger.info(f"Successfully extracted {extracted_count} CSV file(s) to {output_folder}/")
            return True

    except zipfile.BadZipFile:
        logger.error(f"Invalid ZIP file: {zip_path}")
        return False
    except Exception as e:
        logger.error(f"Error extracting ZIP: {e}")
        return False


def import_latest_letterboxd_export(downloads_folder: str = None, output_folder: str = None) -> bool:
    """
    Find and extract the latest Letterboxd export from Azure Blob Storage or Downloads.

    Args:
        downloads_folder: Path to Downloads folder (optional, used as fallback)
        output_folder: Destination folder for CSV files (default: auto-detected based on environment)

    Returns:
        True if import was successful, False otherwise
    """
    # Auto-detect output folder if not specified
    if output_folder is None:
        output_folder = get_output_folder()
    
    logger.info(f"Searching for latest Letterboxd export... (will extract to: {output_folder})")
    
    # Try Azure Blob Storage first
    zip_path = download_from_blob_storage()
    
    # Fallback to local downloads folder
    if not zip_path:
        logger.info("Falling back to local downloads folder...")
        zip_path = find_latest_letterboxd_zip(downloads_folder)
    
    if not zip_path:
        logger.error("No Letterboxd ZIP found in blob storage or downloads folder")
        return False

    # Extract CSVs
    success = extract_letterboxd_csvs(zip_path, output_folder)
    
    # Clean up temp file if downloaded from blob storage
    if zip_path.parent == Path(tempfile.gettempdir()):
        try:
            zip_path.unlink()
            logger.info(f"Cleaned up temporary file: {zip_path}")
        except Exception as e:
            logger.warning(f"Failed to clean up temp file: {e}")
    
    if success:
        logger.info("Letterboxd data import completed successfully!")
    else:
        logger.error("Failed to import Letterboxd data")
    
    return success


if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run import
    success = import_latest_letterboxd_export()
    
    if success:
        print("\n✓ Letterboxd CSV files imported to data/ folder")
        print("  - diary.csv")
        print("  - watched.csv")
        print("  - watchlist.csv")
    else:
        print("\n✗ Failed to import Letterboxd data")
        print("  Make sure you have:")
        print("  1. A letterboxd-*.zip file in Azure Blob Storage (https://epgletterboxdprod.blob.core.windows.net/downloads/), OR")
        print("  2. A letterboxd-*.zip file in your downloads/ folder")
