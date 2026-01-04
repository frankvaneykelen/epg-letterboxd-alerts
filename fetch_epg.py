"""
Fetch EPG data from Ziggo
Universal EPG fetcher for both film and series channel lists
"""
import logging
import argparse
import os
from pathlib import Path
from classes.tvsystemio import ChannelFileIo
from classes.ziggoepggrabber import ZiggoGoEpgGrabber

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def fetch_epg(channel_file="data/channels.txt", output_file="data/ziggogo.xml", scan_days=7):
    """
    Fetch EPG from Ziggo and save to XMLTV file
    
    Args:
        channel_file: Path to channel list file
        output_file: Path to output XMLTV file
        scan_days: Number of days to fetch (default: 7)
    """
    print("\n=== Fetching EPG from Ziggo ===\n")
    print(f"Channel list: {channel_file}")
    print(f"Output file:  {output_file}")
    print(f"Scan days:    {scan_days}")
    print("\nThis may take several minutes...\n")
    
    # Determine database file path (use /tmp in Azure)
    is_azure = (os.environ.get('WEBSITE_INSTANCE_ID') or 
               os.environ.get('WEBSITE_SITE_NAME') or 
               os.environ.get('FUNCTIONS_WORKER_RUNTIME'))
    
    if is_azure:
        database_file = "/tmp/ziggogoepg_cache.sqlite3"
        # Also adjust output file to /tmp if it's in data/
        if output_file.startswith("data/"):
            output_file = f"/tmp/{Path(output_file).name}"
        print(f"Running in Azure - using /tmp for database: {database_file}")
        
        # Download cache from blob storage if it exists
        try:
            from blob_config_loader import download_config_file
            downloaded_cache = download_config_file("ziggogoepg_cache.sqlite3", database_file)
            if Path(downloaded_cache).exists():
                print(f"Downloaded SQLite cache from blob storage ({Path(downloaded_cache).stat().st_size} bytes)")
        except Exception as e:
            print(f"Could not download cache: {e}")
    else:
        database_file = "data/ziggogoepg_cache.sqlite3"
    
    try:
        tv_io = ChannelFileIo(
            channel_list_filename=channel_file,
            xmltv_filename=output_file
        )
        
        grabber = ZiggoGoEpgGrabber(
            tv_io,
            scan_days=scan_days,
            configuration_file="ziggo-nl",
            database_file=database_file
        )
        
        print("Fetching EPG data...")
        grabber.grab()
        
        # Upload cache back to blob storage (in Azure)
        if is_azure:
            try:
                from azure.storage.blob import BlobClient
                from azure.identity import DefaultAzureCredential
                
                storage_account = "epgletterboxdprod"
                account_url = f"https://{storage_account}.blob.core.windows.net"
                
                blob_client = BlobClient(
                    account_url=account_url,
                    container_name="data",
                    blob_name="ziggogoepg_cache.sqlite3",
                    credential=DefaultAzureCredential()
                )
                
                with open(database_file, 'rb') as cache_file:
                    blob_client.upload_blob(cache_file, overwrite=True)
                
                cache_size = Path(database_file).stat().st_size
                print(f"Uploaded SQLite cache to blob storage ({cache_size} bytes)")
            except Exception as e:
                print(f"Could not upload cache: {e}")
        
        print("\n✓ Successfully fetched EPG data!")
        print(f"  Output: {output_file}")
        print(f"  Cache:  {database_file}")
        
        return True
        
    except Exception as e:
        print(f"\n✗ Error: {e}\n")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch EPG data from Ziggo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fetch for film channels (default)
  python fetch_epg.py
  
  # Fetch for TV series channels
  python fetch_epg.py --series
  
  # Custom channel list and output
  python fetch_epg.py -c data/my-channels.txt -o data/my-epg.xml
        """
    )
    
    parser.add_argument(
        "-c", "--channels",
        default="data/channels.txt",
        help="Channel list file (default: data/channels.txt)"
    )
    
    parser.add_argument(
        "-o", "--output",
        default="data/ziggogo.xml",
        help="Output XMLTV file (default: data/ziggogo.xml)"
    )
    
    parser.add_argument(
        "-d", "--days",
        type=int,
        default=7,
        help="Number of days to fetch (default: 7)"
    )
    
    parser.add_argument(
        "--series",
        action="store_true",
        help="Use series channel list and output (channels-series.txt → ziggogo-series.xml)"
    )
    
    args = parser.parse_args()
    
    # Override with series defaults if --series flag is used
    if args.series:
        channel_file = "data/channels-series.txt"
        output_file = "data/ziggogo-series.xml"
    else:
        channel_file = args.channels
        output_file = args.output
    
    fetch_epg(channel_file, output_file, args.days)
