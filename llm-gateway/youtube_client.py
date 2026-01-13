#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YouTube Data API client for creating live broadcasts.

Handles:
- OAuth 2.0 authentication with refresh tokens
- Creating broadcasts and streams via YouTube Data API v3
- Binding broadcasts to streams
- Lifecycle management (transitioning to complete)

Each YouTube channel requires its own OAuth credentials stored in environment variables.
"""

import os
import json
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional
from functools import partial

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)

# Channel configuration - maps channel keys to environment variable names
CHANNELS = {
    "global": {
        "name": "ClashAI-Global",
        "credentials_env": "YOUTUBE_CREDS_GLOBAL",
    },
    "player1": {
        "name": "ClashAI-Player1",
        "credentials_env": "YOUTUBE_CREDS_PLAYER1",
    },
    "player2": {
        "name": "ClashAI-Player2",
        "credentials_env": "YOUTUBE_CREDS_PLAYER2",
    },
}


class YouTubeClient:
    """
    YouTube Data API client for managing live broadcasts.

    Each instance is bound to a specific YouTube channel via OAuth credentials.
    Thread-safe: All API calls are executed in a thread pool to avoid blocking the event loop.
    """

    def __init__(self, channel_key: str):
        """
        Initialize YouTube client for a specific channel.

        Args:
            channel_key: One of "global", "player1", "player2"

        Raises:
            ValueError: If channel_key is not recognized
            KeyError: If credentials environment variable is not set
        """
        if channel_key not in CHANNELS:
            raise ValueError(
                f"Unknown channel: {channel_key}. "
                f"Valid channels: {list(CHANNELS.keys())}"
            )

        channel_config = CHANNELS[channel_key]
        env_var = channel_config["credentials_env"]

        # Load credentials from environment variable
        creds_json = os.environ.get(env_var)
        if not creds_json:
            raise KeyError(
                f"YouTube credentials not configured. "
                f"Set {env_var} environment variable with OAuth credentials JSON. "
                f"See K8s ExternalSecret 'youtube-oauth-credentials' for production setup."
            )
        self._creds_info = json.loads(creds_json)

        self.credentials = Credentials.from_authorized_user_info(self._creds_info)
        self.youtube = build("youtube", "v3", credentials=self.credentials)
        self.channel_name = channel_config["name"]

        logger.info(f"Initialized YouTube client for channel: {self.channel_name}")

    def _refresh_credentials_if_needed(self) -> None:
        """
        Check if OAuth token is expired and refresh if necessary.

        OAuth access tokens expire after 1 hour. This method should be called
        before each API request to ensure valid credentials.
        """
        if self.credentials.expired and self.credentials.refresh_token:
            logger.info(f"Refreshing expired OAuth token for {self.channel_name}")
            self.credentials.refresh(Request())
            # Rebuild the API client with refreshed credentials
            self.youtube = build("youtube", "v3", credentials=self.credentials)
            logger.info("OAuth token refreshed successfully")

    async def _execute_api_call(self, api_request, timeout: float = 30.0):
        """
        Execute a YouTube API request in a thread pool to avoid blocking the event loop.

        Args:
            api_request: The API request object (from youtube.liveBroadcasts(), etc.)
            timeout: Maximum time to wait for the API call (default 30 seconds)

        Returns:
            The API response

        Raises:
            HttpError: If the API call fails
            asyncio.TimeoutError: If the API call exceeds timeout
            RuntimeError: Wrapper for timeout with helpful message
        """
        loop = asyncio.get_running_loop()

        # Refresh credentials before making the call (synchronous, but fast)
        self._refresh_credentials_if_needed()

        # Execute the blocking .execute() call in a thread pool with timeout
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, api_request.execute),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"YouTube API call timed out after {timeout}s. "
                "This may indicate network issues or YouTube API slowness."
            )

    async def create_broadcast(self, title: str, description: str) -> dict:
        """
        Create a new live broadcast via YouTube Data API.

        The broadcast is created as "unlisted" (viewable via direct link only)
        with auto-start and auto-stop enabled.

        Args:
            title: Broadcast title (e.g., "ClashAI Match game-123 - global")
            description: Broadcast description

        Returns:
            dict with keys:
                - video_id: The YouTube video ID (same URL for live and VOD)
                - broadcast_id: The broadcast resource ID

        Raises:
            HttpError: If YouTube API returns an error
        """
        # Schedule start time for "now" (immediate start)
        scheduled_start = (
            datetime.now(timezone.utc) + timedelta(minutes=1)
        ).isoformat()

        broadcast_body = {
            "snippet": {
                "title": title,
                "description": description,
                "scheduledStartTime": scheduled_start,
            },
            "status": {
                "privacyStatus": "unlisted",  # Viewable via direct link only
                "selfDeclaredMadeForKids": False,
            },
            "contentDetails": {
                "enableAutoStart": True,  # Start when stream connects
                "enableAutoStop": True,   # Stop when stream disconnects
                "enableDvr": True,        # Allow rewinding during live
                "recordFromStart": True,  # Ensure VOD captures everything
            },
        }

        logger.info(f"Creating broadcast: {title}")
        api_request = self.youtube.liveBroadcasts().insert(
            part="snippet,status,contentDetails",
            body=broadcast_body
        )
        response = await self._execute_api_call(api_request)

        video_id = response["id"]
        logger.info(f"Created broadcast with video_id: {video_id}")

        return {
            "video_id": video_id,
            "broadcast_id": video_id,  # Same as video_id for broadcasts
        }

    async def create_stream(self) -> dict:
        """
        Create a stream resource and get ingestion address.

        The stream is configured for 720p at 30fps (standard for game streaming).

        Returns:
            dict with keys:
                - stream_id: The stream resource ID
                - stream_key: The RTMPS stream key
                - rtmps_url: The RTMPS ingestion URL

        Raises:
            HttpError: If YouTube API returns an error
        """
        stream_body = {
            "snippet": {
                "title": "Match Stream",
            },
            "cdn": {
                "frameRate": "30fps",
                "resolution": "720p",
                "ingestionType": "rtmp",
            },
        }

        logger.info("Creating stream resource")
        api_request = self.youtube.liveStreams().insert(
            part="snippet,cdn",
            body=stream_body
        )
        response = await self._execute_api_call(api_request)

        stream_id = response["id"]
        ingestion_info = response["cdn"]["ingestionInfo"]

        result = {
            "stream_id": stream_id,
            "stream_key": ingestion_info["streamName"],
            "rtmps_url": ingestion_info["ingestionAddress"],
        }

        logger.info(f"Created stream with id: {stream_id}")
        return result

    async def bind_broadcast_to_stream(
        self, broadcast_id: str, stream_id: str
    ) -> None:
        """
        Bind a broadcast to a stream.

        This associates the stream's video feed with the broadcast,
        allowing the broadcast to go live when the stream connects.

        Args:
            broadcast_id: The broadcast resource ID
            stream_id: The stream resource ID

        Raises:
            HttpError: If YouTube API returns an error
        """
        logger.info(f"Binding broadcast {broadcast_id} to stream {stream_id}")
        api_request = self.youtube.liveBroadcasts().bind(
            id=broadcast_id,
            part="id,snippet",
            streamId=stream_id
        )
        await self._execute_api_call(api_request)
        logger.info("Broadcast bound to stream successfully")

    async def transition_to_complete(self, broadcast_id: str) -> None:
        """
        Transition broadcast to 'complete' status.

        This ends the live broadcast and triggers YouTube's auto-archive
        to convert it to a VOD (same video_id URL).

        Args:
            broadcast_id: The broadcast resource ID

        Raises:
            HttpError: If YouTube API returns an error
        """
        logger.info(f"Transitioning broadcast {broadcast_id} to complete")
        api_request = self.youtube.liveBroadcasts().transition(
            id=broadcast_id,
            part="id,status",
            broadcastStatus="complete"
        )
        await self._execute_api_call(api_request)
        logger.info("Broadcast transitioned to complete")

    async def delete_stream(self, stream_id: str) -> None:
        """
        Delete a stream resource.

        Call this after the broadcast ends to clean up resources.

        Args:
            stream_id: The stream resource ID

        Raises:
            HttpError: If YouTube API returns an error
        """
        logger.info(f"Deleting stream {stream_id}")
        api_request = self.youtube.liveStreams().delete(id=stream_id)
        await self._execute_api_call(api_request)
        logger.info("Stream deleted successfully")
