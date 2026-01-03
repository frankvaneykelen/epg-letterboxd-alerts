"""
TV System IO for EPG-Letterboxd Alerts
Simple file-based implementation for ziggogo-epg integration
"""

import logging
from typing import List
from pathlib import Path

logger = logging.getLogger(__name__)


class TVSystemIoException(Exception):
    """Failure interacting with TV system"""


class TVSystemIo:
    """Base class used for getting the channel list and writing out the EPG"""

    def get_channel_list(self) -> List[str]:
        """Get the list of channels to grab the EPG for"""
        raise NotImplementedError()

    def write_xmltv(self, data: bytes):
        """Write the XMLTV EPG to storage"""
        raise NotImplementedError()


class ChannelFileIo(TVSystemIo):
    """Class used to read channel list from file and write XMLTV file"""

    def __init__(self, channel_list_filename: str = "data/channels.txt", xmltv_filename: str = "data/ziggogo.xml"):
        """Initialize the ChannelFileIo class"""
        self._channel_list_filename = channel_list_filename
        self._xmltv_filename = xmltv_filename

    def get_channel_list(self) -> List[str]:
        """Get the list of channels from the channel list file"""
        channel_path = Path(self._channel_list_filename)
        
        if not channel_path.exists():
            logger.warning(f"Channel list file not found: {self._channel_list_filename}")
            # Return empty list - ziggogo-epg will grab all channels
            return []

        logger.info(f"Reading known channel list from '{self._channel_list_filename}'...")

        try:
            with open(channel_path, "r", encoding="utf-8") as f:
                channellist = []
                for line in f:
                    channel = line.strip()
                    if channel and not channel.startswith("#"):  # Skip comments
                        channellist.append(channel)
            logger.info(f"Loaded {len(channellist)} channels from file")
            return channellist

        except OSError as e:
            raise TVSystemIoException(
                f"Error reading '{self._channel_list_filename}'. Does the file exist and is it readable? Error: {e}"
            )

    def write_xmltv(self, data: bytes):
        """Write the XMLTV EPG to file"""
        xmltv_path = Path(self._xmltv_filename)
        xmltv_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Writing XMLTV to '{self._xmltv_filename}'...")

        try:
            with open(xmltv_path, "wb") as f:
                f.write(data)
            logger.info(f"XMLTV file written successfully ({len(data)} bytes)")

        except OSError as e:
            raise TVSystemIoException(
                f"Error writing XMLTV to '{self._xmltv_filename}'. Is the path correct and is it writable? Error: {e}"
            )
