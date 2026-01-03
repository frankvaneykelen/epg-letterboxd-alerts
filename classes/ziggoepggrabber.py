"""
ZiggoGo EPG Grabber Wrapper
Simplified wrapper around ziggogo-epg library core functionality
"""

import datetime
import json
import logging
import sqlite3
import time
import yaml
import requests
from pathlib import Path
from typing import List
from requests.adapters import HTTPAdapter, Retry

try:
    import pytz
except ImportError:
    pytz = None

from classes.tvsystemio import TVSystemIo
from classes.xmltvwriter import XMLTVWriter

logger = logging.getLogger(__name__)


class GrabException(Exception):
    """Failure grabbing EPG"""


class ChannelMatcher:
    """Matches a given channel with a known channel list"""

    def __init__(self, channels: List[str]):
        """Initialize with known channel list"""
        # Store as lowercase, without whitespace and without 'HD' tag
        self._known_channels = {}
        for channel in channels:
            channel_id = channel.lower().strip()
            if channel_id.endswith(" hd"):
                channel_id = channel_id[:-3].strip()
            self._known_channels[channel_id] = channel

    def is_known(self, channel: str) -> bool:
        """Match channel with list of known channels. Returns True if channel is found, False if it is not."""
        channel = channel.lower().strip()
        if channel.endswith(" hd"):
            channel = channel[:-3].strip()

        return channel in self._known_channels


class ZiggoGoEpgGrabber:
    """Simplified grabber for the EPG hosted by Ziggo on ziggogo.tv"""

    def __init__(
        self,
        tv_system_io: TVSystemIo,
        scan_days: int = 7,
        configuration_file: str = "ziggo-nl.yml",
        database_file: str = "data/ziggogoepg_cache.sqlite3",
        timezone=None,
    ):
        """
        Initialize ZiggoGoEpgGrabber

        Args:
            tv_system_io: Instance of a TVSystemIo object
            scan_days: Number of days to scan for
            configuration_file: YAML config file name (without extension)
            database_file: Path to SQLite cache database
            timezone: Timezone string supported by pytz
        """
        self._tv_system_io = tv_system_io
        
        # Find configuration file
        config_path = Path(__file__).parent.parent / "configs" / f"{configuration_file}.yml"
        if not config_path.exists():
            raise GrabException(f"Configuration file {config_path} not found")

        # Load configuration
        try:
            with open(config_path, 'r') as f:
                configuration = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise GrabException(f"Configuration file {config_path} is not valid YAML: {e}")

        # Extract URLs
        try:
            self._epg_channel_list_url = configuration["urls"]["epg_channel_list"]
            self._epg_segment_url = configuration["urls"]["epg_segment"]
            self._epg_detail_url = configuration["urls"]["epg_detail"]
        except KeyError as e:
            raise GrabException(f"Configuration missing required URLs: {e}")

        # Setup timezone
        if pytz is None:
            raise GrabException("pytz library is required but not installed")
            
        if timezone is None:
            timezone = configuration.get("timezone", "Europe/Amsterdam")
        
        self._timezone = pytz.timezone(timezone)
        self._scan_days = scan_days
        self._grab_start_time = None

        # Setup database
        db_path = Path(database_file)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._db = sqlite3.connect(str(db_path))
        self._db.row_factory = sqlite3.Row
        self._dbcur = self._db.cursor()
        self._dbcur.arraysize = 1024

        # Create tables
        self._create_tables()

    def _create_tables(self):
        """Create database tables if they don't exist"""
        self._dbcur.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id TEXT PRIMARY KEY,
                last_update INTEGER NOT NULL,
                name TEXT NOT NULL,
                logo TEXT
            )
        """)
        self._dbcur.execute("""
            CREATE TABLE IF NOT EXISTS programmes (
                id TEXT PRIMARY KEY,
                channelid TEXT NOT NULL,
                last_update INTEGER NOT NULL,
                title TEXT NOT NULL,
                starttime TEXT NOT NULL,
                endtime TEXT NOT NULL
            )
        """)
        self._dbcur.execute("""
            CREATE TABLE IF NOT EXISTS programmedetails (
                id TEXT PRIMARY KEY,
                details TEXT NOT NULL
            )
        """)
        self._db.commit()

    def __del__(self):
        """Cleanup"""
        if hasattr(self, "_dbcur"):
            self._dbcur.close()
        if hasattr(self, "_db"):
            self._db.close()

    def grab(self, generate_only: bool = False):
        """
        Perform EPG grab
        
        Args:
            generate_only: If True, only generate XMLTV from existing cache
        
        Raises:
            GrabException: On grab failure
        """
        self._grab_start_time = int(time.time())

        if not generate_only:
            logger.info("Starting EPG grab from Ziggo servers...")
            channel_ids = self._grab_channels()
            self._grab_programmes(channel_ids=channel_ids)
            self._grab_programmedetails()
            
            logger.info("Optimizing database...")
            self._dbcur.execute("VACUUM")
        else:
            logger.info("Generate only mode: using existing cache")

        # Generate XMLTV
        xmltv_writer = XMLTVWriter(database_connection=self._db)
        xmltv = xmltv_writer.generate_xmltv()

        # Write output
        self._tv_system_io.write_xmltv(data=xmltv)
        logger.info("EPG grab completed successfully")

    def get_channel_list(self) -> List:
        """Get list of available channels from Ziggo"""
        logger.info("Fetching channel list from Ziggo...")
        
        # Headers to mimic legitimate browser request
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'nl-NL,nl;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Origin': 'https://www.ziggogo.tv',
            'Referer': 'https://www.ziggogo.tv/',
        }
        
        try:
            response = requests.get(self._epg_channel_list_url, headers=headers, timeout=10)
            response.raise_for_status()
            channeldata = response.json()
        except requests.RequestException as e:
            raise GrabException(f"Failed to fetch channel list: {e}")

        channel_list = []
        for channel in channeldata:
            try:
                logo = None
                if "logo" in channel and "focused" in channel["logo"]:
                    logo = channel["logo"]["focused"]

                channel_list.append({
                    "id": channel["id"],
                    "name": channel["name"],
                    "logo": logo,
                })
            except KeyError:
                continue

        logger.info(f"Found {len(channel_list)} channels")
        return channel_list

    def _grab_channels(self) -> List[str]:
        """Grab and filter channel list"""
        channel_matcher = ChannelMatcher(channels=self._tv_system_io.get_channel_list())
        
        logger.info("Getting known channels from EPG...")
        all_channels = self.get_channel_list()
        
        channelupdate = []
        for channel in all_channels:
            if not channel_matcher.is_known(channel["name"]):
                continue
            channelupdate.append(channel)
        
        logger.info(f"Found {len(channelupdate)} matching channels")

        # Update database
        for channel in channelupdate:
            channel["last_update"] = self._grab_start_time
        
        self._dbcur.executemany(
            "INSERT OR REPLACE INTO channels (id, last_update, name, logo) VALUES (:id, :last_update, :name, :logo)",
            channelupdate
        )
        
        # Purge old channels
        self._dbcur.execute("DELETE FROM channels WHERE last_update != ?", (self._grab_start_time,))
        self._db.commit()

        return [ch["id"] for ch in channelupdate]

    def _grab_programmes(self, channel_ids: List[str]):
        """Grab programme listings"""
        logger.info(f"Grabbing programme data for {len(channel_ids)} channels...")
        
        if not channel_ids:
            logger.warning("No channels to grab programmes for")
            return

        grab_start = datetime.datetime.utcfromtimestamp(self._grab_start_time)
        segment_datetime = datetime.datetime(year=grab_start.year, month=grab_start.month, day=grab_start.day)
        end_datetime = segment_datetime + datetime.timedelta(days=self._scan_days)

        # Headers to mimic legitimate browser request
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'nl-NL,nl;q=0.9,en;q=0.8',
            'Origin': 'https://www.ziggogo.tv',
            'Referer': 'https://www.ziggogo.tv/',
        }

        # Setup retry session
        session = requests.Session()
        session.headers.update(headers)
        retries = Retry(total=10, backoff_factor=0.1)
        session.mount('https://', HTTPAdapter(max_retries=retries))

        segment_count = 0
        while segment_datetime < end_datetime:
            segment_code = segment_datetime.strftime("%Y%m%d%H%M%S")
            
            try:
                with session.get(self._epg_segment_url.format(segment_code), timeout=10) as r:
                    if r.status_code == 404:
                        logger.info(f"No more EPG data at {segment_datetime}, stopping")
                        break

                    segmentdata = r.json()
                    
                    if "duration" in segmentdata and isinstance(segmentdata["duration"], int) and segmentdata["duration"] > 0:
                        segment_datetime += datetime.timedelta(seconds=segmentdata["duration"])
                    else:
                        segment_datetime += datetime.timedelta(hours=6)

                    if "entries" not in segmentdata:
                        continue

                    # Extract programmes
                    programmeupdate = []
                    for entry in segmentdata["entries"]:
                        if "events" not in entry or entry.get("channelId") not in channel_ids:
                            continue

                        for event in entry["events"]:
                            try:
                                programmeupdate.append({
                                    "id": event["id"],
                                    "channelid": entry["channelId"],
                                    "last_update": self._grab_start_time,
                                    "title": event["title"],
                                    "starttime": datetime.datetime.fromtimestamp(event["startTime"], self._timezone).strftime("%Y%m%d%H%M%S %z"),
                                    "endtime": datetime.datetime.fromtimestamp(event["endTime"], self._timezone).strftime("%Y%m%d%H%M%S %z"),
                                })
                            except KeyError:
                                pass

                    if programmeupdate:
                        self._dbcur.executemany(
                            "INSERT OR REPLACE INTO programmes (id, channelid, last_update, title, starttime, endtime) VALUES (:id, :channelid, :last_update, :title, :starttime, :endtime)",
                            programmeupdate
                        )
                        self._db.commit()
                    
                    segment_count += 1
                    if segment_count % 10 == 0:
                        logger.info(f"Processed {segment_count} segments...")

            except Exception as e:
                logger.warning(f"Error grabbing segment {segment_code}: {e}")
                segment_datetime += datetime.timedelta(hours=6)

        # Purge old programmes
        logger.info("Cleaning up programme table...")
        self._dbcur.execute("DELETE FROM programmes WHERE last_update != ?", (self._grab_start_time,))
        self._db.commit()
        
        logger.info(f"Grabbed {segment_count} segments successfully")

    def _grab_programmedetails(self):
        """Grab detailed information for programmes"""
        # Cleanup orphaned details first
        logger.info("Cleaning up programme details...")
        self._dbcur.execute("DELETE FROM programmedetails WHERE id NOT IN (SELECT id FROM programmes)")
        self._db.commit()

        # Find missing details
        self._dbcur.execute("SELECT p.id FROM programmes p LEFT JOIN programmedetails pd ON pd.id = p.id WHERE pd.id IS NULL")
        missing_programmes = self._dbcur.fetchall()
        
        if not missing_programmes:
            logger.info("No missing programme details")
            return

        total_count = len(missing_programmes)
        logger.info(f"Fetching details for {total_count} programmes...")

        # Headers to mimic legitimate browser request
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'nl-NL,nl;q=0.9,en;q=0.8',
            'Origin': 'https://www.ziggogo.tv',
            'Referer': 'https://www.ziggogo.tv/',
        }

        session = requests.Session()
        session.headers.update(headers)
        retries = Retry(total=10, backoff_factor=0.1)
        session.mount('https://', HTTPAdapter(max_retries=retries))

        detailsupdate = []
        for idx, row in enumerate(missing_programmes, 1):
            prog_id = row[0]

            try:
                with session.get(self._epg_detail_url.format(prog_id), timeout=5) as r:
                    if r.status_code != 200:
                        continue

                    programmedata = r.json()
                    
                    # Title is required
                    try:
                        details = {"title": programmedata["title"]}
                    except KeyError:
                        logger.warning(f"Programme data for '{prog_id}' is missing title data, skipping.")
                        continue

                    # Add optional fields
                    if "episodeName" in programmedata:
                        details["sub-title"] = programmedata["episodeName"]
                    
                    if "longDescription" in programmedata:
                        details["desc"] = programmedata["longDescription"]
                    elif "shortDescription" in programmedata:
                        details["desc"] = programmedata["shortDescription"]

                    # Credits
                    credits = {}
                    if "actors" in programmedata:
                        credits["actors"] = programmedata["actors"]
                    if "directors" in programmedata:
                        credits["directors"] = programmedata["directors"]
                    if "producers" in programmedata:
                        credits["producers"] = programmedata["producers"]
                    if credits:
                        details["credits"] = credits

                    if "productionDate" in programmedata:
                        details["date"] = programmedata["productionDate"]

                    if "genres" in programmedata:
                        details["categories"] = programmedata["genres"]
                    
                    if "countryOfOrigin" in programmedata:
                        details["country"] = programmedata["countryOfOrigin"]
                    
                    # Episode information
                    episode = {}
                    if "seasonNumber" in programmedata:
                        episode["season"] = programmedata["seasonNumber"]
                    if "episodeNumber" in programmedata:
                        episode["episode"] = programmedata["episodeNumber"]
                    if episode:
                        details["episode"] = episode
                    
                    if "minimumAge" in programmedata:
                        details["rating"] = programmedata["minimumAge"]

                    detailsupdate.append({"id": prog_id, "details": json.dumps(details)})

                    if len(detailsupdate) >= 100:
                        self._dbcur.executemany("INSERT INTO programmedetails (id, details) VALUES (:id, :details)", detailsupdate)
                        self._db.commit()
                        logger.info(f"  Fetched {idx}/{total_count} programme details...")
                        detailsupdate = []

            except Exception as e:
                logger.warning(f"Error fetching details for {prog_id}: {e}")

        if detailsupdate:
            self._dbcur.executemany("INSERT INTO programmedetails (id, details) VALUES (:id, :details)", detailsupdate)
            self._db.commit()
            logger.info(f"  Fetched {total_count}/{total_count} programme details")
