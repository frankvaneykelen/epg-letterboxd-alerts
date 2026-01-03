"""
Test script to verify Ziggo EPG integration
"""
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

from classes.tvsystemio import ChannelFileIo
from classes.ziggoepggrabber import ZiggoGoEpgGrabber

def test_channel_list():
    """Test fetching channel list from Ziggo"""
    print("\n=== Testing Ziggo Channel List ===\n")
    
    try:
        tv_io = ChannelFileIo("data/channels.txt", "data/test.xml")
        grabber = ZiggoGoEpgGrabber(tv_io, 1, "ziggo-nl", "data/test_cache.db")
        
        channels = grabber.get_channel_list()
        
        print(f"\n✓ Successfully fetched {len(channels)} channels from Ziggo!\n")
        print("First 20 channels:")
        for i, channel in enumerate(channels[:20], 1):
            print(f"  {i}. {channel['name']}")
        
        print(f"\n... and {len(channels) - 20} more channels")
        print("\nYou can add any of these to data/channels.txt")
        
        return True
        
    except Exception as e:
        print(f"\n✗ Error: {e}\n")
        return False

if __name__ == "__main__":
    test_channel_list()
