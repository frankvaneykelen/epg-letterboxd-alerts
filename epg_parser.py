"""
EPG Parser Module
Parses Ziggo XMLTV EPG using ziggogo-epg library
"""

import logging
from typing import List, Dict, Any
from datetime import datetime
from xml.etree import ElementTree as ET
from pathlib import Path

from classes.tvsystemio import ChannelFileIo
from classes.ziggoepggrabber import ZiggoGoEpgGrabber, GrabException
from blob_config_loader import download_config_file

logger = logging.getLogger(__name__)


class EPGBroadcast:
    """Represents a single EPG broadcast."""

    def __init__(
        self,
        channel: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        description: str = "",
        language: str = "",
        subtitles: bool = False,
        categories: List[str] = None,
        channel_name: str = "",
        director: str = "",
        date: str = "",
        actors: List[str] = None,
        country: str = "",
        subtitle: str = "",
        channel_icon: str = "",
    ):
        self.channel = channel
        self.title = title
        self.start_time = start_time
        self.end_time = end_time
        self.description = description
        self.language = language
        self.subtitles = subtitles
        self.categories = categories or []
        self.channel_name = channel_name
        self.director = director
        self.date = date
        self.actors = actors or []
        self.country = country
        self.subtitle = subtitle
        self.channel_icon = channel_icon

    def __repr__(self) -> str:
        return f"EPGBroadcast({self.channel}, {self.title}, {self.start_time})"


class EPGParser:
    """Parses XMLTV EPG using ziggogo-epg library."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize EPG parser.

        Args:
            config: Configuration dictionary with 'ziggo' section
        """
        self.config = config.get("ziggo", {})
        self.channel_file = self.config.get("channel_file", "data/channels.txt")
        self.xmltv_file = self.config.get("xmltv_file", "data/ziggogo.xml")
        self.database_file = self.config.get("database_file", "data/ziggogoepg_cache.sqlite3")
        self.scan_days = self.config.get("scan_days", 14)
        self.configuration = self.config.get("configuration", "ziggo-nl")

    def fetch_epg(self) -> str:
        """
        Fetch XMLTV EPG using ziggogo-epg library.

        Returns:
            Path to generated XMLTV file

        Raises:
            GrabException: If grab fails
        """
        logger.info("Fetching EPG from Ziggo using ziggogo-epg library...")
        
        # Download channel file from blob storage with fallback to local
        blob_filename = Path(self.channel_file).name
        channel_file_path = download_config_file(blob_filename, self.channel_file)
        
        try:
            # In Azure Functions, use /tmp for writable storage
            import os
            if os.environ.get('WEBSITE_INSTANCE_ID'):  # Running in Azure
                # Use /tmp for database (only writable location in Azure Functions)
                database_file = f"/tmp/{Path(self.database_file).name}"
                xmltv_file = f"/tmp/{Path(self.xmltv_file).name}"
                logger.info(f"Running in Azure - using /tmp for SQLite: {database_file}")
            else:
                # Local development - use configured paths
                database_file = self.database_file
                xmltv_file = self.xmltv_file
                logger.info(f"Running locally - using configured paths: {database_file}")
            
            # Setup file-based IO
            tv_system_io = ChannelFileIo(
                channel_list_filename=channel_file_path,
                xmltv_filename=xmltv_file
            )

            # Create grabber instance
            grabber = ZiggoGoEpgGrabber(
                tv_system_io=tv_system_io,
                scan_days=self.scan_days,
                configuration_file=self.configuration,
                database_file=database_file,
                timezone=None  # Use config default
            )

            # Perform grab
            grabber.grab(generate_only=False)
            
            # Return path to XMLTV file
            return xmltv_file

        except GrabException as e:
            logger.error(f"Failed to fetch EPG: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching EPG: {e}")
            raise GrabException(f"EPG fetch failed: {e}")


    def parse_xmltv(self, xmltv_file_path: str) -> List[EPGBroadcast]:
        """
        Parse XMLTV file and extract broadcasts.

        Args:
            xmltv_file_path: Path to XMLTV file

        Returns:
            List of EPGBroadcast objects
        """
        broadcasts = []
        try:
            # Read XMLTV file
            xmltv_path = Path(xmltv_file_path)
            if not xmltv_path.exists():
                logger.error(f"XMLTV file not found: {xmltv_file_path}")
                return broadcasts

            tree = ET.parse(xmltv_path)
            root = tree.getroot()
            
            # Build channel ID to name and icon mapping
            channel_map = {}
            icon_map = {}
            for channel in root.findall("channel"):
                channel_id = channel.get("id", "")
                display_name = channel.find("display-name")
                if display_name is not None and display_name.text:
                    channel_map[channel_id] = display_name.text
                icon_elem = channel.find("icon")
                if icon_elem is not None:
                    icon_map[channel_id] = icon_elem.get("src", "")
            
            for programme in root.findall("programme"):
                broadcast = self._parse_programme(programme, channel_map, icon_map)
                if broadcast:
                    broadcasts.append(broadcast)
            logger.info(f"Parsed {len(broadcasts)} broadcasts from EPG")
        except ET.ParseError as e:
            logger.error(f"Failed to parse XMLTV: {e}")
            raise

        return broadcasts

    def _parse_programme(self, prog_element: ET.Element, channel_map: Dict[str, str], icon_map: Dict[str, str]) -> EPGBroadcast | None:
        """
        Parse a single programme element from XMLTV.

        Args:
            prog_element: XML element containing programme data
            channel_map: Mapping of channel IDs to display names
            icon_map: Mapping of channel IDs to icon URLs

        Returns:
            EPGBroadcast object or None if parsing fails
        """
        try:
            channel = prog_element.get("channel", "")
            start = prog_element.get("start", "")
            end = prog_element.get("stop", "")

            title_elem = prog_element.find("title")
            title = title_elem.text if title_elem is not None else ""

            subtitle_elem = prog_element.find("sub-title")
            subtitle = subtitle_elem.text if subtitle_elem is not None else ""

            desc_elem = prog_element.find("desc")
            description = desc_elem.text if desc_elem is not None else ""

            # Extract categories
            categories = []
            for cat_elem in prog_element.findall("category"):
                if cat_elem.text:
                    categories.append(cat_elem.text)

            # Extract credits (director and actors)
            director = ""
            actors = []
            credits_elem = prog_element.find("credits")
            if credits_elem is not None:
                director_elem = credits_elem.find("director")
                if director_elem is not None and director_elem.text:
                    director = director_elem.text
                
                for actor_elem in credits_elem.findall("actor"):
                    if actor_elem.text:
                        actors.append(actor_elem.text)
            
            # Extract date
            date_elem = prog_element.find("date")
            date = date_elem.text if date_elem is not None and date_elem.text else ""
            
            # Extract country
            country_elem = prog_element.find("country")
            country = country_elem.text if country_elem is not None and country_elem.text else ""

            # Extract language and subtitle info
            language = ""
            subtitles = False
            for elem in prog_element.findall("*/"):
                if elem.tag == "lang":
                    language = elem.text or ""
                elif elem.tag == "subtitles":
                    subtitles = True

            start_time = self._parse_time(start)
            end_time = self._parse_time(end)

            if not all([channel, title, start_time, end_time]):
                return None

            # Get channel name and icon from mapping
            channel_name = channel_map.get(channel, channel)
            channel_icon = icon_map.get(channel, "")

            return EPGBroadcast(
                channel=channel,
                title=title,
                start_time=start_time,
                end_time=end_time,
                description=description,
                language=language,
                subtitles=subtitles,
                categories=categories,
                channel_name=channel_name,
                director=director,
                date=date,
                actors=actors,
                country=country,
                subtitle=subtitle,
                channel_icon=channel_icon,
            )
        except (AttributeError, ValueError) as e:
            logger.warning(f"Failed to parse programme element: {e}")
            return None

    @staticmethod
    def _parse_time(time_str: str) -> datetime | None:
        """
        Parse XMLTV time format (YYYYMMDDHHmmss +HHMM).

        Args:
            time_str: Time string in XMLTV format

        Returns:
            datetime object or None if parsing fails
        """
        try:
            # Extract the datetime part (first 14 chars)
            if len(time_str) < 14:
                return None
            dt_part = time_str[:14]
            return datetime.strptime(dt_part, "%Y%m%d%H%M%S")
        except ValueError:
            logger.warning(f"Failed to parse time string: {time_str}")
            return None

    def filter_broadcasts(
        self,
        broadcasts: List[EPGBroadcast],
        languages: List[str] | None = None,
        require_subtitles: bool = False,
    ) -> List[EPGBroadcast]:
        """
        Filter broadcasts by language and subtitle requirements.

        Args:
            broadcasts: List of EPGBroadcast objects
            languages: Allowed language codes (e.g., ['en', 'nl'])
            require_subtitles: If True, only include broadcasts with subtitles

        Returns:
            Filtered list of EPGBroadcast objects
        """
        filtered = broadcasts

        if languages:
            filtered = [
                b for b in filtered
                if b.language in languages or b.language == ""
            ]
            logger.info(f"Filtered to {len(filtered)} broadcasts with languages {languages}")

        if require_subtitles:
            filtered = [b for b in filtered if b.subtitles]
            logger.info(f"Filtered to {len(filtered)} broadcasts with subtitles")

        return filtered

    def filter_movies(self, broadcasts: List[EPGBroadcast]) -> List[EPGBroadcast]:
        """
        Filter broadcasts to only include movies (Film category).

        Args:
            broadcasts: List of EPGBroadcast objects

        Returns:
            Filtered list containing only movies
        """
        movies = [
            b for b in broadcasts
            if "Film" in b.categories
        ]
        logger.info(f"Filtered to {len(movies)} movies (from {len(broadcasts)} total broadcasts)")
        return movies
