#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TDD tests for Stream Manager.

Tests cover:
- K8s Job creation for streaming (3 views: global, player1, player2)
- YouTube broadcast/stream lifecycle
- Session storage of youtube_urls
- Error handling and rollback
- GCS backup orchestration (upload handled by streaming container)
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock, AsyncMock, call

# Ensure we can import from parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def make_mock_youtube_result(view="global"):
    """Helper to create mock YouTubeClient result with unique IDs per view"""
    return {
        "video_id": f"test-video-{view}-abc123",
        "broadcast_id": f"test-video-{view}-abc123",
    }


def make_mock_stream_result(view="global"):
    """Helper to create mock stream creation result with unique keys per view"""
    return {
        "stream_id": f"stream-{view}-xyz789",
        "stream_key": f"key-{view}-xxxx-yyyy",
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


def create_mock_youtube_client(view):
    """Create a mock YouTubeClient for a specific view"""
    client = MagicMock()
    client.create_broadcast = AsyncMock(return_value=make_mock_youtube_result(view))
    client.create_stream = AsyncMock(return_value=make_mock_stream_result(view))
    client.bind_broadcast_to_stream = AsyncMock()
    client.transition_to_complete = AsyncMock()
    client.delete_stream = AsyncMock()
    return client


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

        # Mock CoreV1Api for secrets management
        self.core_api_patch = patch("stream_manager.kubernetes.client.CoreV1Api")
        self.mock_core_api_class = self.core_api_patch.start()
        self.mock_core_api = MagicMock()
        self.mock_core_api_class.return_value = self.mock_core_api

        # Mock YouTubeClient - returns different mock per channel
        self.yt_patch = patch("stream_manager.YouTubeClient")
        self.mock_yt_class = self.yt_patch.start()

        # Create mock clients for each view
        self.mock_yt_clients = {
            "global": create_mock_youtube_client("global"),
            "player1": create_mock_youtube_client("player1"),
            "player2": create_mock_youtube_client("player2"),
        }
        self.mock_yt_class.side_effect = lambda view: self.mock_yt_clients[view]

        # Disable readiness check for faster tests
        self.readiness_patch = patch("stream_manager.JOB_READINESS_TIMEOUT", 0)
        self.readiness_patch.start()

    def teardown_method(self):
        """Clean up patches after each test"""
        self.readiness_patch.stop()
        self.yt_patch.stop()
        self.core_api_patch.stop()
        self.batch_api_patch.stop()
        self.config_patch.stop()

    @pytest.mark.asyncio
    async def test_start_stream_creates_three_jobs(self):
        """Should create exactly 3 K8s Jobs (global, player1, player2)"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="game123", civserver_port=6001)

        # Verify exactly 3 jobs were created
        assert self.mock_batch_api.create_namespaced_job.call_count == 3

    @pytest.mark.asyncio
    async def test_job_names_include_game_id_and_view(self):
        """Job names should include game_id and view for identification"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="match-abc", civserver_port=6001)

        # Get all job names that were created
        job_names = []
        for call_args in self.mock_batch_api.create_namespaced_job.call_args_list:
            job_body = call_args.kwargs.get("body") or call_args[1].get("body")
            job_names.append(job_body.metadata.name)

        assert "stream-match-abc-global" in job_names
        assert "stream-match-abc-player1" in job_names
        assert "stream-match-abc-player2" in job_names

    @pytest.mark.asyncio
    async def test_global_job_receives_strategic_camera(self):
        """Global view job should receive observer URL with strategic camera"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="game123", civserver_port=6005)

        # Find the global job's observer URL
        for call_args in self.mock_batch_api.create_namespaced_job.call_args_list:
            job_body = call_args.kwargs.get("body") or call_args[1].get("body")
            if "global" in job_body.metadata.name:
                container = job_body.spec.template.spec.containers[0]
                env_dict = {e.name: e.value for e in container.env}
                observer_url = env_dict["OBSERVER_URL"]
                assert "camera=strategic" in observer_url
                assert "civserverport=6005" in observer_url
                break

    @pytest.mark.asyncio
    async def test_player_jobs_receive_cinematic_camera(self):
        """Player view jobs should receive observer URL with cinematic camera"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="game123", civserver_port=6005)

        # Find player jobs and check camera
        for call_args in self.mock_batch_api.create_namespaced_job.call_args_list:
            job_body = call_args.kwargs.get("body") or call_args[1].get("body")
            if "player1" in job_body.metadata.name or "player2" in job_body.metadata.name:
                container = job_body.spec.template.spec.containers[0]
                env_dict = {e.name: e.value for e in container.env}
                observer_url = env_dict["OBSERVER_URL"]
                assert "camera=cinematic" in observer_url

    @pytest.mark.asyncio
    async def test_jobs_receive_unique_stream_key_secrets(self):
        """Each job should reference its own unique stream key secret"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="game123", civserver_port=6001)

        # Collect all secret names referenced by STREAM_KEY env var
        secret_names = []
        for call_args in self.mock_batch_api.create_namespaced_job.call_args_list:
            job_body = call_args.kwargs.get("body") or call_args[1].get("body")
            container = job_body.spec.template.spec.containers[0]
            for env_var in container.env:
                if env_var.name == "STREAM_KEY":
                    # Stream key should be from secretKeyRef, not direct value
                    assert env_var.value_from is not None
                    secret_names.append(env_var.value_from.secret_key_ref.name)

        # All secret names should be unique (one per view)
        assert len(secret_names) == 3
        assert len(set(secret_names)) == 3
        assert "stream-key-game123-global" in secret_names
        assert "stream-key-game123-player1" in secret_names
        assert "stream-key-game123-player2" in secret_names

    @pytest.mark.asyncio
    async def test_jobs_receive_unique_backup_paths(self):
        """Each job should receive its own unique backup path"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="game123", civserver_port=6001)

        # Collect all backup paths
        backup_paths = []
        for call_args in self.mock_batch_api.create_namespaced_job.call_args_list:
            job_body = call_args.kwargs.get("body") or call_args[1].get("body")
            container = job_body.spec.template.spec.containers[0]
            env_dict = {e.name: e.value for e in container.env}
            backup_paths.append(env_dict["BACKUP_PATH"])

        # All backup paths should be unique and include view
        assert "/backup/game123-global.mp4" in backup_paths
        assert "/backup/game123-player1.mp4" in backup_paths
        assert "/backup/game123-player2.mp4" in backup_paths

    @pytest.mark.asyncio
    async def test_jobs_have_view_labels(self):
        """Each job should have a view label for identification"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="game123", civserver_port=6001)

        # Collect all view labels
        views = []
        for call_args in self.mock_batch_api.create_namespaced_job.call_args_list:
            job_body = call_args.kwargs.get("body") or call_args[1].get("body")
            views.append(job_body.metadata.labels.get("view"))

        assert "global" in views
        assert "player1" in views
        assert "player2" in views


class TestStreamManagerAllViewsReturned:
    """Test that all 3 view URLs are returned"""

    def setup_method(self):
        """Set up mocks before each test"""
        self.k8s_patch = patch("stream_manager.kubernetes")
        self.mock_k8s = self.k8s_patch.start()

        self.yt_patch = patch("stream_manager.YouTubeClient")
        self.mock_yt_class = self.yt_patch.start()

        self.mock_yt_clients = {
            "global": create_mock_youtube_client("global"),
            "player1": create_mock_youtube_client("player1"),
            "player2": create_mock_youtube_client("player2"),
        }
        self.mock_yt_class.side_effect = lambda view: self.mock_yt_clients[view]

        self.mock_batch_api = MagicMock()
        self.mock_k8s.client.BatchV1Api.return_value = self.mock_batch_api

        # Disable readiness check for faster tests
        self.readiness_patch = patch("stream_manager.JOB_READINESS_TIMEOUT", 0)
        self.readiness_patch.start()

    def teardown_method(self):
        self.readiness_patch.stop()
        self.yt_patch.stop()
        self.k8s_patch.stop()

    @pytest.mark.asyncio
    async def test_all_views_return_youtube_urls(self):
        """All 3 views should have non-null YouTube URLs"""
        from stream_manager import StreamManager
        manager = StreamManager()

        result = await manager.start_stream(game_id="game123", civserver_port=6001)

        # All views should have URLs
        assert result["youtube_urls"]["global"] is not None
        assert result["youtube_urls"]["player1"] is not None
        assert result["youtube_urls"]["player2"] is not None

    @pytest.mark.asyncio
    async def test_urls_contain_correct_video_ids(self):
        """Each URL should contain the correct video ID for that view"""
        from stream_manager import StreamManager
        manager = StreamManager()

        result = await manager.start_stream(game_id="game123", civserver_port=6001)

        assert "test-video-global-abc123" in result["youtube_urls"]["global"]
        assert "test-video-player1-abc123" in result["youtube_urls"]["player1"]
        assert "test-video-player2-abc123" in result["youtube_urls"]["player2"]

    @pytest.mark.asyncio
    async def test_returns_list_of_job_names(self):
        """Should return list of all 3 job names"""
        from stream_manager import StreamManager
        manager = StreamManager()

        result = await manager.start_stream(game_id="game123", civserver_port=6001)

        assert "job_names" in result
        assert len(result["job_names"]) == 3
        assert any("global" in name for name in result["job_names"])
        assert any("player1" in name for name in result["job_names"])
        assert any("player2" in name for name in result["job_names"])


class TestStreamManagerJobLifecycle:
    """Test Job lifecycle management"""

    def setup_method(self):
        """Set up mocks before each test"""
        self.k8s_patch = patch("stream_manager.kubernetes")
        self.mock_k8s = self.k8s_patch.start()

        self.yt_patch = patch("stream_manager.YouTubeClient")
        self.mock_yt_class = self.yt_patch.start()

        self.mock_yt_clients = {
            "global": create_mock_youtube_client("global"),
            "player1": create_mock_youtube_client("player1"),
            "player2": create_mock_youtube_client("player2"),
        }
        self.mock_yt_class.side_effect = lambda view: self.mock_yt_clients[view]

        self.mock_batch_api = MagicMock()
        self.mock_k8s.client.BatchV1Api.return_value = self.mock_batch_api

        # Disable readiness check for faster tests
        self.readiness_patch = patch("stream_manager.JOB_READINESS_TIMEOUT", 0)
        self.readiness_patch.start()

    def teardown_method(self):
        self.readiness_patch.stop()
        self.yt_patch.stop()
        self.k8s_patch.stop()

    @pytest.mark.asyncio
    async def test_stop_stream_deletes_all_three_jobs(self):
        """Should delete all 3 K8s Jobs when stopping stream"""
        from stream_manager import StreamManager
        manager = StreamManager()

        # First start a stream to register it
        await manager.start_stream(game_id="game123", civserver_port=6001)

        # Now stop it
        await manager.stop_stream(game_id="game123")

        # Verify all 3 jobs were deleted
        assert self.mock_batch_api.delete_namespaced_job.call_count == 3

        # Check job names
        deleted_names = [
            call_args.kwargs.get("name") or call_args[0][0]
            for call_args in self.mock_batch_api.delete_namespaced_job.call_args_list
        ]
        assert any("global" in name for name in deleted_names)
        assert any("player1" in name for name in deleted_names)
        assert any("player2" in name for name in deleted_names)

    @pytest.mark.asyncio
    async def test_stop_stream_transitions_all_broadcasts_to_complete(self):
        """Should transition all 3 YouTube broadcasts to complete on stop"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="game123", civserver_port=6001)
        await manager.stop_stream(game_id="game123")

        # Each client should have transition_to_complete called once
        self.mock_yt_clients["global"].transition_to_complete.assert_called_once()
        self.mock_yt_clients["player1"].transition_to_complete.assert_called_once()
        self.mock_yt_clients["player2"].transition_to_complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_job_not_found_on_stop(self):
        """Should handle gracefully when jobs don't exist on stop"""
        from kubernetes.client.rest import ApiException

        self.mock_batch_api.delete_namespaced_job.side_effect = ApiException(
            status=404, reason="Not Found"
        )

        from stream_manager import StreamManager
        manager = StreamManager()

        # Start and stop - should not raise even if jobs not found
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

        self.mock_yt_clients = {
            "global": create_mock_youtube_client("global"),
            "player1": create_mock_youtube_client("player1"),
            "player2": create_mock_youtube_client("player2"),
        }
        self.mock_yt_class.side_effect = lambda view: self.mock_yt_clients[view]

        self.mock_batch_api = MagicMock()
        self.mock_k8s.client.BatchV1Api.return_value = self.mock_batch_api

        # Disable readiness check for faster tests
        self.readiness_patch = patch("stream_manager.JOB_READINESS_TIMEOUT", 0)
        self.readiness_patch.start()

    def teardown_method(self):
        self.readiness_patch.stop()
        self.yt_patch.stop()
        self.k8s_patch.stop()

    @pytest.mark.asyncio
    async def test_creates_three_youtube_clients(self):
        """Should create 3 YouTube clients (one per channel)"""
        from stream_manager import StreamManager
        manager = StreamManager()

        # YouTubeClient should be called 3 times with different view names
        assert self.mock_yt_class.call_count == 3
        self.mock_yt_class.assert_any_call("global")
        self.mock_yt_class.assert_any_call("player1")
        self.mock_yt_class.assert_any_call("player2")

    @pytest.mark.asyncio
    async def test_start_stream_creates_three_broadcasts(self):
        """Should create 3 YouTube broadcasts when starting stream"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="game123", civserver_port=6001)

        # Each client should have create_broadcast called once
        self.mock_yt_clients["global"].create_broadcast.assert_called_once()
        self.mock_yt_clients["player1"].create_broadcast.assert_called_once()
        self.mock_yt_clients["player2"].create_broadcast.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_titles_include_view_name(self):
        """Broadcast titles should include the view name"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="game123", civserver_port=6001)

        # Check titles
        global_title = self.mock_yt_clients["global"].create_broadcast.call_args.kwargs["title"]
        player1_title = self.mock_yt_clients["player1"].create_broadcast.call_args.kwargs["title"]
        player2_title = self.mock_yt_clients["player2"].create_broadcast.call_args.kwargs["title"]

        assert "global" in global_title
        assert "player1" in player1_title
        assert "player2" in player2_title

    @pytest.mark.asyncio
    async def test_stores_all_view_data_in_session(self):
        """Should store data for all 3 views in session"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="game123", civserver_port=6001)

        # Check internal session storage
        assert "game123" in manager.active_streams
        session = manager.active_streams["game123"]

        assert "global" in session.views
        assert "player1" in session.views
        assert "player2" in session.views

        assert session.views["global"].video_id == "test-video-global-abc123"
        assert session.views["player1"].video_id == "test-video-player1-abc123"
        assert session.views["player2"].video_id == "test-video-player2-abc123"


class TestStreamManagerErrorHandling:
    """Test error handling and rollback"""

    def setup_method(self):
        """Set up mocks before each test"""
        self.k8s_patch = patch("stream_manager.kubernetes")
        self.mock_k8s = self.k8s_patch.start()

        self.yt_patch = patch("stream_manager.YouTubeClient")
        self.mock_yt_class = self.yt_patch.start()

        self.mock_yt_clients = {
            "global": create_mock_youtube_client("global"),
            "player1": create_mock_youtube_client("player1"),
            "player2": create_mock_youtube_client("player2"),
        }
        self.mock_yt_class.side_effect = lambda view: self.mock_yt_clients[view]

        self.mock_batch_api = MagicMock()
        self.mock_k8s.client.BatchV1Api.return_value = self.mock_batch_api

        # Disable readiness check for faster tests
        self.readiness_patch = patch("stream_manager.JOB_READINESS_TIMEOUT", 0)
        self.readiness_patch.start()

    def teardown_method(self):
        self.readiness_patch.stop()
        self.yt_patch.stop()
        self.k8s_patch.stop()

    @pytest.mark.asyncio
    async def test_rollback_on_second_view_failure(self):
        """Should clean up first view resources if second view fails"""
        from kubernetes.client.rest import ApiException

        # Global succeeds, player1 fails on job creation
        self.mock_batch_api.create_namespaced_job.side_effect = [
            MagicMock(),  # global job succeeds
            ApiException(status=500, reason="Internal Server Error"),  # player1 fails
        ]

        from stream_manager import StreamManager
        manager = StreamManager()

        with pytest.raises(Exception):
            await manager.start_stream(game_id="game123", civserver_port=6001)

        # Should have rolled back global stream and job
        self.mock_yt_clients["global"].delete_stream.assert_called_once()
        self.mock_batch_api.delete_namespaced_job.assert_called()

    @pytest.mark.asyncio
    async def test_retry_on_transient_k8s_error(self):
        """Should retry Job creation on transient errors"""
        from kubernetes.client.rest import ApiException

        # First call fails, subsequent succeed
        self.mock_batch_api.create_namespaced_job.side_effect = [
            ApiException(status=503, reason="Service Unavailable"),
            MagicMock(),  # global succeeds on retry
            MagicMock(),  # player1 succeeds
            MagicMock(),  # player2 succeeds
        ]

        from stream_manager import StreamManager
        manager = StreamManager()

        # Should succeed on retry
        result = await manager.start_stream(game_id="game123", civserver_port=6001)

        assert result["youtube_urls"]["global"] is not None
        # 4 calls: 1 failed + 3 successful
        assert self.mock_batch_api.create_namespaced_job.call_count == 4

    @pytest.mark.asyncio
    async def test_cleanup_orphaned_jobs_deletes_all_views(self):
        """Should clean up all 3 view jobs without active session"""
        from stream_manager import StreamManager
        manager = StreamManager()

        # Call cleanup directly without starting a stream
        await manager.cleanup_orphaned_jobs(game_id="orphan-game")

        # Should attempt to delete all 3 jobs
        assert self.mock_batch_api.delete_namespaced_job.call_count == 3


class TestStreamManagerStreamStatus:
    """Test stream status queries"""

    def setup_method(self):
        """Set up mocks before each test"""
        self.k8s_patch = patch("stream_manager.kubernetes")
        self.mock_k8s = self.k8s_patch.start()

        self.yt_patch = patch("stream_manager.YouTubeClient")
        self.mock_yt_class = self.yt_patch.start()

        self.mock_yt_clients = {
            "global": create_mock_youtube_client("global"),
            "player1": create_mock_youtube_client("player1"),
            "player2": create_mock_youtube_client("player2"),
        }
        self.mock_yt_class.side_effect = lambda view: self.mock_yt_clients[view]

        self.mock_batch_api = MagicMock()
        self.mock_k8s.client.BatchV1Api.return_value = self.mock_batch_api

        # Disable readiness check for faster tests
        self.readiness_patch = patch("stream_manager.JOB_READINESS_TIMEOUT", 0)
        self.readiness_patch.start()

    def teardown_method(self):
        self.readiness_patch.stop()
        self.yt_patch.stop()
        self.k8s_patch.stop()

    @pytest.mark.asyncio
    async def test_get_stream_status_returns_all_views(self):
        """Should return status for all 3 views"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="game123", civserver_port=6001)

        status = await manager.get_stream_status("game123")

        assert status is not None
        assert "views" in status
        assert "global" in status["views"]
        assert "player1" in status["views"]
        assert "player2" in status["views"]

    @pytest.mark.asyncio
    async def test_get_stream_status_includes_youtube_urls(self):
        """Status should include YouTube URLs for each view"""
        from stream_manager import StreamManager
        manager = StreamManager()

        await manager.start_stream(game_id="game123", civserver_port=6001)

        status = await manager.get_stream_status("game123")

        for view in ["global", "player1", "player2"]:
            assert "youtube_url" in status["views"][view]
            assert "youtube.com/watch" in status["views"][view]["youtube_url"]

    @pytest.mark.asyncio
    async def test_get_stream_status_returns_none_for_unknown_game(self):
        """Should return None for games without active streams"""
        from stream_manager import StreamManager
        manager = StreamManager()

        status = await manager.get_stream_status("nonexistent-game")

        assert status is None


class TestStreamManagerObserverURLWithPlayerNames:
    """Test observer URL generation with player names for fog-of-war"""

    def setup_method(self):
        """Set up mocks before each test"""
        self.k8s_patch = patch("stream_manager.kubernetes")
        self.mock_k8s = self.k8s_patch.start()

        self.yt_patch = patch("stream_manager.YouTubeClient")
        self.mock_yt_class = self.yt_patch.start()

        self.mock_yt_clients = {
            "global": create_mock_youtube_client("global"),
            "player1": create_mock_youtube_client("player1"),
            "player2": create_mock_youtube_client("player2"),
        }
        self.mock_yt_class.side_effect = lambda view: self.mock_yt_clients[view]

        self.mock_batch_api = MagicMock()
        self.mock_k8s.client.BatchV1Api.return_value = self.mock_batch_api

        # Disable readiness check for faster tests
        self.readiness_patch = patch("stream_manager.JOB_READINESS_TIMEOUT", 0)
        self.readiness_patch.start()

    def teardown_method(self):
        self.readiness_patch.stop()
        self.yt_patch.stop()
        self.k8s_patch.stop()

    @pytest.mark.asyncio
    async def test_player_observer_urls_include_observe_player_param(self):
        """Player views should include observe_player param when player_names provided"""
        from stream_manager import StreamManager
        manager = StreamManager()

        player_names = {
            "player1": "AI-Agent-Alpha",
            "player2": "AI-Agent-Beta",
        }

        await manager.start_stream(
            game_id="game123",
            civserver_port=6001,
            player_names=player_names
        )

        # Find player1 job and check observer URL
        for call_args in self.mock_batch_api.create_namespaced_job.call_args_list:
            job_body = call_args.kwargs.get("body") or call_args[1].get("body")
            if "player1" in job_body.metadata.name:
                container = job_body.spec.template.spec.containers[0]
                env_dict = {e.name: e.value for e in container.env}
                observer_url = env_dict["OBSERVER_URL"]
                assert "observe_player=AI-Agent-Alpha" in observer_url
                assert "follow=AI-Agent-Alpha" in observer_url

    @pytest.mark.asyncio
    async def test_global_view_never_has_observe_player_param(self):
        """Global view should never have observe_player even with player_names"""
        from stream_manager import StreamManager
        manager = StreamManager()

        player_names = {
            "player1": "AI-Agent-Alpha",
            "player2": "AI-Agent-Beta",
        }

        await manager.start_stream(
            game_id="game123",
            civserver_port=6001,
            player_names=player_names
        )

        # Find global job and check observer URL
        for call_args in self.mock_batch_api.create_namespaced_job.call_args_list:
            job_body = call_args.kwargs.get("body") or call_args[1].get("body")
            if "global" in job_body.metadata.name:
                container = job_body.spec.template.spec.containers[0]
                env_dict = {e.name: e.value for e in container.env}
                observer_url = env_dict["OBSERVER_URL"]
                assert "observe_player" not in observer_url
                assert "follow" not in observer_url


class TestStreamManagerGCSBackup:
    """Test GCS backup orchestration (upload handled by streaming container)"""

    def setup_method(self):
        """Set up mocks before each test"""
        self.k8s_patch = patch("stream_manager.kubernetes")
        self.mock_k8s = self.k8s_patch.start()

        self.yt_patch = patch("stream_manager.YouTubeClient")
        self.mock_yt_class = self.yt_patch.start()

        self.mock_yt_clients = {
            "global": create_mock_youtube_client("global"),
            "player1": create_mock_youtube_client("player1"),
            "player2": create_mock_youtube_client("player2"),
        }
        self.mock_yt_class.side_effect = lambda view: self.mock_yt_clients[view]

        self.mock_batch_api = MagicMock()
        self.mock_k8s.client.BatchV1Api.return_value = self.mock_batch_api

        # Disable readiness check for faster tests
        self.readiness_patch = patch("stream_manager.JOB_READINESS_TIMEOUT", 0)
        self.readiness_patch.start()

    def teardown_method(self):
        self.readiness_patch.stop()
        self.yt_patch.stop()
        self.k8s_patch.stop()

    @pytest.mark.asyncio
    async def test_uploads_local_backup_to_gcs_on_stop(self):
        """Should trigger GCS backup upload when stopping stream"""
        # GCS upload is handled by streaming container - manager just orchestrates
        with patch("stream_manager.StreamManager._upload_backup_to_gcs") as mock_upload:
            mock_upload.return_value = None

            from stream_manager import StreamManager
            manager = StreamManager()

            await manager.start_stream(game_id="game123", civserver_port=6001)
            await manager.stop_stream(game_id="game123")

            # GCS upload should be attempted
            mock_upload.assert_called_once_with("game123")


class TestStreamManagerReadinessCheck:
    """Test K8s Job readiness check functionality"""

    def setup_method(self):
        """Set up mocks before each test"""
        self.k8s_patch = patch("stream_manager.kubernetes")
        self.mock_k8s = self.k8s_patch.start()

        self.yt_patch = patch("stream_manager.YouTubeClient")
        self.mock_yt_class = self.yt_patch.start()

        self.mock_yt_clients = {
            "global": create_mock_youtube_client("global"),
            "player1": create_mock_youtube_client("player1"),
            "player2": create_mock_youtube_client("player2"),
        }
        self.mock_yt_class.side_effect = lambda view: self.mock_yt_clients[view]

        self.mock_batch_api = MagicMock()
        self.mock_core_api = MagicMock()
        self.mock_k8s.client.BatchV1Api.return_value = self.mock_batch_api
        self.mock_k8s.client.CoreV1Api.return_value = self.mock_core_api

    def teardown_method(self):
        self.yt_patch.stop()
        self.k8s_patch.stop()

    def _create_mock_pod(self, job_name, phase="Running"):
        """Helper to create a mock pod for a job"""
        pod = MagicMock()
        pod.metadata.name = f"{job_name}-xxxxx"
        pod.metadata.labels = {"job-name": job_name}
        pod.status.phase = phase
        return pod

    @pytest.mark.asyncio
    async def test_readiness_check_returns_true_when_pod_running(self):
        """Should return True when pod reaches Running state"""
        from stream_manager import StreamManager
        manager = StreamManager()

        # Mock pod list response with a running pod
        mock_pod = self._create_mock_pod("stream-game123-global", "Running")
        mock_pod_list = MagicMock()
        mock_pod_list.items = [mock_pod]
        self.mock_core_api.list_namespaced_pod.return_value = mock_pod_list

        result = await manager._wait_for_job_running(
            job_name="stream-game123-global",
            timeout=5.0,
            poll_interval=0.1
        )

        assert result is True
        self.mock_core_api.list_namespaced_pod.assert_called()

    @pytest.mark.asyncio
    async def test_readiness_check_returns_false_on_timeout(self):
        """Should return False (not raise) when timeout exceeded"""
        from stream_manager import StreamManager
        manager = StreamManager()

        # Mock pod list response with a pending pod
        mock_pod = self._create_mock_pod("stream-game123-global", "Pending")
        mock_pod_list = MagicMock()
        mock_pod_list.items = [mock_pod]
        self.mock_core_api.list_namespaced_pod.return_value = mock_pod_list

        result = await manager._wait_for_job_running(
            job_name="stream-game123-global",
            timeout=0.3,
            poll_interval=0.1
        )

        # Should return False, not raise an exception
        assert result is False

    @pytest.mark.asyncio
    async def test_readiness_check_returns_false_for_failed_pod(self):
        """Should stop waiting and return False when pod is Failed"""
        from stream_manager import StreamManager
        manager = StreamManager()

        # Mock pod list response with a failed pod
        mock_pod = self._create_mock_pod("stream-game123-global", "Failed")
        mock_pod_list = MagicMock()
        mock_pod_list.items = [mock_pod]
        self.mock_core_api.list_namespaced_pod.return_value = mock_pod_list

        result = await manager._wait_for_job_running(
            job_name="stream-game123-global",
            timeout=5.0,
            poll_interval=0.1
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_readiness_check_skipped_when_disabled(self):
        """Should skip readiness check when timeout is 0"""
        from stream_manager import StreamManager
        manager = StreamManager()

        result = await manager._wait_for_job_running(
            job_name="stream-game123-global",
            timeout=0,  # Disabled
            poll_interval=0.1
        )

        # Should immediately return True without checking
        assert result is True
        self.mock_core_api.list_namespaced_pod.assert_not_called()

    @pytest.mark.asyncio
    async def test_readiness_check_handles_api_errors_gracefully(self):
        """Should continue polling even if API errors occur"""
        from kubernetes.client.rest import ApiException
        from stream_manager import StreamManager
        manager = StreamManager()

        # First call errors, second succeeds with running pod
        mock_pod = self._create_mock_pod("stream-game123-global", "Running")
        mock_pod_list = MagicMock()
        mock_pod_list.items = [mock_pod]

        self.mock_core_api.list_namespaced_pod.side_effect = [
            ApiException(status=500, reason="Internal Server Error"),
            mock_pod_list,
        ]

        result = await manager._wait_for_job_running(
            job_name="stream-game123-global",
            timeout=5.0,
            poll_interval=0.1
        )

        assert result is True
        assert self.mock_core_api.list_namespaced_pod.call_count == 2

    @pytest.mark.asyncio
    async def test_start_stream_calls_readiness_check(self):
        """Should call readiness check for all jobs after creation"""
        # Mock pod responses for all jobs to be running
        mock_pods = {}
        for view in ["global", "player1", "player2"]:
            pod = self._create_mock_pod(f"stream-game123-{view}", "Running")
            mock_pods[f"stream-game123-{view}"] = pod

        def mock_list_pods(namespace, label_selector):
            job_name = label_selector.replace("job-name=", "")
            result = MagicMock()
            if job_name in mock_pods:
                result.items = [mock_pods[job_name]]
            else:
                result.items = []
            return result

        self.mock_core_api.list_namespaced_pod.side_effect = mock_list_pods

        from stream_manager import StreamManager
        manager = StreamManager()

        # Run start_stream
        await manager.start_stream(game_id="game123", civserver_port=6001)

        # Readiness check should have been called for each job
        # (3 views means at least 3 calls to list_namespaced_pod)
        assert self.mock_core_api.list_namespaced_pod.call_count >= 3
