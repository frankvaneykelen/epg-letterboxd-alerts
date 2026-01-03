"""
XMLTV Writer Module
Generates XMLTV format from database
"""

import json
import logging
import sqlite3
from lxml import etree

logger = logging.getLogger(__name__)


class XMLTVWriter:
    """Write XMLTV data from database"""

    def __init__(self, database_connection: sqlite3.Connection):
        """
        Initialize XMLTVWriter

        Args:
            database_connection: Open SQLite database connection
        """
        self._db = database_connection
        self._dbcur = self._db.cursor()
        self._lang = "nl"  # Ziggo EPG is Dutch

    def generate_xmltv(self) -> bytes:
        """
        Generate XMLTV file from database

        Returns:
            XMLTV data as bytes
        """
        logger.info("Generating XMLTV data...")

        xmltv = etree.Element(
            "tv",
            attrib={
                "source-info-url": "https://www.ziggogo.tv",
                "source-info-name": "ZiggoGo",
                "generator-info-name": "EPG-Letterboxd Alerts",
                "generator-info-url": "https://github.com/frankvaneykelen/epg-letterboxd-alerts",
            },
        )

        self._add_channels(xmltv=xmltv)
        self._add_programmes(xmltv=xmltv)

        return etree.tostring(xmltv, pretty_print=True, encoding='utf-8', xml_declaration=True)

    def _add_channels(self, xmltv: etree.Element):
        """Add channels to XMLTV element"""
        self._dbcur.execute("SELECT id, name, logo FROM channels")

        for row in self._dbcur:
            channel = etree.SubElement(xmltv, "channel", attrib={"id": row["id"].replace("_", ".")})
            etree.SubElement(channel, "display-name", attrib={"lang": self._lang}).text = row["name"]

            if row["logo"]:
                etree.SubElement(channel, "icon", attrib={"src": row["logo"]})

    def _add_programmes(self, xmltv: etree.Element):
        """Add programmes to XMLTV element"""
        self._dbcur.execute(
            "SELECT channelid, title, starttime, endtime, pd.details AS details "
            "FROM programmes p "
            "LEFT JOIN programmedetails pd ON pd.id = p.id"
        )

        for row in self._dbcur:
            programme = etree.SubElement(
                xmltv,
                "programme",
                attrib={
                    "start": row["starttime"],
                    "stop": row["endtime"],
                    "channel": row["channelid"].replace("_", ".")
                },
            )
            etree.SubElement(programme, "title", attrib={"lang": self._lang}).text = row["title"]

            if row["details"] is not None:
                try:
                    details = json.loads(row["details"])

                    if "sub-title" in details:
                        etree.SubElement(programme, "sub-title", attrib={"lang": self._lang}).text = details["sub-title"]

                    if "desc" in details:
                        etree.SubElement(programme, "desc", attrib={"lang": self._lang}).text = details["desc"]

                    if "credits" in details:
                        credits = etree.SubElement(programme, "credits")
                        if "directors" in details["credits"]:
                            for director in details["credits"]["directors"]:
                                etree.SubElement(credits, "director").text = director
                        if "actors" in details["credits"]:
                            for actor in details["credits"]["actors"]:
                                etree.SubElement(credits, "actor").text = actor
                        if "producers" in details["credits"]:
                            for producer in details["credits"]["producers"]:
                                etree.SubElement(credits, "producer").text = producer

                    if "date" in details:
                        etree.SubElement(programme, "date").text = details["date"]

                    if "categories" in details:
                        for category in details["categories"]:
                            etree.SubElement(programme, "category", attrib={"lang": self._lang}).text = category

                    if "country" in details:
                        etree.SubElement(programme, "country").text = details["country"]

                    if "episode" in details:
                        season = ""
                        ziggo_internal_id = False
                        try:
                            season = int(details["episode"]["season"]) - 1
                            if season >= 99999:
                                # Fake season number used in ZiggoGo that should never be displayed
                                ziggo_internal_id = True
                        except (KeyError, ValueError):
                            # No season value or not an integer
                            pass
                        episode = ""
                        try:
                            episode = int(details["episode"]["episode"]) - 1
                            if episode >= 9999999:
                                # Fake episode number used in ZiggoGo that should never be displayed
                                ziggo_internal_id = True
                        except (KeyError, ValueError):
                            # No episode value or not an integer
                            pass
                        if not ziggo_internal_id and (season != "" or episode != ""):
                            etree.SubElement(programme, "episode-num", attrib={"system": "xmltv_ns"}).text = f"{season}.{episode}."

                    if "rating" in details:
                        rating = etree.SubElement(programme, "rating", attrib={"system": "Kijkwijzer"})
                        etree.SubElement(rating, "value").text = details["rating"]

                except json.JSONDecodeError:
                    pass

    def __del__(self):
        """Cleanup"""
        if hasattr(self, "_dbcur"):
            self._dbcur.close()
