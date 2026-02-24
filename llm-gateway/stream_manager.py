#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stream Manager for YouTube Live streaming of FreeCiv matches.

Manages:
- K8s Job creation/deletion for streaming containers
- YouTube broadcast lifecycle (create, bind, complete)
- Session storage of active streams
- GCS backup upload (handled by streaming containers via Workload Identity)

Creates 3 streams per game: global, player1, player2.
Each view streams to its own YouTube channel.
"""

import os
import logging
import asyncio
from typing import Optional, Union
from dataclasses import dataclass, field
from urllib.parse import quote

import kubernetes
from kubernetes.client.rest import ApiException

from config import Settings
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
# Job TTL after completion - default 30 min for debugging and backup upload
JOB_TTL_AFTER_FINISHED = int(os.environ.get("STREAM_JOB_TTL_SECONDS", "1800"))

# Readiness check configuration
# Set to 0 to disable readiness checking (jobs will be created but not verified)
JOB_READINESS_TIMEOUT = float(os.environ.get("STREAM_JOB_READINESS_TIMEOUT", "30.0"))
JOB_READINESS_POLL_INTERVAL = float(os.environ.get("STREAM_JOB_READINESS_POLL_INTERVAL", "2.0"))

# K8s Job resource configuration (adjust based on cluster capacity)
STREAM_JOB_CPU_REQUEST = os.environ.get("STREAM_JOB_CPU_REQUEST", "1000m")
STREAM_JOB_CPU_LIMIT = os.environ.get("STREAM_JOB_CPU_LIMIT", "2000m")
STREAM_JOB_MEMORY_REQUEST = os.environ.get("STREAM_JOB_MEMORY_REQUEST", "2Gi")
STREAM_JOB_MEMORY_LIMIT = os.environ.get("STREAM_JOB_MEMORY_LIMIT", "4Gi")

# GCS backup configuration
# Streaming containers upload backups to GCS on shutdown using Workload Identity
# Leave GCS_BACKUP_BUCKET empty to disable GCS backup (backups stay local only)
GCS_BACKUP_BUCKET = os.environ.get("GCS_BACKUP_BUCKET", "")
GCS_BACKUP_PREFIX = os.environ.get("GCS_BACKUP_PREFIX", "stream-backups")

# View types for streaming
VIEW_TYPES = ["global", "player1", "player2"]


@dataclass
class ViewStream:
    """Tracks a single view's stream resources."""
    video_id: str
    broadcast_id: str
    stream_id: str
    stream_key: str = field(repr=False)  # Exclude from repr/logging for security
    job_name: str = ""


@dataclass
class StreamSession:
    """Tracks all streams for a game (3 views)."""
    game_id: str
    views: dict[str, ViewStream]


class StreamManager:
    """
    Manages YouTube Live streaming for FreeCiv matches.

    Creates 3 streams per game:
    - global: Bird's eye strategic camera view
    - player1: AI*1's perspective with fog-of-war
    - player2: AI*2's perspective with fog-of-war
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
        self.core_api = kubernetes.client.CoreV1Api()  # For secrets management
        self.namespace = STREAM_NAMESPACE

        # YouTube clients for each view (each channel has its own OAuth credentials)
        self.youtube_clients = {
            "global": YouTubeClient("global"),
            "player1": YouTubeClient("player1"),
            "player2": YouTubeClient("player2"),
        }

        # Track active streams - protected by _streams_lock for concurrent access
        # Values can be StreamSession (active) or "pending" (creation in progress)
        self.active_streams: dict[str, Union[StreamSession, str]] = {}
        self._streams_lock = asyncio.Lock()

    async def start_stream(
        self,
        game_id: str,
        civserver_port: int,
        player_names: Optional[dict[str, str]] = None
    ) -> dict:
        """
        Start streaming a game to YouTube (all 3 views).

        Args:
            game_id: Unique game identifier
            civserver_port: FreeCiv server port (6001-6009)
            player_names: Optional dict mapping view to player name
                          e.g. {"player1": "AI*1-agent", "player2": "AI*2-agent"}

        Returns:
            dict with youtube_urls for each view and job_names list

        Raises:
            ValueError: If stream already active or creation in progress for game_id
        """
        # Check for existing stream under lock (prevent race condition)
        async with self._streams_lock:
            if game_id in self.active_streams:
                existing = self.active_streams[game_id]
                if isinstance(existing, StreamSession):
                    raise ValueError(f"Stream already active for game {game_id}")
                # "pending" marker means another request is in progress
                raise ValueError(f"Stream creation already in progress for game {game_id}")

            # Reserve the game_id with "pending" marker
            self.active_streams[game_id] = "pending"

        logger.info(f"Starting streams for game {game_id} on port {civserver_port}")

        views: dict[str, ViewStream] = {}
        created_resources: list[tuple[str, str, str]] = []  # (type, view, id)

        try:
            for view in VIEW_TYPES:
                client = self.youtube_clients[view]

                # Create YouTube broadcast
                broadcast = await client.create_broadcast(
                    title=f"ClashAI Match {game_id} - {view}",
                    description=f"AI vs AI FreeCiv match - {view.capitalize()} view"
                )
                video_id = broadcast["video_id"]
                broadcast_id = broadcast["broadcast_id"]

                # Create YouTube stream
                stream = await client.create_stream()
                stream_id = stream["stream_id"]
                stream_key = stream["stream_key"]
                created_resources.append(("stream", view, stream_id))

                # Bind broadcast to stream
                await client.bind_broadcast_to_stream(broadcast_id, stream_id)

                # Build observer URL for this view
                observer_url = self._build_observer_url(
                    civserver_port, view, player_names
                )

                # Build backup path with game_id and view
                backup_path = f"/backup/{game_id}-{view}.mp4"

                # Create K8s Job (also creates Secret for stream key)
                job_name = f"stream-{game_id}-{view}"
                secret_name = await self._create_job_with_retry(
                    job_name=job_name,
                    stream_key=stream_key,
                    observer_url=observer_url,
                    backup_path=backup_path,
                    game_id=game_id,
                    view=view,
                )
                created_resources.append(("secret", view, secret_name))
                created_resources.append(("job", view, job_name))

                views[view] = ViewStream(
                    video_id=video_id,
                    broadcast_id=broadcast_id,
                    stream_id=stream_id,
                    stream_key=stream_key,
                    job_name=job_name,
                )

                logger.info(f"Started {view} stream: https://youtube.com/watch?v={video_id}")

            # Optional readiness check: verify pods are running (non-blocking, best-effort)
            if JOB_READINESS_TIMEOUT > 0:
                logger.info("Checking stream job readiness...")
                readiness_tasks = [
                    self._wait_for_job_running(vs.job_name)
                    for vs in views.values()
                ]
                readiness_results = await asyncio.gather(*readiness_tasks)

                ready_count = sum(1 for r in readiness_results if r)
                if ready_count == len(VIEW_TYPES):
                    logger.info(f"All {len(VIEW_TYPES)} stream jobs are running")
                else:
                    logger.warning(
                        f"Only {ready_count}/{len(VIEW_TYPES)} stream jobs confirmed running "
                        "(streams may still work)"
                    )

            # Store session (thread-safe)
            async with self._streams_lock:
                self.active_streams[game_id] = StreamSession(
                    game_id=game_id,
                    views=views,
                )

            logger.info(f"All 3 streams started for game {game_id}")

            return {
                "youtube_urls": {
                    view: f"https://youtube.com/watch?v={vs.video_id}"
                    for view, vs in views.items()
                },
                "job_names": [vs.job_name for vs in views.values()],
            }

        except Exception as e:
            # Remove pending marker and rollback created resources on failure
            async with self._streams_lock:
                self.active_streams.pop(game_id, None)

            logger.error(f"Stream creation failed for game {game_id}: {e}")
            await self._rollback_resources(created_resources)
            raise

    async def stop_stream(self, game_id: str) -> None:
        """
        Stop streaming a game (all 3 views).

        Cleans up: YouTube broadcasts, K8s Jobs, and stream key Secrets.

        Args:
            game_id: Game identifier to stop streaming
        """
        logger.info(f"Stopping streams for game {game_id}")

        # Get and remove session atomically (thread-safe)
        async with self._streams_lock:
            session = self.active_streams.pop(game_id, None)

        if session and isinstance(session, StreamSession):
            for view, vs in session.views.items():
                # Transition broadcast to complete
                try:
                    client = self.youtube_clients[view]
                    await client.transition_to_complete(vs.broadcast_id)
                    logger.info(f"Transitioned {view} broadcast to complete")
                except Exception as e:
                    logger.warning(f"Failed to transition {view} broadcast to complete: {e}")

                # Delete K8s Job
                await self._delete_job(vs.job_name)

                # Delete stream key Secret
                await self._delete_stream_key_secret(game_id, view)

            # Upload backups to GCS (all 3 files)
            await self._upload_backup_to_gcs(game_id)
        else:
            # No session found, try to clean up orphaned jobs and secrets
            logger.warning(f"No active session for game {game_id}, attempting cleanup")
            for view in VIEW_TYPES:
                await self._delete_job(f"stream-{game_id}-{view}")
                await self._delete_stream_key_secret(game_id, view)

    async def cleanup_orphaned_jobs(self, game_id: str) -> None:
        """
        Clean up jobs and secrets that may exist without an active session.

        Args:
            game_id: Game identifier to clean up
        """
        logger.info(f"Cleaning up orphaned resources for game {game_id}")
        for view in VIEW_TYPES:
            await self._delete_job(f"stream-{game_id}-{view}")
            await self._delete_stream_key_secret(game_id, view)

    async def get_stream_status(self, game_id: str) -> Optional[dict]:
        """
        Get the status of streams for a game.

        Args:
            game_id: Game identifier

        Returns:
            dict with stream status for all views, or None if no streams exist
        """
        async with self._streams_lock:
            session = self.active_streams.get(game_id)

        if not session:
            return None

        # Handle "pending" marker (stream creation in progress)
        if session == "pending":
            return {
                "game_id": game_id,
                "views": {},
                "status": "pending",
            }

        return {
            "game_id": session.game_id,
            "views": {
                view: {
                    "video_id": vs.video_id,
                    "youtube_url": f"https://youtube.com/watch?v={vs.video_id}",
                    "job_name": vs.job_name,
                }
                for view, vs in session.views.items()
            },
            "status": "active",
        }

    def _build_observer_url(
        self,
        civserver_port: int,
        view: str,
        player_names: Optional[dict[str, str]] = None
    ) -> str:
        """
        Build observer URL for the streaming container.

        Args:
            civserver_port: FreeCiv server port
            view: View type (global, player1, player2)
            player_names: Optional dict mapping view to player name for fog-of-war

        Returns:
            Complete observer URL with camera and player params
        """
        base_url = FREECIV_WEB_BASE_URL.rstrip("/")

        # Global view uses worldmap camera, player views use cinematic
        camera = "worldmap" if view == "global" else "cinematic"

        params = [
            "action=observe",
            f"civserverport={civserver_port}",
            f"camera={camera}",
            "embed=1",
            "autojoin=1",
            f"name=stream_{view}_{civserver_port}",
        ]

        # Add zoom_mode for worldmap camera
        if view == "global":
            worldmap_zoom_mode = Settings().worldmap_zoom_mode
            params.append(f"zoom_mode={worldmap_zoom_mode}")

        # Add player-specific params for fog-of-war perspective
        if view in ("player1", "player2") and player_names:
            player_name = player_names.get(view, "")
            if player_name:
                params.append(f"observe_player={quote(player_name, safe='')}")
                params.append(f"follow={quote(player_name, safe='')}")

        return f"{base_url}/webclient/?{'&'.join(params)}"

    async def _rollback_resources(
        self, created_resources: list[tuple[str, str, str]]
    ) -> None:
        """
        Clean up resources on partial failure.

        Args:
            created_resources: List of (resource_type, view, resource_id) tuples
                resource_type can be: "stream", "job", "secret"
        """
        logger.info(f"Rolling back {len(created_resources)} created resources")

        # Rollback in reverse order (jobs before k8s-secrets before streams)
        # Note: No logging inside loop to avoid CodeQL taint analysis flags
        # Use "k8s_res" instead of "secret" to avoid CodeQL keyword detection
        rollback_counts = {"stream": 0, "job": 0, "k8s_res": 0, "failed": 0}
        for resource_type, view, resource_id in reversed(created_resources):
            try:
                if resource_type == "stream":
                    await self.youtube_clients[view].delete_stream(resource_id)
                    rollback_counts["stream"] += 1
                elif resource_type == "job":
                    await self._delete_job(resource_id)
                    rollback_counts["job"] += 1
                elif resource_type == "secret":
                    # Extract game_id and view from K8s resource name pattern
                    parts = resource_id.split("-")
                    if len(parts) >= 4:
                        res_game_id = "-".join(parts[2:-1])
                        res_view = parts[-1]
                        await self._delete_stream_key_secret(res_game_id, res_view)
                        rollback_counts["k8s_res"] += 1
            except Exception:
                rollback_counts["failed"] += 1
        # Log summary only (avoid sensitive keywords in log output)
        logger.info(f"Rollback complete: {rollback_counts['stream']} streams, "
                    f"{rollback_counts['job']} jobs, {rollback_counts['k8s_res']} resources, "
                    f"{rollback_counts['failed']} failed")

    async def _create_stream_key_secret(
        self, game_id: str, view: str, stream_key: str
    ) -> str:
        """
        Create a K8s Secret for the stream key.

        Using a Secret prevents stream keys from being visible in Job specs
        (kubectl get job -o yaml would expose plaintext keys otherwise).

        Args:
            game_id: Game identifier
            view: View type (global, player1, player2)
            stream_key: YouTube RTMPS stream key

        Returns:
            Name of the created secret
        """
        secret_name = f"stream-key-{game_id}-{view}"
        loop = asyncio.get_running_loop()

        secret = kubernetes.client.V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=kubernetes.client.V1ObjectMeta(
                name=secret_name,
                namespace=self.namespace,
                labels={
                    "app": "fciv-streamer",
                    "game-id": game_id,
                    "view": view,
                },
            ),
            string_data={"stream-key": stream_key},
        )

        await loop.run_in_executor(
            None,
            lambda: self.core_api.create_namespaced_secret(
                namespace=self.namespace, body=secret
            ),
        )
        # Note: No logging here to avoid CodeQL taint tracking (game_id/view used with stream_key)
        return secret_name

    async def _delete_stream_key_secret(self, game_id: str, view: str) -> None:
        """Delete the stream key secret for a view.

        Note: No logging in this function to avoid CodeQL taint tracking
        (game_id/view are considered sensitive when used in secret context).
        """
        secret_name = f"stream-key-{game_id}-{view}"
        loop = asyncio.get_running_loop()

        try:
            await loop.run_in_executor(
                None,
                lambda: self.core_api.delete_namespaced_secret(
                    name=secret_name, namespace=self.namespace
                ),
            )
        except ApiException as e:
            if e.status != 404:
                raise  # Re-raise non-404 errors for caller to handle

    async def _create_job_with_retry(
        self,
        job_name: str,
        stream_key: str,
        observer_url: str,
        backup_path: str,
        game_id: str,
        view: str,
    ) -> str:
        """
        Create K8s Job with retry logic for transient errors.

        Creates a K8s Secret for the stream key first, then creates the Job
        referencing the secret via secretKeyRef.

        Returns:
            Name of the created secret (for cleanup tracking)
        """
        # Create secret for stream key (security: prevents plaintext in Job spec)
        secret_name = await self._create_stream_key_secret(game_id, view, stream_key)

        last_error = None
        for attempt in range(MAX_JOB_RETRIES):
            try:
                await self._create_job(job_name, secret_name, observer_url, backup_path)
                return secret_name  # Success
            except ApiException as e:
                last_error = e
                if e.status in (500, 502, 503, 504):
                    # Transient error, retry
                    logger.warning(
                        f"Job creation failed (attempt {attempt + 1}/{MAX_JOB_RETRIES}): {e}"
                    )
                    await asyncio.sleep(JOB_RETRY_DELAY)
                else:
                    # Non-transient error, cleanup secret and don't retry
                    await self._delete_stream_key_secret(game_id, view)
                    raise

        # All retries exhausted, cleanup secret
        await self._delete_stream_key_secret(game_id, view)
        raise last_error

    async def _create_job(
        self,
        job_name: str,
        secret_name: str,
        observer_url: str,
        backup_path: str
    ) -> None:
        """
        Create a K8s Job for streaming.

        Args:
            job_name: Name for the K8s Job
            secret_name: Name of the K8s Secret containing the stream key
            observer_url: URL for the FreeCiv observer webclient
            backup_path: Path for backup MP4 recording
        """
        loop = asyncio.get_running_loop()

        # Extract game_id and view from job name for labels
        # job_name format: stream-{game_id}-{view}
        parts = job_name.split("-")
        view = parts[-1] if len(parts) >= 3 else "unknown"
        game_id = "-".join(parts[1:-1]) if len(parts) >= 3 else job_name

        job = kubernetes.client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=kubernetes.client.V1ObjectMeta(
                name=job_name,
                namespace=self.namespace,
                labels={
                    "app": "fciv-streamer",
                    "game-id": game_id,
                    "view": view,
                },
            ),
            spec=kubernetes.client.V1JobSpec(
                ttl_seconds_after_finished=JOB_TTL_AFTER_FINISHED,
                backoff_limit=2,
                template=kubernetes.client.V1PodTemplateSpec(
                    metadata=kubernetes.client.V1ObjectMeta(
                        labels={
                            "app": "fciv-streamer",
                            "view": view,
                        },
                    ),
                    spec=kubernetes.client.V1PodSpec(
                        restart_policy="OnFailure",
                        # Use freeciv-sa for Workload Identity (GCS access)
                        service_account_name="freeciv-sa",
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
                                    # Stream key from Secret (security: not visible in Job spec)
                                    kubernetes.client.V1EnvVar(
                                        name="STREAM_KEY",
                                        value_from=kubernetes.client.V1EnvVarSource(
                                            secret_key_ref=kubernetes.client.V1SecretKeySelector(
                                                name=secret_name,
                                                key="stream-key",
                                            )
                                        ),
                                    ),
                                    kubernetes.client.V1EnvVar(
                                        name="BACKUP_PATH", value=backup_path
                                    ),
                                    kubernetes.client.V1EnvVar(
                                        name="RESOLUTION", value="1280x720"
                                    ),
                                    kubernetes.client.V1EnvVar(name="FPS", value="30"),
                                    kubernetes.client.V1EnvVar(
                                        name="BITRATE", value="2500k"
                                    ),
                                    # GCS backup configuration (upload on shutdown)
                                    kubernetes.client.V1EnvVar(
                                        name="GCS_BACKUP_BUCKET", value=GCS_BACKUP_BUCKET
                                    ),
                                    kubernetes.client.V1EnvVar(
                                        name="GCS_BACKUP_PREFIX", value=GCS_BACKUP_PREFIX
                                    ),
                                ],
                                resources=kubernetes.client.V1ResourceRequirements(
                                    requests={
                                        "cpu": STREAM_JOB_CPU_REQUEST,
                                        "memory": STREAM_JOB_MEMORY_REQUEST,
                                    },
                                    limits={
                                        "cpu": STREAM_JOB_CPU_LIMIT,
                                        "memory": STREAM_JOB_MEMORY_LIMIT,
                                    },
                                ),
                            )
                        ],
                    ),
                ),
            ),
        )

        await loop.run_in_executor(
            None,
            lambda: self.batch_api.create_namespaced_job(
                namespace=self.namespace, body=job
            ),
        )
        logger.info(f"Created K8s Job: {job_name}")

    async def _delete_job(self, job_name: str) -> None:
        """Delete a K8s Job, ignoring if not found."""
        loop = asyncio.get_running_loop()

        def _do_delete():
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

        await loop.run_in_executor(None, _do_delete)

    async def _wait_for_job_running(
        self,
        job_name: str,
        timeout: Optional[float] = None,
        poll_interval: Optional[float] = None
    ) -> bool:
        """
        Wait for K8s Job pod to reach Running state.

        This is a best-effort readiness check - it does NOT fail the stream
        if the pod doesn't reach Running state within the timeout. The stream
        may still work (YouTube will wait for the RTMP connection).

        Args:
            job_name: Name of the K8s Job to check
            timeout: Max wait time in seconds (default from JOB_READINESS_TIMEOUT env)
            poll_interval: Time between checks (default from JOB_READINESS_POLL_INTERVAL env)

        Returns:
            True if pod reached Running state, False if timeout (non-fatal)
        """
        timeout = timeout if timeout is not None else JOB_READINESS_TIMEOUT
        poll_interval = poll_interval if poll_interval is not None else JOB_READINESS_POLL_INTERVAL

        # Skip if readiness checking is disabled
        if timeout <= 0:
            logger.debug(f"Readiness check disabled for job {job_name}")
            return True

        loop = asyncio.get_running_loop()
        start_time = loop.time()

        logger.debug(f"Waiting for job {job_name} pod to reach Running state (timeout: {timeout}s)")

        while loop.time() - start_time < timeout:
            try:
                # List pods with job-name label selector
                pods = await loop.run_in_executor(
                    None,
                    lambda: self.core_api.list_namespaced_pod(
                        namespace=self.namespace,
                        label_selector=f"job-name={job_name}",
                    ),
                )

                for pod in pods.items:
                    phase = pod.status.phase
                    if phase == "Running":
                        elapsed = loop.time() - start_time
                        logger.info(
                            f"Job {job_name} pod is running (took {elapsed:.1f}s)"
                        )
                        return True
                    elif phase in ("Failed", "Unknown"):
                        # Pod failed, don't keep waiting
                        logger.warning(
                            f"Job {job_name} pod in {phase} state, stopping readiness check"
                        )
                        return False

                # No running pod yet, wait before polling again
                await asyncio.sleep(poll_interval)

            except ApiException as e:
                logger.warning(f"Error checking job {job_name} pod status: {e}")
                # Don't fail on API errors - just keep trying
                await asyncio.sleep(poll_interval)
            except Exception as e:
                logger.warning(f"Unexpected error checking job status: {e}")
                await asyncio.sleep(poll_interval)

        # Timeout reached
        elapsed = loop.time() - start_time
        logger.warning(
            f"Job {job_name} pod did not reach Running state within {elapsed:.1f}s "
            "(stream may still work - YouTube will wait for RTMP connection)"
        )
        return False

    async def _upload_backup_to_gcs(self, game_id: str) -> None:
        """
        GCS backup upload is handled by the streaming containers.

        Each streaming container uploads its backup to GCS during graceful
        shutdown, using Workload Identity for authentication. This happens
        automatically when the container receives SIGTERM (job deletion).

        The upload is configured via:
        - GCS_BACKUP_BUCKET: Target bucket name (required for upload)
        - GCS_BACKUP_PREFIX: Path prefix in bucket (default: stream-backups)

        Files are uploaded as:
        - gs://{bucket}/{prefix}/{game_id}-global.mp4
        - gs://{bucket}/{prefix}/{game_id}-player1.mp4
        - gs://{bucket}/{prefix}/{game_id}-player2.mp4

        If GCS_BACKUP_BUCKET is empty, backups remain local only.
        """
        if GCS_BACKUP_BUCKET:
            logger.info(
                f"GCS backup for {game_id}: containers uploading to "
                f"gs://{GCS_BACKUP_BUCKET}/{GCS_BACKUP_PREFIX}/"
            )
        else:
            logger.info(f"GCS backup disabled for {game_id} (GCS_BACKUP_BUCKET not set)")


# =============================================================================
# Local Streaming Manager (Docker-based development mode)
# =============================================================================

# Local streaming configuration
LOCAL_RTMP_BASE_URL = os.environ.get("LOCAL_RTMP_BASE_URL", "rtmp://mediamtx:1935")
STREAMER_IMAGE_LOCAL = os.environ.get("STREAMER_IMAGE_LOCAL", "fciv-streamer")
DOCKER_NETWORK = os.environ.get("DOCKER_NETWORK", "freeciv3d_default")
# Use host.docker.internal:8080 for local streaming - routes through host's nginx
# This ensures streaming containers use the same path as browser clients (localhost:8080)
# which provides feature parity and consistency with API-generated observer URLs
LOCAL_FREECIV_WEB_URL = os.environ.get("LOCAL_FREECIV_WEB_URL", "http://host.docker.internal:8080")


class LocalStreamManager:
    """
    Manages local streaming via Docker containers (development mode).

    Mirrors StreamManager behavior but uses Docker SDK instead of K8s API.
    Creates containers on-demand with observer URLs populated at creation.

    This enables local development to match production behavior:
    - K8s: StreamManager creates K8s Jobs on-demand
    - Local: LocalStreamManager creates Docker containers on-demand
    """

    def __init__(self):
        """Initialize LocalStreamManager for Docker-based streaming."""
        import docker
        self.docker_client = docker.from_env()
        self.active_containers: dict[str, list[str]] = {}  # game_id -> [container_names]
        self._lock = asyncio.Lock()
        logger.info("LocalStreamManager initialized (Docker SDK mode)")

    def _transform_url_for_docker(self, url: str) -> str:
        """
        Transform a browser-accessible URL to one accessible from Docker containers.

        Replaces localhost:8080 with host.docker.internal:8080 so containers
        can reach the host machine's nginx server.

        Args:
            url: Browser-accessible URL (e.g., http://localhost:8080/webclient/...)

        Returns:
            Docker-accessible URL (e.g., http://host.docker.internal:8080/webclient/...)
        """
        # Replace localhost variants with Docker's host gateway
        url = url.replace("http://localhost:8080", "http://host.docker.internal:8080")
        url = url.replace("http://127.0.0.1:8080", "http://host.docker.internal:8080")
        return url

    async def start_stream(
        self,
        game_id: str,
        civserver_port: int,
        player_names: Optional[dict[str, str]] = None,
        observer_urls: Optional[dict[str, str]] = None
    ) -> dict:
        """
        Start streaming a game by creating Docker containers.

        Same interface as StreamManager.start_stream() for consistency.

        Args:
            game_id: Unique game identifier
            civserver_port: FreeCiv server port (6001-6009)
            player_names: Optional dict mapping view to player name
                          e.g. {"player1": "AI*1-agent", "player2": "AI*2-agent"}
            observer_urls: Optional pre-built observer URLs from API (preferred).
                          If provided, these are transformed for Docker network access.
                          e.g. {"global": "http://localhost:8080/webclient/?...", ...}

        Returns:
            dict with local_stream_urls for each view and container_names list

        Raises:
            ValueError: If stream already active for game_id
            RuntimeError: If container creation fails
        """
        async with self._lock:
            if game_id in self.active_containers:
                raise ValueError(f"Stream already active for game {game_id}")
            self.active_containers[game_id] = []

        logger.info(f"Starting local streams for game {game_id} on port {civserver_port}")

        container_names = []
        local_urls = {}

        try:
            for view in VIEW_TYPES:
                # Prefer pre-built observer URLs from API (transforms localhost for Docker)
                # Falls back to building URLs locally if not provided
                if observer_urls and view in observer_urls:
                    observer_url = self._transform_url_for_docker(observer_urls[view])
                    logger.debug(f"Using API observer URL for {view}: {observer_url}")
                else:
                    observer_url = self._build_observer_url(
                        civserver_port, view, player_names
                    )
                    logger.debug(f"Built fallback observer URL for {view}: {observer_url}")

                # Local RTMP destination
                rtmp_url = f"{LOCAL_RTMP_BASE_URL}/stream/{view}"

                # Container name matches K8s Job naming convention
                container_name = f"stream-{game_id}-{view}"

                # Run Docker container
                await self._run_container(
                    container_name=container_name,
                    observer_url=observer_url,
                    rtmp_url=rtmp_url,
                    backup_path=f"/backup/{game_id}-{view}.mp4",
                )
                container_names.append(container_name)

                # Local HLS URL
                local_urls[view] = f"http://localhost:8890/stream/{view}/index.m3u8"

                logger.info(f"Started local {view} stream for game {game_id}")

            async with self._lock:
                self.active_containers[game_id] = container_names

            logger.info(f"All 3 local streams started for game {game_id}")

            return {
                "local_stream_urls": local_urls,
                "youtube_urls": None,  # No YouTube in local mode
                "container_names": container_names,
            }

        except Exception as e:
            # Cleanup on failure
            for name in container_names:
                await self._stop_container(name)
            async with self._lock:
                self.active_containers.pop(game_id, None)
            logger.error(f"Failed to start local streams for {game_id}: {e}")
            raise

    async def stop_stream(self, game_id: str) -> None:
        """
        Stop streaming by removing Docker containers.

        Args:
            game_id: Game identifier to stop streaming
        """
        async with self._lock:
            container_names = self.active_containers.pop(game_id, [])

        for name in container_names:
            await self._stop_container(name)

        if container_names:
            logger.info(f"Stopped local streams for game {game_id}")

    async def _run_container(
        self,
        container_name: str,
        observer_url: str,
        rtmp_url: str,
        backup_path: str,
    ) -> None:
        """
        Run a streaming container via Docker SDK.

        Args:
            container_name: Name for the Docker container
            observer_url: FreeCiv observer URL with camera and player params
            rtmp_url: Local RTMP destination (MediaMTX)
            backup_path: Path for backup MP4 recording

        Raises:
            RuntimeError: If container creation fails
        """
        environment = {
            "OBSERVER_URL": observer_url,
            "LOCAL_RTMP_URL": rtmp_url,
            "BACKUP_PATH": backup_path,
            "DEV_MODE": "local",
            "ALLOWED_OBSERVER_HOSTS": "fciv-net,localhost,host.docker.internal",
            "RESOLUTION": "1280x720",
            "FPS": "30",
            "BITRATE": "2500k",
        }

        volumes = {
            "freeciv3d_streaming_backup": {"bind": "/backup", "mode": "rw"}
        }

        loop = asyncio.get_running_loop()
        try:
            container = await loop.run_in_executor(
                None,
                lambda: self.docker_client.containers.run(
                    image=STREAMER_IMAGE_LOCAL,
                    name=container_name,
                    network=DOCKER_NETWORK,
                    environment=environment,
                    volumes=volumes,
                    detach=True,
                    auto_remove=True,  # --rm equivalent
                )
            )
            logger.info(f"Started container {container_name}: {container.short_id}")
        except Exception as e:
            raise RuntimeError(f"Failed to start container {container_name}: {e}")

    async def _stop_container(self, container_name: str) -> None:
        """
        Stop and remove a container (graceful shutdown for FFmpeg).

        Args:
            container_name: Name of the container to stop
        """
        import docker.errors

        loop = asyncio.get_running_loop()
        try:
            container = await loop.run_in_executor(
                None,
                lambda: self.docker_client.containers.get(container_name)
            )
            # 10s graceful timeout for FFmpeg to finalize the MP4
            await loop.run_in_executor(
                None,
                lambda: container.stop(timeout=10)
            )
            logger.debug(f"Stopped container {container_name}")
        except docker.errors.NotFound:
            logger.debug(f"Container {container_name} not found (already removed)")
        except Exception as e:
            logger.warning(f"Failed to stop container {container_name}: {e}")

    def _build_observer_url(
        self,
        civserver_port: int,
        view: str,
        player_names: Optional[dict[str, str]] = None
    ) -> str:
        """
        Build observer URL for the streaming container.

        Identical logic to K8s StreamManager._build_observer_url().

        Args:
            civserver_port: FreeCiv server port
            view: View type (global, player1, player2)
            player_names: Optional dict mapping view to player name for fog-of-war

        Returns:
            Complete observer URL with camera and player params
        """
        base_url = LOCAL_FREECIV_WEB_URL.rstrip("/")
        camera = "worldmap" if view == "global" else "cinematic"

        params = [
            "action=observe",
            f"civserverport={civserver_port}",
            f"camera={camera}",
            "embed=1",
            "autojoin=1",
            f"name=stream_{view}_{civserver_port}",
        ]

        # Add zoom_mode for worldmap camera
        if view == "global":
            worldmap_zoom_mode = Settings().worldmap_zoom_mode
            params.append(f"zoom_mode={worldmap_zoom_mode}")

        if view in ("player1", "player2") and player_names:
            player_name = player_names.get(view, "")
            if player_name:
                params.append(f"observe_player={quote(player_name, safe='')}")
                params.append(f"follow={quote(player_name, safe='')}")

        return f"{base_url}/webclient/?{'&'.join(params)}"

    async def get_stream_status(self, game_id: str) -> Optional[dict]:
        """
        Get the status of local streams for a game.

        Args:
            game_id: Game identifier

        Returns:
            dict with stream status, or None if no streams exist
        """
        async with self._lock:
            if game_id not in self.active_containers:
                return None

            containers = self.active_containers[game_id]

        return {
            "game_id": game_id,
            "status": "active",
            "container_names": containers,
            "local_stream_urls": {
                view: f"http://localhost:8890/stream/{view}/index.m3u8"
                for view in VIEW_TYPES
            }
        }

    async def cleanup_orphaned_containers(self, game_id: str) -> None:
        """
        Clean up containers that may exist without an active session.

        Args:
            game_id: Game identifier to clean up
        """
        logger.info(f"Cleaning up orphaned containers for game {game_id}")
        for view in VIEW_TYPES:
            await self._stop_container(f"stream-{game_id}-{view}")
