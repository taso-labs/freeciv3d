#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TDD tests for Stream Manager.

Tests cover:
- K8s Job creation for streaming
- YouTube broadcast/stream lifecycle
- Session storage of youtube_urls
- Error handling and rollback
- GCS backup upload (stubbed for MVP)

MVP: Single global view only. Player views return placeholder/null.
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

# Ensure we can import from parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def mock_youtube_result():
    """Helper to create mock YouTubeClient result"""
    return {
        "video_id": "test-video-abc123",
        "broadcast_id": "test-video-abc123",
    }


def mock_stream_result():
    """Helper to create mock stream creation result"""
    return {
        "stream_id": "stream-xyz789",
        "stream_key": "xxxx-yyyy-zzzz-aaaa",
        "rtmps_url": "rtmps://a.rtmps.youtube.com/live2",
    }


def mock_job_object(name="stream-game123-global", phase="Running"):
    """Helper to create mock K8s Job object"""
    job = MagicMock()
    job.metadata.name = name
    job.status.active = 1 if phase == "Running" else 0
    job.status.succeeded = 1 if phase == "Succeeded" else 0
    job.status.failed = 1 if phase == "Failed" else 0
    return job


class TestStreamManagerJobCreation:
    """Test K8s Job creation for streaming"""

    def setup_method(self):
        """Set up mocks before each test"""
        # Mock K8s config loading and BatchV1Api
        self.config_patch = patch("stream_manager.kubernetes.config")
        self.mock_config = self.config_patch.start()

        self.batch_api_patch = patch("stream_manager.kubernetes.client.BatchV1Api")
        self.mock_batch_api_class = self.batch_api_patch.start()
        self.mock_batch_api = MagicMock()
        self.mock_batch_api_class.return_value = self.mock_batch_api

        # Mock YouTubeClient
        self.yt_patch = patch("stream_manager.YouTubeClient")
        self.mock_yt_class = self.yt_patch.start()

        # Configure mock YouTube client
        self.mock_yt_client = MagicMock()
        self.mock_yt_client.create_broadcast = AsyncMock(return_value=mock_youtube_result())
        self.mock_yt_client.create_stream = AsyncMock(return_value=mock_stream_result())
        self.mock_yt_client.bind_broadcast_to_stream = AsyncMock()
        self.mock_yt_class.return_value = self.mock_yt_client

    def teardown_method(self):
        """Clean up patches after each test"""
        self.yt_patch.stop()
        self.batch_api_patch.stop()
        self.config_patch.stop()

    @pytest.mark.asyncio
    async def test_start_stream_creates_one_job(self):
        """Should create exactly one K8s Job (MVP: global view only)"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="game123", civserver_port=6001)

        # Verify exactly one job was created
        assert self.mock_batch_api.create_namespaced_job.call_count == 1

    @pytest.mark.asyncio
    async def test_job_name_includes_game_id(self):
        """Job name should include game_id for identification"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="match-abc", civserver_port=6001)

        call_args = self.mock_batch_api.create_namespaced_job.call_args
        job_body = call_args.kwargs.get("body") or call_args[1].get("body")
        # Access the actual name string from the V1ObjectMeta object
        job_name = job_body.metadata.name
        assert "match-abc" in str(job_name)

    @pytest.mark.asyncio
    async def test_job_receives_correct_observer_url(self):
        """Job should receive observer URL with correct civserver port"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="game123", civserver_port=6005)

        call_args = self.mock_batch_api.create_namespaced_job.call_args
        job_body = call_args.kwargs.get("body") or call_args[1].get("body")

        # Find OBSERVER_URL env var in container spec
        # The containers list contains actual V1Container objects
        container = job_body.spec.template.spec.containers[0]
        env_list = container.env
        env_dict = {e.name: e.value for e in env_list}

        assert "OBSERVER_URL" in env_dict
        observer_url = env_dict["OBSERVER_URL"]
        assert "civserverport=6005" in observer_url
        assert "camera=strategic" in observer_url

    @pytest.mark.asyncio
    async def test_job_receives_stream_key(self):
        """Job should receive YouTube stream key as env var"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="game123", civserver_port=6001)

        call_args = self.mock_batch_api.create_namespaced_job.call_args
        job_body = call_args.kwargs.get("body") or call_args[1].get("body")

        container = job_body.spec.template.spec.containers[0]
        env_list = container.env
        env_dict = {e.name: e.value for e in env_list}

        assert "STREAM_KEY" in env_dict
        assert env_dict["STREAM_KEY"] == "xxxx-yyyy-zzzz-aaaa"


class TestStreamManagerMVPStubs:
    """Test MVP stub behavior for player views"""

    def setup_method(self):
        """Set up mocks before each test"""
        self.k8s_patch = patch("stream_manager.kubernetes")
        self.mock_k8s = self.k8s_patch.start()

        self.yt_patch = patch("stream_manager.YouTubeClient")
        self.mock_yt_class = self.yt_patch.start()

        self.mock_yt_client = MagicMock()
        self.mock_yt_client.create_broadcast = AsyncMock(return_value=mock_youtube_result())
        self.mock_yt_client.create_stream = AsyncMock(return_value=mock_stream_result())
        self.mock_yt_client.bind_broadcast_to_stream = AsyncMock()
        self.mock_yt_class.return_value = self.mock_yt_client

        self.mock_batch_api = MagicMock()
        self.mock_k8s.client.BatchV1Api.return_value = self.mock_batch_api

    def teardown_method(self):
        self.yt_patch.stop()
        self.k8s_patch.stop()

    @pytest.mark.asyncio
    async def test_player_views_return_placeholder_urls(self):
        """MVP: player1 and player2 youtube_urls should be None"""
        from stream_manager import StreamManager
        manager = StreamManager()

        result = await manager.start_stream(game_id="game123", civserver_port=6001)

        # Global view should have URL
        assert result["youtube_urls"]["global"] is not None

        # Player views should be None in MVP
        assert result["youtube_urls"]["player1"] is None
        assert result["youtube_urls"]["player2"] is None


class TestStreamManagerJobLifecycle:
    """Test Job lifecycle management"""

    def setup_method(self):
        """Set up mocks before each test"""
        self.k8s_patch = patch("stream_manager.kubernetes")
        self.mock_k8s = self.k8s_patch.start()

        self.yt_patch = patch("stream_manager.YouTubeClient")
        self.mock_yt_class = self.yt_patch.start()

        self.mock_yt_client = MagicMock()
        self.mock_yt_client.create_broadcast = AsyncMock(return_value=mock_youtube_result())
        self.mock_yt_client.create_stream = AsyncMock(return_value=mock_stream_result())
        self.mock_yt_client.bind_broadcast_to_stream = AsyncMock()
        self.mock_yt_client.transition_to_complete = AsyncMock()
        self.mock_yt_client.delete_stream = AsyncMock()
        self.mock_yt_class.return_value = self.mock_yt_client

        self.mock_batch_api = MagicMock()
        self.mock_k8s.client.BatchV1Api.return_value = self.mock_batch_api

    def teardown_method(self):
        self.yt_patch.stop()
        self.k8s_patch.stop()

    @pytest.mark.asyncio
    async def test_stop_stream_deletes_job(self):
        """Should delete the K8s Job when stopping stream"""
        from stream_manager import StreamManager
        manager = StreamManager()

        # First start a stream to register it
        await manager.start_stream(game_id="game123", civserver_port=6001)

        # Now stop it
        await manager.stop_stream(game_id="game123")

        # Verify job was deleted
        self.mock_batch_api.delete_namespaced_job.assert_called_once()
        call_args = self.mock_batch_api.delete_namespaced_job.call_args
        job_name = call_args.kwargs.get("name") or call_args[0][0]
        assert "game123" in job_name

    @pytest.mark.asyncio
    async def test_stop_stream_transitions_broadcast_to_complete(self):
        """Should transition YouTube broadcast to complete on stop"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="game123", civserver_port=6001)
        await manager.stop_stream(game_id="game123")

        self.mock_yt_client.transition_to_complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_job_not_found_on_stop(self):
        """Should handle gracefully when job doesn't exist on stop"""
        from kubernetes.client.rest import ApiException

        self.mock_batch_api.delete_namespaced_job.side_effect = ApiException(
            status=404, reason="Not Found"
        )

        from stream_manager import StreamManager
        manager = StreamManager()

        # Start and stop - should not raise even if job not found
        await manager.start_stream(game_id="game123", civserver_port=6001)
        await manager.stop_stream(game_id="game123")  # Should not raise


class TestStreamManagerYouTubeIntegration:
    """Test YouTube API integration"""

    def setup_method(self):
        """Set up mocks before each test"""
        self.k8s_patch = patch("stream_manager.kubernetes")
        self.mock_k8s = self.k8s_patch.start()

        self.yt_patch = patch("stream_manager.YouTubeClient")
        self.mock_yt_class = self.yt_patch.start()

        self.mock_yt_client = MagicMock()
        self.mock_yt_client.create_broadcast = AsyncMock(return_value={
            "video_id": "unique-video-id-123",
            "broadcast_id": "unique-video-id-123",
        })
        self.mock_yt_client.create_stream = AsyncMock(return_value=mock_stream_result())
        self.mock_yt_client.bind_broadcast_to_stream = AsyncMock()
        self.mock_yt_class.return_value = self.mock_yt_client

        self.mock_batch_api = MagicMock()
        self.mock_k8s.client.BatchV1Api.return_value = self.mock_batch_api

    def teardown_method(self):
        self.yt_patch.stop()
        self.k8s_patch.stop()

    @pytest.mark.asyncio
    async def test_start_stream_creates_broadcast(self):
        """Should create YouTube broadcast when starting stream"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="game123", civserver_port=6001)

        self.mock_yt_client.create_broadcast.assert_called_once()
        call_args = self.mock_yt_client.create_broadcast.call_args
        assert "game123" in call_args.kwargs.get("title", "")

    @pytest.mark.asyncio
    async def test_returns_youtube_url(self):
        """Should return youtube_url in result"""
        from stream_manager import StreamManager
        manager = StreamManager()

        result = await manager.start_stream(game_id="game123", civserver_port=6001)

        assert "youtube_urls" in result
        assert result["youtube_urls"]["global"] == "https://youtube.com/watch?v=unique-video-id-123"

    @pytest.mark.asyncio
    async def test_stores_video_id_in_session(self):
        """Should store video_id for later reference"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="game123", civserver_port=6001)

        # Check internal session storage (StreamSession dataclass)
        assert "game123" in manager.active_streams
        session = manager.active_streams["game123"]
        assert session.video_id == "unique-video-id-123"


class TestStreamManagerErrorHandling:
    """Test error handling and rollback"""

    def setup_method(self):
        """Set up mocks before each test"""
        self.k8s_patch = patch("stream_manager.kubernetes")
        self.mock_k8s = self.k8s_patch.start()

        self.yt_patch = patch("stream_manager.YouTubeClient")
        self.mock_yt_class = self.yt_patch.start()

        self.mock_yt_client = MagicMock()
        self.mock_yt_class.return_value = self.mock_yt_client

        self.mock_batch_api = MagicMock()
        self.mock_k8s.client.BatchV1Api.return_value = self.mock_batch_api

    def teardown_method(self):
        self.yt_patch.stop()
        self.k8s_patch.stop()

    @pytest.mark.asyncio
    async def test_rollback_on_failure(self):
        """Should clean up YouTube resources if Job creation fails"""
        from kubernetes.client.rest import ApiException

        # YouTube calls succeed
        self.mock_yt_client.create_broadcast = AsyncMock(return_value=mock_youtube_result())
        self.mock_yt_client.create_stream = AsyncMock(return_value=mock_stream_result())
        self.mock_yt_client.bind_broadcast_to_stream = AsyncMock()
        self.mock_yt_client.delete_stream = AsyncMock()

        # But Job creation fails
        self.mock_batch_api.create_namespaced_job.side_effect = ApiException(
            status=500, reason="Internal Server Error"
        )

        from stream_manager import StreamManager
        manager = StreamManager()

        with pytest.raises(Exception):
            await manager.start_stream(game_id="game123", civserver_port=6001)

        # Should have attempted to clean up the stream
        self.mock_yt_client.delete_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_on_transient_k8s_error(self):
        """Should retry Job creation on transient errors"""
        from kubernetes.client.rest import ApiException

        # First call fails, second succeeds
        self.mock_batch_api.create_namespaced_job.side_effect = [
            ApiException(status=503, reason="Service Unavailable"),
            MagicMock(),  # Success
        ]

        self.mock_yt_client.create_broadcast = AsyncMock(return_value=mock_youtube_result())
        self.mock_yt_client.create_stream = AsyncMock(return_value=mock_stream_result())
        self.mock_yt_client.bind_broadcast_to_stream = AsyncMock()

        from stream_manager import StreamManager
        manager = StreamManager()

        # Should succeed on retry
        result = await manager.start_stream(game_id="game123", civserver_port=6001)

        assert result["youtube_urls"]["global"] is not None
        assert self.mock_batch_api.create_namespaced_job.call_count == 2

    @pytest.mark.asyncio
    async def test_cleanup_orphaned_jobs(self):
        """Should be able to clean up jobs without active session"""
        from stream_manager import StreamManager
        manager = StreamManager()

        # Call cleanup directly without starting a stream
        await manager.cleanup_orphaned_jobs(game_id="orphan-game")

        # Should attempt to delete job even without session
        self.mock_batch_api.delete_namespaced_job.assert_called()


class TestStreamManagerGCSBackup:
    """Test GCS backup functionality (stubbed for MVP)"""

    def setup_method(self):
        """Set up mocks before each test"""
        self.k8s_patch = patch("stream_manager.kubernetes")
        self.mock_k8s = self.k8s_patch.start()

        self.yt_patch = patch("stream_manager.YouTubeClient")
        self.mock_yt_class = self.yt_patch.start()

        self.mock_yt_client = MagicMock()
        self.mock_yt_client.create_broadcast = AsyncMock(return_value=mock_youtube_result())
        self.mock_yt_client.create_stream = AsyncMock(return_value=mock_stream_result())
        self.mock_yt_client.bind_broadcast_to_stream = AsyncMock()
        self.mock_yt_client.transition_to_complete = AsyncMock()
        self.mock_yt_class.return_value = self.mock_yt_client

        self.mock_batch_api = MagicMock()
        self.mock_k8s.client.BatchV1Api.return_value = self.mock_batch_api

    def teardown_method(self):
        self.yt_patch.stop()
        self.k8s_patch.stop()

    @pytest.mark.asyncio
    async def test_uploads_local_backup_to_gcs_on_stop(self):
        """Should trigger GCS backup upload when stopping stream"""
        # GCS upload is stubbed for MVP - just verify it's called
        with patch("stream_manager.StreamManager._upload_backup_to_gcs") as mock_upload:
            mock_upload.return_value = None

            from stream_manager import StreamManager
            manager = StreamManager()

            await manager.start_stream(game_id="game123", civserver_port=6001)
            await manager.stop_stream(game_id="game123")

            # GCS upload should be attempted
            mock_upload.assert_called_once_with("game123")
