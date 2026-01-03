"""
TVHeadend Client Module
Schedules recordings via TVHeadend JSON API.
"""

import logging
import os
from typing import Dict, Any, Optional
from datetime import datetime
import requests

logger = logging.getLogger(__name__)


class TVHeadendClient:
    """Client for TVHeadend recording API."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize TVHeadend client.

        Args:
            config: Configuration dictionary with 'tvheadend' section
        """
        self.config = config.get("tvheadend", {})
        self.enabled = self.config.get("enabled", False)
        self.base_url = self.config.get("base_url", "http://localhost:9981")
        self.username = os.getenv("TVHEADEND_USERNAME", "admin")
        self.password = os.getenv("TVHEADEND_PASSWORD", "admin")

        if not self.enabled:
            logger.info("TVHeadend recording is disabled")

    def schedule_recording(
        self,
        channel_uuid: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Schedule a recording via TVHeadend.

        Args:
            channel_uuid: TVHeadend channel UUID
            title: Recording title
            start_time: Recording start datetime
            end_time: Recording end datetime
            metadata: Optional additional metadata

        Returns:
            True if scheduling succeeded, False otherwise
        """
        if not self.enabled:
            logger.warning("TVHeadend recording is disabled")
            return False

        try:
            # Convert datetimes to Unix timestamps
            start_unix = int(start_time.timestamp())
            end_unix = int(end_time.timestamp())

            # Prepare DVR entry
            dvr_data = {
                "enabled": 1,
                "channelid": channel_uuid,
                "start": start_unix,
                "stop": end_unix,
                "title": title,
            }

            if metadata:
                dvr_data.update(metadata)

            url = f"{self.base_url}/api/dvr/entry/create"
            response = requests.post(
                url,
                json=dvr_data,
                auth=(self.username, self.password),
                timeout=10,
            )
            response.raise_for_status()

            result = response.json()
            if result.get("success"):
                logger.info(f"Successfully scheduled recording: {title}")
                return True
            else:
                error = result.get("error", "Unknown error")
                logger.error(f"Failed to schedule recording: {error}")
                return False

        except requests.RequestException as e:
            logger.error(f"TVHeadend API error while scheduling recording: {e}")
            return False

    def get_channels(self) -> Dict[str, Any] | None:
        """
        Fetch available channels from TVHeadend.

        Returns:
            Dictionary of channels or None if fetch fails
        """
        if not self.enabled:
            return None

        try:
            url = f"{self.base_url}/api/channel/grid"
            response = requests.get(
                url,
                auth=(self.username, self.password),
                timeout=10,
            )
            response.raise_for_status()

            return response.json()

        except requests.RequestException as e:
            logger.error(f"Failed to fetch TVHeadend channels: {e}")
            return None

    def test_connection(self) -> bool:
        """
        Test connection to TVHeadend server.

        Returns:
            True if connection successful, False otherwise
        """
        if not self.enabled:
            logger.warning("TVHeadend is disabled")
            return False

        try:
            url = f"{self.base_url}/api/config/load"
            response = requests.get(
                url,
                auth=(self.username, self.password),
                timeout=10,
            )
            response.raise_for_status()

            logger.info("Successfully connected to TVHeadend")
            return True

        except requests.RequestException as e:
            logger.error(f"Failed to connect to TVHeadend: {e}")
            return False
