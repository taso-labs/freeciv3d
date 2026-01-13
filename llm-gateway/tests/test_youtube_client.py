#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TDD tests for YouTube Client.

Tests cover:
- OAuth credential loading from environment variables
- YouTube Data API broadcast creation
- Stream creation and binding
- Lifecycle management (transition to complete)

These tests use mocked Google API client - no actual YouTube API calls.
"""

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone

# Ensure we can import from parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def mock_broadcast_response(video_id="abc123", broadcast_id="broadcast_abc123"):
    """Helper to create mock broadcast API response"""
    return {
        "id": broadcast_id,
        "snippet": {
            "title": "ClashAI Match test-game - global",
            "description": "AI vs AI FreeCiv match",
            "scheduledStartTime": "2026-01-07T12:00:00Z",
        },
        "status": {
            "privacyStatus": "unlisted",
            "lifeCycleStatus": "ready",
        },
        "contentDetails": {
            "enableAutoStart": True,
            "enableAutoStop": True,
        },
    }


def mock_stream_response(stream_id="stream_xyz789", stream_key="xxxx-xxxx-xxxx-xxxx"):
    """Helper to create mock stream API response"""
    return {
        "id": stream_id,
        "snippet": {
            "title": "Match Stream",
        },
        "cdn": {
            "frameRate": "30fps",
            "resolution": "720p",
            "ingestionType": "rtmp",
            "ingestionInfo": {
                "streamName": stream_key,
                "ingestionAddress": "rtmps://a.rtmps.youtube.com/live2",
                "backupIngestionAddress": "rtmps://b.rtmps.youtube.com/live2?backup=1",
            },
        },
    }


def mock_credentials_json():
    """Helper to create mock OAuth credentials JSON"""
    return json.dumps({
        "client_id": "test-client-id.apps.googleusercontent.com",
        "client_secret": "test-client-secret",
        "refresh_token": "test-refresh-token",
        "token": "test-access-token",
        "token_uri": "https://oauth2.googleapis.com/token",
    })


class TestYouTubeClientAuthentication:
    """Test YouTube client OAuth authentication"""

    def test_loads_credentials_from_env_var(self):
        """Should load OAuth credentials from environment variable"""
        with patch.dict(os.environ, {"YOUTUBE_CREDS_GLOBAL": mock_credentials_json()}):
            with patch("youtube_client.build") as mock_build:
                with patch("youtube_client.Credentials") as mock_creds_class:
                    mock_creds = MagicMock()
                    mock_creds_class.from_authorized_user_info.return_value = mock_creds

                    from youtube_client import YouTubeClient
                    client = YouTubeClient("global")

                    mock_creds_class.from_authorized_user_info.assert_called_once()
                    mock_build.assert_called_once_with(
                        "youtube", "v3", credentials=mock_creds
                    )

    def test_raises_error_when_credentials_missing(self):
        """Should raise KeyError when credentials env var is not set"""
        with patch.dict(os.environ, {}, clear=True):
            # Remove the env var if it exists
            os.environ.pop("YOUTUBE_CREDS_GLOBAL", None)

            with pytest.raises(KeyError):
                from youtube_client import YouTubeClient
                # Force reimport to test with clean environment
                import importlib
                import youtube_client
                importlib.reload(youtube_client)
                YouTubeClient("global")

    def test_raises_error_for_invalid_channel_key(self):
        """Should raise ValueError for unknown channel key"""
        with patch.dict(os.environ, {"YOUTUBE_CREDS_GLOBAL": mock_credentials_json()}):
            with pytest.raises(ValueError, match="Unknown channel"):
                from youtube_client import YouTubeClient
                YouTubeClient("invalid_channel")


class TestYouTubeClientBroadcastCreation:
    """Test YouTube broadcast creation via Data API"""

    def setup_method(self):
        """Set up mock YouTube API client before each test"""
        self.env_patch = patch.dict(os.environ, {
            "YOUTUBE_CREDS_GLOBAL": mock_credentials_json()
        })
        self.env_patch.start()

        self.build_patch = patch("youtube_client.build")
        self.mock_build = self.build_patch.start()

        self.creds_patch = patch("youtube_client.Credentials")
        self.mock_creds_class = self.creds_patch.start()
        self.mock_creds_class.from_authorized_user_info.return_value = MagicMock()

        # Set up mock YouTube API
        self.mock_youtube = MagicMock()
        self.mock_build.return_value = self.mock_youtube

    def teardown_method(self):
        """Clean up patches after each test"""
        self.creds_patch.stop()
        self.build_patch.stop()
        self.env_patch.stop()

    @pytest.mark.asyncio
    async def test_create_broadcast_returns_video_id(self):
        """Should return video_id from created broadcast"""
        self.mock_youtube.liveBroadcasts().insert().execute.return_value = (
            mock_broadcast_response(video_id="test-video-123")
        )

        from youtube_client import YouTubeClient
        client = YouTubeClient("global")
        result = await client.create_broadcast(
            title="ClashAI Match test-game - global",
            description="AI vs AI FreeCiv match"
        )

        assert "video_id" in result
        assert result["video_id"] == "broadcast_abc123"  # id field from response

    @pytest.mark.asyncio
    async def test_create_broadcast_sets_unlisted_privacy(self):
        """Should create broadcast with unlisted privacy status"""
        self.mock_youtube.liveBroadcasts().insert().execute.return_value = (
            mock_broadcast_response()
        )

        from youtube_client import YouTubeClient
        client = YouTubeClient("global")
        await client.create_broadcast(
            title="Test Match",
            description="Test description"
        )

        # Verify the API was called with unlisted privacy
        call_args = self.mock_youtube.liveBroadcasts().insert.call_args
        body = call_args.kwargs.get("body", call_args[1].get("body", {}))
        assert body.get("status", {}).get("privacyStatus") == "unlisted"

    @pytest.mark.asyncio
    async def test_create_broadcast_enables_auto_start_stop(self):
        """Should enable auto-start and auto-stop for the broadcast"""
        self.mock_youtube.liveBroadcasts().insert().execute.return_value = (
            mock_broadcast_response()
        )

        from youtube_client import YouTubeClient
        client = YouTubeClient("global")
        await client.create_broadcast(
            title="Test Match",
            description="Test description"
        )

        call_args = self.mock_youtube.liveBroadcasts().insert.call_args
        body = call_args.kwargs.get("body", call_args[1].get("body", {}))
        content_details = body.get("contentDetails", {})
        assert content_details.get("enableAutoStart") is True
        assert content_details.get("enableAutoStop") is True

    @pytest.mark.asyncio
    async def test_create_broadcast_handles_api_error(self):
        """Should raise exception when YouTube API returns error"""
        from googleapiclient.errors import HttpError

        mock_response = MagicMock()
        mock_response.status = 403
        mock_response.reason = "quotaExceeded"

        self.mock_youtube.liveBroadcasts().insert().execute.side_effect = HttpError(
            resp=mock_response, content=b'{"error": {"message": "Quota exceeded"}}'
        )

        from youtube_client import YouTubeClient
        client = YouTubeClient("global")

        with pytest.raises(HttpError):
            await client.create_broadcast(
                title="Test Match",
                description="Test description"
            )


class TestYouTubeClientStreamCreation:
    """Test YouTube stream creation and configuration"""

    def setup_method(self):
        """Set up mock YouTube API client before each test"""
        self.env_patch = patch.dict(os.environ, {
            "YOUTUBE_CREDS_GLOBAL": mock_credentials_json()
        })
        self.env_patch.start()

        self.build_patch = patch("youtube_client.build")
        self.mock_build = self.build_patch.start()

        self.creds_patch = patch("youtube_client.Credentials")
        self.mock_creds_class = self.creds_patch.start()
        self.mock_creds_class.from_authorized_user_info.return_value = MagicMock()

        self.mock_youtube = MagicMock()
        self.mock_build.return_value = self.mock_youtube

    def teardown_method(self):
        """Clean up patches after each test"""
        self.creds_patch.stop()
        self.build_patch.stop()
        self.env_patch.stop()

    @pytest.mark.asyncio
    async def test_create_stream_returns_stream_key(self):
        """Should return stream_key from created stream"""
        self.mock_youtube.liveStreams().insert().execute.return_value = (
            mock_stream_response(stream_key="abcd-efgh-ijkl-mnop")
        )

        from youtube_client import YouTubeClient
        client = YouTubeClient("global")
        result = await client.create_stream()

        assert "stream_key" in result
        assert result["stream_key"] == "abcd-efgh-ijkl-mnop"

    @pytest.mark.asyncio
    async def test_create_stream_returns_rtmps_url(self):
        """Should return RTMPS ingestion URL from created stream"""
        self.mock_youtube.liveStreams().insert().execute.return_value = (
            mock_stream_response()
        )

        from youtube_client import YouTubeClient
        client = YouTubeClient("global")
        result = await client.create_stream()

        assert "rtmps_url" in result
        assert result["rtmps_url"] == "rtmps://a.rtmps.youtube.com/live2"

    @pytest.mark.asyncio
    async def test_create_stream_configures_720p_30fps(self):
        """Should configure stream for 720p at 30fps"""
        self.mock_youtube.liveStreams().insert().execute.return_value = (
            mock_stream_response()
        )

        from youtube_client import YouTubeClient
        client = YouTubeClient("global")
        await client.create_stream()

        call_args = self.mock_youtube.liveStreams().insert.call_args
        body = call_args.kwargs.get("body", call_args[1].get("body", {}))
        cdn = body.get("cdn", {})
        assert cdn.get("resolution") == "720p"
        assert cdn.get("frameRate") == "30fps"


class TestYouTubeClientBinding:
    """Test binding broadcasts to streams"""

    def setup_method(self):
        """Set up mock YouTube API client before each test"""
        self.env_patch = patch.dict(os.environ, {
            "YOUTUBE_CREDS_GLOBAL": mock_credentials_json()
        })
        self.env_patch.start()

        self.build_patch = patch("youtube_client.build")
        self.mock_build = self.build_patch.start()

        self.creds_patch = patch("youtube_client.Credentials")
        self.mock_creds_class = self.creds_patch.start()
        self.mock_creds_class.from_authorized_user_info.return_value = MagicMock()

        self.mock_youtube = MagicMock()
        self.mock_build.return_value = self.mock_youtube

    def teardown_method(self):
        """Clean up patches after each test"""
        self.creds_patch.stop()
        self.build_patch.stop()
        self.env_patch.stop()

    @pytest.mark.asyncio
    async def test_bind_broadcast_to_stream(self):
        """Should call YouTube API to bind broadcast to stream"""
        self.mock_youtube.liveBroadcasts().bind().execute.return_value = {
            "id": "broadcast_abc123"
        }

        from youtube_client import YouTubeClient
        client = YouTubeClient("global")
        await client.bind_broadcast_to_stream(
            broadcast_id="broadcast_abc123",
            stream_id="stream_xyz789"
        )

        # Check that bind was called with correct parameters
        # The mock chain is: liveBroadcasts().bind(id=..., streamId=...).execute()
        bind_calls = self.mock_youtube.liveBroadcasts().bind.call_args_list
        # Find the call with actual arguments (not the setup call)
        actual_call = [c for c in bind_calls if c.kwargs]
        assert len(actual_call) == 1
        assert actual_call[0].kwargs.get("id") == "broadcast_abc123"
        assert actual_call[0].kwargs.get("streamId") == "stream_xyz789"

    @pytest.mark.asyncio
    async def test_bind_handles_invalid_ids(self):
        """Should raise exception for invalid broadcast/stream IDs"""
        from googleapiclient.errors import HttpError

        mock_response = MagicMock()
        mock_response.status = 404
        mock_response.reason = "notFound"

        self.mock_youtube.liveBroadcasts().bind().execute.side_effect = HttpError(
            resp=mock_response, content=b'{"error": {"message": "Broadcast not found"}}'
        )

        from youtube_client import YouTubeClient
        client = YouTubeClient("global")

        with pytest.raises(HttpError):
            await client.bind_broadcast_to_stream(
                broadcast_id="invalid_broadcast",
                stream_id="invalid_stream"
            )


class TestYouTubeClientLifecycle:
    """Test broadcast lifecycle management"""

    def setup_method(self):
        """Set up mock YouTube API client before each test"""
        self.env_patch = patch.dict(os.environ, {
            "YOUTUBE_CREDS_GLOBAL": mock_credentials_json()
        })
        self.env_patch.start()

        self.build_patch = patch("youtube_client.build")
        self.mock_build = self.build_patch.start()

        self.creds_patch = patch("youtube_client.Credentials")
        self.mock_creds_class = self.creds_patch.start()
        self.mock_creds_class.from_authorized_user_info.return_value = MagicMock()

        self.mock_youtube = MagicMock()
        self.mock_build.return_value = self.mock_youtube

    def teardown_method(self):
        """Clean up patches after each test"""
        self.creds_patch.stop()
        self.build_patch.stop()
        self.env_patch.stop()

    @pytest.mark.asyncio
    async def test_transition_broadcast_to_complete(self):
        """Should transition broadcast to 'complete' status"""
        self.mock_youtube.liveBroadcasts().transition().execute.return_value = {
            "id": "broadcast_abc123",
            "status": {"lifeCycleStatus": "complete"}
        }

        from youtube_client import YouTubeClient
        client = YouTubeClient("global")
        await client.transition_to_complete(broadcast_id="broadcast_abc123")

        # Check that transition was called with correct parameters
        transition_calls = self.mock_youtube.liveBroadcasts().transition.call_args_list
        actual_call = [c for c in transition_calls if c.kwargs]
        assert len(actual_call) == 1
        assert actual_call[0].kwargs.get("id") == "broadcast_abc123"
        assert actual_call[0].kwargs.get("broadcastStatus") == "complete"

    @pytest.mark.asyncio
    async def test_delete_stream_after_broadcast_ends(self):
        """Should be able to delete stream resource after use"""
        self.mock_youtube.liveStreams().delete().execute.return_value = None

        from youtube_client import YouTubeClient
        client = YouTubeClient("global")
        await client.delete_stream(stream_id="stream_xyz789")

        # Check that delete was called with correct parameters
        delete_calls = self.mock_youtube.liveStreams().delete.call_args_list
        actual_call = [c for c in delete_calls if c.kwargs]
        assert len(actual_call) == 1
        assert actual_call[0].kwargs.get("id") == "stream_xyz789"
