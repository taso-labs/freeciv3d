#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Secure Token Manager for LLM API Gateway
Handles encrypted storage and validation of API tokens
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

logger = logging.getLogger("llm-gateway")


@dataclass
class TokenInfo:
    """Information about a stored token"""
    agent_id: str
    encrypted_token: bytes
    created_at: float
    last_used: float
    usage_count: int = 0
    is_active: bool = True


class SecureTokenManager:
    """
    Secure token storage and validation manager
    Encrypts tokens in memory and provides secure validation
    """

    def __init__(self, master_key: Optional[bytes] = None, token_ttl: float = 86400.0):
        """
        Initialize the secure token manager

        Args:
            master_key: Master encryption key (generated if None)
            token_ttl: Token time-to-live in seconds (24 hours default)
        """
        self.token_ttl = token_ttl
        self._lock = asyncio.Lock()

        # Initialize encryption
        if master_key:
            self._cipher = Fernet(master_key)
        else:
            self._cipher = Fernet(Fernet.generate_key())

        # Token storage
        self._token_storage: Dict[str, TokenInfo] = {}
        self._token_hashes: Dict[str, str] = {}  # agent_id -> token_hash

        # Validation settings
        self.max_validation_attempts = 5
        self.validation_window = 300.0  # 5 minutes
        self._validation_attempts: Dict[str, List[float]] = {}

        # Background cleanup
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

        # Statistics
        self._stats = {
            "tokens_stored": 0,
            "validation_attempts": 0,
            "validation_successes": 0,
            "validation_failures": 0,
            "expired_tokens": 0
        }

    async def start(self):
        """Start the token manager"""
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("SecureTokenManager started")

    async def stop(self):
        """Stop the token manager"""
        self._running = False

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Clear all tokens
        async with self._lock:
            self._token_storage.clear()
            self._token_hashes.clear()
            self._validation_attempts.clear()

        logger.info("SecureTokenManager stopped")

    async def store_token(self, agent_id: str, token: str) -> bool:
        """
        Store an encrypted token for an agent

        Args:
            agent_id: Agent identifier
            token: Plain text API token

        Returns:
            bool: True if stored successfully
        """
        if not token or not agent_id:
            return False

        try:
            async with self._lock:
                # Encrypt the token
                encrypted_token = self._cipher.encrypt(token.encode('utf-8'))

                # Create token hash for validation
                token_hash = self._create_token_hash(token)

                # Store token info
                token_info = TokenInfo(
                    agent_id=agent_id,
                    encrypted_token=encrypted_token,
                    created_at=time.time(),
                    last_used=time.time()
                )

                self._token_storage[agent_id] = token_info
                self._token_hashes[agent_id] = token_hash
                self._stats["tokens_stored"] += 1

                logger.debug(f"Stored encrypted token for agent {agent_id}")
                return True

        except Exception as e:
            logger.error(f"Error storing token for agent {agent_id}: {e}")
            return False

    async def get_token(self, agent_id: str) -> Optional[str]:
        """
        Retrieve and decrypt a token for an agent

        Args:
            agent_id: Agent identifier

        Returns:
            Decrypted token or None if not found/expired
        """
        try:
            async with self._lock:
                token_info = self._token_storage.get(agent_id)

                if not token_info:
                    return None

                if not token_info.is_active:
                    return None

                # Check if token has expired
                if time.time() - token_info.created_at > self.token_ttl:
                    await self._expire_token_unsafe(agent_id)
                    return None

                # Update usage
                token_info.last_used = time.time()
                token_info.usage_count += 1

                # Decrypt and return token
                decrypted_token = self._cipher.decrypt(token_info.encrypted_token)
                return decrypted_token.decode('utf-8')

        except Exception as e:
            logger.error(f"Error retrieving token for agent {agent_id}: {e}")
            return None

    async def validate_token(self, agent_id: str, token: str) -> bool:
        """
        Validate a token against stored encrypted token

        Args:
            agent_id: Agent identifier
            token: Token to validate

        Returns:
            bool: True if token is valid
        """
        self._stats["validation_attempts"] += 1

        # Check rate limiting
        if not await self._check_validation_rate_limit(agent_id):
            logger.warning(f"Validation rate limit exceeded for agent {agent_id}")
            return False

        try:
            async with self._lock:
                token_info = self._token_storage.get(agent_id)

                if not token_info or not token_info.is_active:
                    self._stats["validation_failures"] += 1
                    return False

                # Check if token has expired
                if time.time() - token_info.created_at > self.token_ttl:
                    await self._expire_token_unsafe(agent_id)
                    self._stats["validation_failures"] += 1
                    return False

                # Validate using hash comparison (timing-safe)
                stored_hash = self._token_hashes.get(agent_id)
                if not stored_hash:
                    self._stats["validation_failures"] += 1
                    return False

                provided_hash = self._create_token_hash(token)
                is_valid = hmac.compare_digest(stored_hash, provided_hash)

                if is_valid:
                    token_info.last_used = time.time()
                    token_info.usage_count += 1
                    self._stats["validation_successes"] += 1
                    logger.debug(f"Token validation successful for agent {agent_id}")
                else:
                    self._stats["validation_failures"] += 1
                    logger.warning(f"Token validation failed for agent {agent_id}")

                return is_valid

        except Exception as e:
            logger.error(f"Error validating token for agent {agent_id}: {e}")
            self._stats["validation_failures"] += 1
            return False

    async def validate_request_signature(
        self,
        agent_id: str,
        request_data: Dict[str, Any],
        provided_signature: str
    ) -> bool:
        """
        Validate HMAC signature of request data

        Args:
            agent_id: Agent identifier
            request_data: Request data to validate
            provided_signature: HMAC signature to check

        Returns:
            bool: True if signature is valid
        """
        try:
            # Get the stored token for HMAC key
            token = await self.get_token(agent_id)
            if not token:
                return False

            # Create canonical representation of request data
            canonical_data = json.dumps(request_data, sort_keys=True, separators=(',', ':'))

            # Calculate expected signature
            expected_signature = hmac.new(
                token.encode('utf-8'),
                canonical_data.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            # Timing-safe comparison
            return hmac.compare_digest(expected_signature, provided_signature)

        except Exception as e:
            logger.error(f"Error validating request signature for agent {agent_id}: {e}")
            return False

    async def revoke_token(self, agent_id: str) -> bool:
        """
        Revoke a token for an agent

        Args:
            agent_id: Agent identifier

        Returns:
            bool: True if token was revoked
        """
        try:
            async with self._lock:
                token_info = self._token_storage.get(agent_id)

                if token_info:
                    token_info.is_active = False
                    logger.info(f"Revoked token for agent {agent_id}")
                    return True

                return False

        except Exception as e:
            logger.error(f"Error revoking token for agent {agent_id}: {e}")
            return False

    async def rotate_token(self, agent_id: str, new_token: str) -> bool:
        """
        Rotate a token for an agent

        Args:
            agent_id: Agent identifier
            new_token: New token to store

        Returns:
            bool: True if rotation was successful
        """
        try:
            # Revoke old token and store new one
            await self.revoke_token(agent_id)
            return await self.store_token(agent_id, new_token)

        except Exception as e:
            logger.error(f"Error rotating token for agent {agent_id}: {e}")
            return False

    async def get_token_info(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Get token information (without the actual token)

        Args:
            agent_id: Agent identifier

        Returns:
            Token information or None
        """
        try:
            async with self._lock:
                token_info = self._token_storage.get(agent_id)

                if not token_info:
                    return None

                return {
                    "agent_id": token_info.agent_id,
                    "created_at": token_info.created_at,
                    "last_used": token_info.last_used,
                    "usage_count": token_info.usage_count,
                    "is_active": token_info.is_active,
                    "expires_at": token_info.created_at + self.token_ttl,
                    "is_expired": time.time() - token_info.created_at > self.token_ttl
                }

        except Exception as e:
            logger.error(f"Error getting token info for agent {agent_id}: {e}")
            return None

    async def list_active_tokens(self) -> List[str]:
        """
        List all active token agent IDs

        Returns:
            List of agent IDs with active tokens
        """
        try:
            async with self._lock:
                active_agents = []
                current_time = time.time()

                for agent_id, token_info in self._token_storage.items():
                    if (token_info.is_active and
                        current_time - token_info.created_at <= self.token_ttl):
                        active_agents.append(agent_id)

                return active_agents

        except Exception as e:
            logger.error(f"Error listing active tokens: {e}")
            return []

    async def get_stats(self) -> Dict[str, Any]:
        """Get token manager statistics"""
        async with self._lock:
            active_tokens = sum(
                1 for info in self._token_storage.values()
                if info.is_active and time.time() - info.created_at <= self.token_ttl
            )

            return {
                **self._stats,
                "active_tokens": active_tokens,
                "total_stored_tokens": len(self._token_storage),
                "token_ttl": self.token_ttl,
                "max_validation_attempts": self.max_validation_attempts
            }

    # Internal methods

    def _create_token_hash(self, token: str) -> str:
        """Create a secure hash of the token"""
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    async def _check_validation_rate_limit(self, agent_id: str) -> bool:
        """Check if agent is within validation rate limits"""
        current_time = time.time()
        window_start = current_time - self.validation_window

        # Clean old attempts
        if agent_id in self._validation_attempts:
            self._validation_attempts[agent_id] = [
                timestamp for timestamp in self._validation_attempts[agent_id]
                if timestamp > window_start
            ]
        else:
            self._validation_attempts[agent_id] = []

        # Check limit
        if len(self._validation_attempts[agent_id]) >= self.max_validation_attempts:
            return False

        # Record this attempt
        self._validation_attempts[agent_id].append(current_time)
        return True

    async def _expire_token_unsafe(self, agent_id: str):
        """Mark token as expired (unsafe - requires lock)"""
        token_info = self._token_storage.get(agent_id)
        if token_info:
            token_info.is_active = False
            self._stats["expired_tokens"] += 1
            logger.debug(f"Expired token for agent {agent_id}")

    async def _cleanup_loop(self):
        """Background task to clean up expired tokens"""
        while self._running:
            try:
                await asyncio.sleep(3600)  # Run every hour
                await self._cleanup_expired_tokens()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in token cleanup loop: {e}")

    async def _cleanup_expired_tokens(self):
        """Clean up expired tokens"""
        current_time = time.time()
        expired_agents = []

        async with self._lock:
            for agent_id, token_info in list(self._token_storage.items()):
                if current_time - token_info.created_at > self.token_ttl:
                    expired_agents.append(agent_id)

            # Remove expired tokens
            for agent_id in expired_agents:
                del self._token_storage[agent_id]
                if agent_id in self._token_hashes:
                    del self._token_hashes[agent_id]

        if expired_agents:
            logger.info(f"Cleaned up {len(expired_agents)} expired tokens")


def generate_secure_key() -> bytes:
    """Generate a secure key for token encryption"""
    return Fernet.generate_key()


def derive_key_from_password(password: str, salt: Optional[bytes] = None) -> tuple[bytes, bytes]:
    """
    Derive encryption key from password

    Args:
        password: Password to derive key from
        salt: Optional salt (generated if None)

    Returns:
        tuple: (key, salt)
    """
    if salt is None:
        salt = os.urandom(16)

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )

    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key, salt


# Global instance
secure_token_manager = SecureTokenManager()