"""
Upload HTML files to Azure Blob Storage.
"""

import logging
from pathlib import Path
from typing import Optional
from azure.storage.blob import ContentSettings

logger = logging.getLogger(__name__)

def upload_html_to_blob(html_content: str, blob_name: str, container_name: str = "$web") -> bool:
    """
    Upload HTML content to Azure Blob Storage.
    
    Args:
        html_content: The HTML content as a string
        blob_name: The blob name (e.g., 'index.html', 'new-series.html')
        container_name: The container name (default: '$web' for static website hosting)
    
    Returns:
        True if upload was successful, False otherwise
    """
    try:
        from azure.storage.blob import BlobClient
        from azure.identity import DefaultAzureCredential
        
        storage_account = "epgletterboxdprod"
        account_url = f"https://{storage_account}.blob.core.windows.net"
        
        # Create blob client with Managed Identity
        blob_client = BlobClient(
            account_url=account_url,
            container_name=container_name,
            blob_name=blob_name,
            credential=DefaultAzureCredential()
        )
        
        # Upload HTML content with proper content type
        blob_client.upload_blob(
            html_content.encode('utf-8'),
            overwrite=True,
            content_settings=ContentSettings(content_type='text/html; charset=utf-8')
        )
        
        logger.info(f"Successfully uploaded {blob_name} to blob storage container '{container_name}'")
        return True
        
    except ImportError:
        logger.error("Azure Storage libraries not available. Cannot upload to blob storage.")
        return False
    except Exception as e:
        logger.error(f"Failed to upload {blob_name} to blob storage: {e}")
        return False


def download_html_from_blob(blob_name: str, container_name: str = "$web") -> Optional[str]:
    """
    Download HTML content from Azure Blob Storage.
    
    Args:
        blob_name: The blob name (e.g., 'index.html', 'new-series.html')
        container_name: The container name (default: '$web' for static website hosting)
    
    Returns:
        HTML content as string, or None if download failed
    """
    try:
        from azure.storage.blob import BlobClient
        from azure.identity import DefaultAzureCredential
        
        storage_account = "epgletterboxdprod"
        account_url = f"https://{storage_account}.blob.core.windows.net"
        
        # Create blob client with Managed Identity
        blob_client = BlobClient(
            account_url=account_url,
            container_name=container_name,
            blob_name=blob_name,
            credential=DefaultAzureCredential()
        )
        
        # Download blob content
        blob_data = blob_client.download_blob()
        html_content = blob_data.readall().decode('utf-8')
        
        logger.info(f"Successfully downloaded {blob_name} from blob storage container '{container_name}'")
        return html_content
        
    except ImportError:
        logger.error("Azure Storage libraries not available. Cannot download from blob storage.")
        return None
    except Exception as e:
        logger.error(f"Failed to download {blob_name} from blob storage: {e}")
        return None
