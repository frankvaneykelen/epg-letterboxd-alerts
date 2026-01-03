"""
Letterboxd ZIP Import Utility
Automatically extracts the latest Letterboxd export ZIP from Downloads
and copies CSV files to the data/ folder.
"""

import os
import zipfile
import shutil
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


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


def import_latest_letterboxd_export(downloads_folder: str = None, output_folder: str = "data") -> bool:
    """
    Find and extract the latest Letterboxd export from Downloads.

    Args:
        downloads_folder: Path to Downloads folder (optional)
        output_folder: Destination folder for CSV files (default: 'data')

    Returns:
        True if import was successful, False otherwise
    """
    logger.info("Searching for latest Letterboxd export...")
    
    # Find the latest ZIP
    zip_path = find_latest_letterboxd_zip(downloads_folder)
    if not zip_path:
        return False

    # Extract CSVs
    success = extract_letterboxd_csvs(zip_path, output_folder)
    
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
        print("  Make sure you have a letterboxd-*.zip file in your Downloads folder")
