"""
Blob Configuration File Loader
Downloads configuration files from Azure Blob Storage with fallback to local files.
"""

import logging
from pathlib import Path
import tempfile

logger = logging.getLogger(__name__)

# Azure Blob Storage settings
AZURE_STORAGE_ACCOUNT = "ziggoepgletterboxd"
AZURE_CONTAINER_NAME = "data"
AZURE_BLOB_URL = f"https://{AZURE_STORAGE_ACCOUNT}.blob.core.windows.net/{AZURE_CONTAINER_NAME}/"


def download_config_file(blob_name: str, local_fallback_path: str) -> str:
    """
    Download a configuration file from Azure Blob Storage.
    Falls back to local file if download fails.
    
    Args:
        blob_name: Name of the blob in the data container (e.g., "channels.txt")
        local_fallback_path: Path to local file to use if blob download fails
    
    Returns:
        Path to the file to use (either downloaded temp file or local fallback)
    """
    try:
        from azure.storage.blob import BlobClient
        from azure.identity import DefaultAzureCredential
        
        logger.info(f"Attempting to download {blob_name} from Azure Blob Storage...")
        
        # Use DefaultAzureCredential - works with Managed Identity in Azure and Azure CLI locally
        credential = DefaultAzureCredential()
        
        # Create blob client
        blob_url = f"https://{AZURE_STORAGE_ACCOUNT}.blob.core.windows.net/{AZURE_CONTAINER_NAME}/{blob_name}"
        blob_client = BlobClient.from_blob_url(blob_url, credential=credential)
        
        # Download to temp file
        temp_dir = Path(tempfile.gettempdir())
        download_path = temp_dir / blob_name
        
        with open(download_path, "wb") as f:
            download_stream = blob_client.download_blob()
            f.write(download_stream.readall())
        
        logger.info(f"Downloaded {blob_name} from blob storage to {download_path}")
        return str(download_path)
        
    except ImportError:
        logger.info(f"Azure dependencies not available, using local {local_fallback_path}")
        return local_fallback_path
    except Exception as e:
        logger.info(f"Failed to download {blob_name} from blob storage: {e}")
        logger.info(f"Falling back to local {local_fallback_path}")
        return local_fallback_path
