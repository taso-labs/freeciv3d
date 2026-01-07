#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stream Manager for YouTube Live streaming of FreeCiv matches.

Manages:
- K8s Job creation/deletion for streaming containers
- YouTube broadcast lifecycle (create, bind, complete)
- Session storage of active streams
- GCS backup upload (stubbed for MVP)

MVP: Single global view only. Player views return None.
"""

import os
import logging
import asyncio
from typing import Optional
from dataclasses import dataclass, field

import kubernetes
from kubernetes.client.rest import ApiException

from youtube_client import YouTubeClient

logger = logging.getLogger(__name__)

# Configuration from environment
STREAM_NAMESPACE = os.environ.get("STREAM_NAMESPACE", "freeciv")
FREECIV_WEB_BASE_URL = os.environ.get(
    "GATEWAY_FREECIV_WEB_BASE_URL", "https://freeciv.clashai.live"
)
STREAMER_IMAGE = os.environ.get(
    "STREAMER_IMAGE", "us-central1-docker.pkg.dev/clashai-production/clashai-production-registry/fciv-streamer:latest"
)
MAX_JOB_RETRIES = int(os.environ.get("STREAM_JOB_MAX_RETRIES", "3"))
JOB_RETRY_DELAY = float(os.environ.get("STREAM_JOB_RETRY_DELAY", "2.0"))


@dataclass
class StreamSession:
    """Tracks an active stream for a game"""
    game_id: str
    video_id: str
    broadcast_id: str
    stream_id: str
    stream_key: str
    job_name: str


class StreamManager:
    """
    Manages YouTube Live streaming for FreeCiv matches.

    MVP: Creates one stream per game (global strategic view).
    Future: Will create 3 streams per game (global, player1, player2).
    """

    def __init__(self):
        """Initialize StreamManager with K8s and YouTube clients."""
        # Load K8s config (in-cluster or from kubeconfig)
        try:
            kubernetes.config.load_incluster_config()
            logger.info("Loaded in-cluster K8s config")
        except kubernetes.config.ConfigException:
            kubernetes.config.load_kube_config()
            logger.info("Loaded kubeconfig")

        self.batch_api = kubernetes.client.BatchV1Api()
        self.namespace = STREAM_NAMESPACE

        # YouTube client for global view (MVP)
        self.youtube_client = YouTubeClient("global")

        # Track active streams - protected by _streams_lock for concurrent access
        self.active_streams: dict[str, StreamSession] = {}
        self._streams_lock = asyncio.Lock()

    async def start_stream(self, game_id: str, civserver_port: int) -> dict:
        """
        Start streaming a game to YouTube.

        Args:
            game_id: Unique game identifier
            civserver_port: FreeCiv server port (6001-6009)

        Returns:
            dict with youtube_urls for each view:
                - global: YouTube URL for strategic view
                - player1: None (MVP stub)
                - player2: None (MVP stub)
        """
        logger.info(f"Starting stream for game {game_id} on port {civserver_port}")

        # Create YouTube broadcast and stream
        broadcast = await self.youtube_client.create_broadcast(
            title=f"ClashAI Match {game_id} - global",
            description=f"AI vs AI FreeCiv match - Global strategic view"
        )
        video_id = broadcast["video_id"]
        broadcast_id = broadcast["broadcast_id"]

        stream = await self.youtube_client.create_stream()
        stream_id = stream["stream_id"]
        stream_key = stream["stream_key"]

        # Bind broadcast to stream
        await self.youtube_client.bind_broadcast_to_stream(broadcast_id, stream_id)

        # Generate observer URL for global view
        observer_url = self._build_observer_url(civserver_port, "global")

        # Create K8s Job with retry
        job_name = f"stream-{game_id}-global"
        try:
            await self._create_job_with_retry(
                job_name=job_name,
                stream_key=stream_key,
                observer_url=observer_url,
            )
        except Exception as e:
            # Rollback: clean up YouTube resources
            logger.error(f"Job creation failed, rolling back YouTube resources: {e}")
            await self.youtube_client.delete_stream(stream_id)
            raise

        # Store session (thread-safe)
        async with self._streams_lock:
            self.active_streams[game_id] = StreamSession(
                game_id=game_id,
                video_id=video_id,
                broadcast_id=broadcast_id,
                stream_id=stream_id,
                stream_key=stream_key,
                job_name=job_name,
            )

        youtube_url = f"https://youtube.com/watch?v={video_id}"
        logger.info(f"Stream started: {youtube_url}")

        return {
            "youtube_urls": {
                "global": youtube_url,
                "player1": None,  # MVP stub
                "player2": None,  # MVP stub
            },
            "job_name": job_name,
        }

    async def stop_stream(self, game_id: str) -> None:
        """
        Stop streaming a game.

        Args:
            game_id: Game identifier to stop streaming
        """
        logger.info(f"Stopping stream for game {game_id}")

        # Get and remove session atomically (thread-safe)
        async with self._streams_lock:
            session = self.active_streams.pop(game_id, None)

        if session:
            # Transition broadcast to complete
            try:
                await self.youtube_client.transition_to_complete(session.broadcast_id)
            except Exception as e:
                logger.warning(f"Failed to transition broadcast to complete: {e}")

            # Delete K8s Job
            self._delete_job(session.job_name)

            # Upload backup to GCS (stubbed for MVP)
            await self._upload_backup_to_gcs(game_id)
        else:
            # No session found, try to clean up anyway
            logger.warning(f"No active session for game {game_id}, attempting cleanup")
            self._delete_job(f"stream-{game_id}-global")

    async def cleanup_orphaned_jobs(self, game_id: str) -> None:
        """
        Clean up jobs that may exist without an active session.

        Args:
            game_id: Game identifier to clean up
        """
        logger.info(f"Cleaning up orphaned jobs for game {game_id}")
        self._delete_job(f"stream-{game_id}-global")

    async def get_stream_status(self, game_id: str) -> Optional[dict]:
        """
        Get the status of a stream for a game.

        Args:
            game_id: Game identifier

        Returns:
            dict with stream status, or None if no stream exists
        """
        async with self._streams_lock:
            session = self.active_streams.get(game_id)

        if not session:
            return None

        return {
            "game_id": session.game_id,
            "video_id": session.video_id,
            "youtube_url": f"https://youtube.com/watch?v={session.video_id}",
            "job_name": session.job_name,
            "status": "active",
        }

    def _build_observer_url(self, civserver_port: int, view: str) -> str:
        """Build observer URL for the streaming container."""
        base_url = FREECIV_WEB_BASE_URL.rstrip("/")

        # Global view uses strategic camera
        camera = "strategic" if view == "global" else "cinematic"

        params = [
            "action=observe",
            f"civserverport={civserver_port}",
            f"camera={camera}",
            "embed=1",
            "autojoin=1",
            f"name=stream_{view}_{civserver_port}",
        ]

        return f"{base_url}/webclient/?{'&'.join(params)}"

    async def _create_job_with_retry(
        self, job_name: str, stream_key: str, observer_url: str
    ) -> None:
        """Create K8s Job with retry logic for transient errors."""
        last_error = None

        for attempt in range(MAX_JOB_RETRIES):
            try:
                self._create_job(job_name, stream_key, observer_url)
                return  # Success
            except ApiException as e:
                last_error = e
                if e.status in (500, 502, 503, 504):
                    # Transient error, retry
                    logger.warning(
                        f"Job creation failed (attempt {attempt + 1}/{MAX_JOB_RETRIES}): {e}"
                    )
                    await asyncio.sleep(JOB_RETRY_DELAY)
                else:
                    # Non-transient error, don't retry
                    raise

        # All retries exhausted
        raise last_error

    def _create_job(self, job_name: str, stream_key: str, observer_url: str) -> None:
        """Create a K8s Job for streaming."""
        job = kubernetes.client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=kubernetes.client.V1ObjectMeta(
                name=job_name,
                namespace=self.namespace,
                labels={
                    "app": "fciv-streamer",
                    "game-id": job_name.replace("stream-", "").replace("-global", ""),
                },
            ),
            spec=kubernetes.client.V1JobSpec(
                ttl_seconds_after_finished=300,  # Cleanup 5 min after completion
                backoff_limit=2,
                template=kubernetes.client.V1PodTemplateSpec(
                    metadata=kubernetes.client.V1ObjectMeta(
                        labels={"app": "fciv-streamer"},
                    ),
                    spec=kubernetes.client.V1PodSpec(
                        restart_policy="OnFailure",
                        # Pod anti-affinity: spread streaming jobs across nodes
                        # to prevent resource contention (FFmpeg is CPU-intensive)
                        affinity=kubernetes.client.V1Affinity(
                            pod_anti_affinity=kubernetes.client.V1PodAntiAffinity(
                                preferred_during_scheduling_ignored_during_execution=[
                                    kubernetes.client.V1WeightedPodAffinityTerm(
                                        weight=100,
                                        pod_affinity_term=kubernetes.client.V1PodAffinityTerm(
                                            label_selector=kubernetes.client.V1LabelSelector(
                                                match_labels={"app": "fciv-streamer"}
                                            ),
                                            topology_key="kubernetes.io/hostname",
                                        ),
                                    )
                                ]
                            )
                        ),
                        containers=[
                            kubernetes.client.V1Container(
                                name="streamer",
                                image=STREAMER_IMAGE,
                                env=[
                                    kubernetes.client.V1EnvVar(
                                        name="OBSERVER_URL", value=observer_url
                                    ),
                                    kubernetes.client.V1EnvVar(
                                        name="STREAM_KEY", value=stream_key
                                    ),
                                    kubernetes.client.V1EnvVar(
                                        name="RESOLUTION", value="1280x720"
                                    ),
                                    kubernetes.client.V1EnvVar(name="FPS", value="30"),
                                    kubernetes.client.V1EnvVar(
                                        name="BITRATE", value="2500k"
                                    ),
                                ],
                                resources=kubernetes.client.V1ResourceRequirements(
                                    requests={"cpu": "1000m", "memory": "2Gi"},
                                    limits={"cpu": "2000m", "memory": "4Gi"},
                                ),
                            )
                        ],
                    ),
                ),
            ),
        )

        self.batch_api.create_namespaced_job(namespace=self.namespace, body=job)
        logger.info(f"Created K8s Job: {job_name}")

    def _delete_job(self, job_name: str) -> None:
        """Delete a K8s Job, ignoring if not found."""
        try:
            self.batch_api.delete_namespaced_job(
                name=job_name,
                namespace=self.namespace,
                propagation_policy="Background",
            )
            logger.info(f"Deleted K8s Job: {job_name}")
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"Job {job_name} not found, skipping deletion")
            else:
                logger.error(f"Failed to delete job {job_name}: {e}")

    async def _upload_backup_to_gcs(self, game_id: str) -> None:
        """
        Upload local backup recording to GCS.

        MVP: Stubbed - actual GCS upload will be implemented later.
        The streaming container handles backup locally, and this method
        will trigger the upload after the Job completes.
        """
        logger.info(f"GCS backup upload for {game_id} - stubbed for MVP")
        # TODO: Implement GCS upload when streaming container is ready
        pass
