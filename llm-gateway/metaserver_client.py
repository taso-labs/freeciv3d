#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Metaserver Client for FreeCiv Server Allocation
Handles requesting and releasing game servers from the FreeCiv metaserver
"""

import asyncio
import logging
from typing import Dict, Any, Optional
import aiohttp

logger = logging.getLogger("llm-gateway")


class MetaserverClient:
    """Client for interacting with FreeCiv metaserver allocation API"""

    def __init__(self, metaserver_url: str = "http://localhost:8080"):
        self.metaserver_url = metaserver_url
        self.allocate_endpoint = f"{metaserver_url}/freeciv-web/meta/allocate"
        self.release_endpoint = f"{metaserver_url}/freeciv-web/meta/release"
        self.status_endpoint = f"{metaserver_url}/freeciv-web/meta/status"

    async def allocate_server(self, game_type: str = "multiplayer") -> Optional[Dict[str, Any]]:
        """
        Allocate a game server from the metaserver pool

        Args:
            game_type: Type of game (multiplayer, singleplayer, pbem, longturn)

        Returns:
            Dict with server details: {"host": str, "port": int, "proxy_port": int, "type": str}
            None if allocation failed
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.allocate_endpoint,
                    data={"type": game_type},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success"):
                            logger.info(
                                f"Allocated server: {data['host']}:{data['port']} "
                                f"(proxy: {data['proxy_port']})"
                            )
                            return {
                                "host": data["host"],
                                "port": data["port"],
                                "proxy_port": data["proxy_port"],
                                "type": data["type"]
                            }
                        else:
                            logger.error(f"Server allocation failed: {data.get('error', 'Unknown error')}")
                            return None

                    elif response.status == 503:
                        data = await response.json()
                        logger.warning(f"No available servers: {data.get('error', 'Service unavailable')}")
                        return None

                    else:
                        error_text = await response.text()
                        logger.error(f"Server allocation failed with status {response.status}: {error_text}")
                        return None

        except asyncio.TimeoutError:
            logger.error("Server allocation request timed out")
            return None
        except Exception as e:
            logger.error(f"Error allocating server: {e}")
            return None

    async def release_server(self, host: str, port: int) -> bool:
        """
        Release a game server back to the available pool

        Args:
            host: Server hostname
            port: Server port (6000-6009)

        Returns:
            True if successfully released, False otherwise
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.release_endpoint,
                    data={"host": host, "port": port},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success"):
                            logger.info(f"Released server: {host}:{port}")
                            return True
                        else:
                            logger.error(f"Server release failed: {data.get('error', 'Unknown error')}")
                            return False
                    else:
                        error_text = await response.text()
                        logger.error(f"Server release failed with status {response.status}: {error_text}")
                        return False

        except asyncio.TimeoutError:
            logger.error("Server release request timed out")
            return False
        except Exception as e:
            logger.error(f"Error releasing server: {e}")
            return False

    async def get_server_status(self) -> Optional[Dict[str, int]]:
        """
        Get current metaserver status

        Returns:
            Dict with status: {"total": int, "single": int, "multi": int}
            None if request failed
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.status_endpoint,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        text = await response.text()
                        # Parse status format: "meta-status;total;single;multi"
                        parts = text.strip().split(";")
                        if len(parts) == 4 and parts[0] == "meta-status":
                            return {
                                "total": int(parts[1]),
                                "single": int(parts[2]),
                                "multi": int(parts[3])
                            }
                        else:
                            logger.error(f"Invalid status format: {text}")
                            return None
                    else:
                        logger.error(f"Status request failed with status {response.status}")
                        return None

        except Exception as e:
            logger.error(f"Error getting server status: {e}")
            return None

    async def allocate_with_retry(
        self,
        game_type: str = "multiplayer",
        max_attempts: int = 3,
        retry_delay: float = 2.0
    ) -> Optional[Dict[str, Any]]:
        """
        Allocate a server with automatic retries

        Args:
            game_type: Type of game
            max_attempts: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds

        Returns:
            Server details dict or None if all attempts failed
        """
        for attempt in range(max_attempts):
            logger.info(f"Server allocation attempt {attempt + 1}/{max_attempts}")

            result = await self.allocate_server(game_type)
            if result:
                return result

            if attempt < max_attempts - 1:
                # Check server status before retrying
                status = await self.get_server_status()
                if status and status.get("multi", 0) == 0:
                    logger.warning("No multiplayer servers available. Waiting for servers to become available...")
                    await asyncio.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                else:
                    await asyncio.sleep(retry_delay)

        logger.error(f"Failed to allocate server after {max_attempts} attempts")
        return None


# Global metaserver client instance
metaserver_client = MetaserverClient()
