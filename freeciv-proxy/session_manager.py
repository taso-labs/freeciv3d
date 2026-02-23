#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Session management for LLM agents in FreeCiv proxy
Provides secure session tracking, token expiration, and session validation

Supports two backends:
1. MySQLSessionManager - Persistent storage that survives proxy restarts
2. InMemorySessionManager - Fast in-memory storage (fallback)

The SessionManager wrapper tries MySQL first and falls back to in-memory.
"""

import asyncio
import time
import uuid
import hmac
import hashlib
import logging
import os
import secrets
import threading
from typing import Dict, Any, Optional, Set, Protocol
from dataclasses import dataclass, field
from enum import Enum
from contextlib import contextmanager
from datetime import datetime, timedelta

try:
    import bcrypt
except ImportError:
    bcrypt = None

try:
    import mysql.connector
    from mysql.connector import pooling
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

logger = logging.getLogger("freeciv-proxy")


class SessionState(Enum):
    """Session states"""
    ACTIVE = "active"
    EXPIRED = "expired"
    TERMINATED = "terminated"
    SUSPENDED = "suspended"


@dataclass
class SessionInfo:
    """Session information container"""
    session_id: str
    agent_id: str
    api_token_hash: str  # Hashed API token for verification
    created_at: float
    last_activity: float
    expires_at: float
    player_id: Optional[int] = None
    civserver_port: Optional[int] = None  # Port of the civserver game (for reconnection)
    game_id: Optional[str] = None  # Game ID for linking to game_allocations
    connection_count: int = 0
    state: SessionState = SessionState.ACTIVE
    resume_attempts: int = 0  # Track resume attempts for rate limiting
    last_resume_attempt: float = 0.0  # Timestamp of last resume attempt
    metadata: Dict[str, Any] = field(default_factory=dict)


class SessionManagerBackend(Protocol):
    """Protocol defining the session manager interface"""

    def create_session(self, agent_id: str, api_token: str, game_id: str = None) -> Optional[SessionInfo]:
        ...

    def validate_session(self, session_id: str, api_token: Optional[str] = None) -> Optional[SessionInfo]:
        ...

    def update_session_activity(self, session_id: str) -> bool:
        ...

    def extend_session(self, session_id: str, extension_seconds: int = None) -> bool:
        ...

    def terminate_session(self, session_id: str, reason: str = "manual") -> bool:
        ...

    def terminate_agent_session(self, agent_id: str, reason: str = "new_session") -> bool:
        ...

    def get_session_by_agent(self, agent_id: str) -> Optional[SessionInfo]:
        ...

    def suspend_session(self, session_id: str, reason: str = "admin") -> bool:
        ...

    def resume_session(self, session_id: str) -> bool:
        ...

    def try_resume_session_for_agent(self, agent_id: str, api_token: str, game_id: Optional[str] = None) -> Optional[SessionInfo]:
        ...

    def cleanup_expired_sessions(self) -> int:
        ...

    def get_active_session_count(self) -> int:
        ...

    def get_session_stats(self) -> Dict[str, Any]:
        ...


class TokenHasher:
    """Shared token hashing utilities"""

    @staticmethod
    def hash_token(token: str) -> str:
        """Hash API token for secure storage using bcrypt or fallback to PBKDF2"""
        if bcrypt:
            salt = bcrypt.gensalt(rounds=12)
            return bcrypt.hashpw(token.encode('utf-8'), salt).decode('utf-8')
        else:
            # Fallback to PBKDF2 with salt
            salt = secrets.token_bytes(32)
            key = hashlib.pbkdf2_hmac('sha256', token.encode('utf-8'), salt, 100000)
            return salt.hex() + ':' + key.hex()

    @staticmethod
    def verify_token(token: str, stored_hash: str) -> bool:
        """Verify token against stored hash using constant-time comparison"""
        try:
            if bcrypt:
                return bcrypt.checkpw(token.encode('utf-8'), stored_hash.encode('utf-8'))

            if ':' not in stored_hash:
                logger.warning("Legacy hash format detected - rejecting for security")
                return False

            salt_hex, key_hex = stored_hash.split(':', 1)
            salt = bytes.fromhex(salt_hex)
            stored_key = bytes.fromhex(key_hex)
            new_key = hashlib.pbkdf2_hmac('sha256', token.encode('utf-8'), salt, 100000)
            return hmac.compare_digest(stored_key, new_key)
        except Exception as e:
            logger.error(f"Token verification error: {e}")
            return False


class MySQLSessionManager:
    """
    MySQL-backed session manager for full persistence across proxy restarts.

    Sessions are stored in the agent_sessions table and survive process restarts.
    Cleanup is handled by periodic calls to cleanup_expired_sessions() from the
    application layer (via PeriodicCallback or during message handling).
    """

    def __init__(self,
                 db_config: Dict[str, Any],
                 session_timeout: int = 3600,
                 max_concurrent_sessions: int = 100,
                 cleanup_interval: int = 300):
        self.session_timeout = session_timeout
        self.max_concurrent_sessions = max_concurrent_sessions
        self.cleanup_interval = cleanup_interval
        self.db_config = db_config
        self._pool = None
        self._pool_lock = threading.Lock()
        self.last_cleanup = 0.0  # Timestamp of last cleanup run

        # Session security
        self.session_secret = self._get_secure_session_secret()

        # Statistics (in-memory, not persisted)
        self.stats = {
            'sessions_created': 0,
            'sessions_expired': 0,
            'sessions_terminated': 0,
            'authentication_attempts': 0,
            'authentication_failures': 0,
            'db_errors': 0
        }

        # Initialize connection pool
        self._init_pool()

    def _init_pool(self):
        """Initialize MySQL connection pool"""
        try:
            self._pool = pooling.MySQLConnectionPool(
                pool_name="session_pool",
                pool_size=int(os.getenv('DB_POOL_SIZE', '20')),
                pool_reset_session=True,
                **self.db_config
            )
            logger.info("MySQLSessionManager: Connection pool initialized")
        except Exception as e:
            logger.error(f"MySQLSessionManager: Failed to initialize pool: {e}")
            self._pool = None

    @contextmanager
    def _get_connection(self):
        """Get a connection from the pool with automatic cleanup"""
        conn = None
        try:
            if self._pool is None:
                with self._pool_lock:
                    if self._pool is None:
                        self._init_pool()

            if self._pool is None:
                raise RuntimeError("MySQL connection pool not available")

            conn = self._pool.get_connection()
            yield conn
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def is_available(self) -> bool:
        """Check if MySQL backend is available"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                    return True
        except Exception as e:
            logger.debug(f"MySQLSessionManager: Availability check failed: {e}")
            return False

    def create_session(self, agent_id: str, api_token: str, game_id: str = None) -> Optional[SessionInfo]:
        """Create a new session in MySQL"""
        try:
            with self._get_connection() as conn:
                with conn.cursor(dictionary=True) as cursor:
                    # Check session limits
                    cursor.execute(
                        "SELECT COUNT(*) as count FROM agent_sessions WHERE state = 'active'"
                    )
                    row = cursor.fetchone()
                    if row and row['count'] >= self.max_concurrent_sessions:
                        logger.warning(f"Maximum concurrent sessions reached: {self.max_concurrent_sessions}")
                        return None

                    # Terminate existing session for this agent
                    cursor.execute(
                        "UPDATE agent_sessions SET state = 'terminated' WHERE agent_id = %s AND state IN ('active', 'suspended')",
                        (agent_id,)
                    )

                    # Generate session ID and hash token
                    session_id = self._generate_session_id(agent_id)
                    api_token_hash = TokenHasher.hash_token(api_token)

                    now = datetime.now()
                    expires_at = now + timedelta(seconds=self.session_timeout)

                    # Insert new session
                    cursor.execute("""
                        INSERT INTO agent_sessions
                        (session_id, agent_id, game_id, api_token_hash, expires_at, state, connection_count, resume_attempts)
                        VALUES (%s, %s, %s, %s, %s, 'active', 0, 0)
                    """, (session_id, agent_id, game_id, api_token_hash, expires_at))

                    conn.commit()

                self.stats['sessions_created'] += 1
                logger.info(f"MySQLSessionManager: Created session for agent {agent_id}: {session_id}")

                return SessionInfo(
                    session_id=session_id,
                    agent_id=agent_id,
                    api_token_hash=api_token_hash,
                    created_at=now.timestamp(),
                    last_activity=now.timestamp(),
                    expires_at=expires_at.timestamp(),
                    game_id=game_id,
                    state=SessionState.ACTIVE
                )

        except Exception as e:
            logger.error(f"MySQLSessionManager: Failed to create session: {e}")
            self.stats['db_errors'] += 1
            return None

    def validate_session(self, session_id: str, api_token: Optional[str] = None) -> Optional[SessionInfo]:
        """Validate an existing session"""
        self.stats['authentication_attempts'] += 1

        try:
            with self._get_connection() as conn:
                with conn.cursor(dictionary=True) as cursor:
                    cursor.execute("""
                        SELECT * FROM agent_sessions WHERE session_id = %s
                    """, (session_id,))
                    row = cursor.fetchone()

                    if not row:
                        self.stats['authentication_failures'] += 1
                        return None

                    # Check state
                    if row['state'] != 'active':
                        logger.warning(f"Session {session_id} is not active: {row['state']}")
                        self.stats['authentication_failures'] += 1
                        return None

                    # Check expiration
                    if datetime.now() > row['expires_at']:
                        logger.info(f"Session {session_id} expired")
                        cursor.execute(
                            "UPDATE agent_sessions SET state = 'expired' WHERE session_id = %s",
                            (session_id,)
                        )
                        conn.commit()
                        self.stats['sessions_expired'] += 1
                        self.stats['authentication_failures'] += 1
                        return None

                    # Verify API token if provided
                    if api_token:
                        if not TokenHasher.verify_token(api_token, row['api_token_hash']):
                            logger.warning(f"Invalid API token for session {session_id}")
                            self.stats['authentication_failures'] += 1
                            return None

                    # Update last activity (handled by ON UPDATE CURRENT_TIMESTAMP)
                    cursor.execute(
                        "UPDATE agent_sessions SET last_activity = NOW() WHERE session_id = %s",
                        (session_id,)
                    )
                    conn.commit()

                    return self._row_to_session_info(row)

        except Exception as e:
            logger.error(f"MySQLSessionManager: Error validating session: {e}")
            self.stats['authentication_failures'] += 1
            self.stats['db_errors'] += 1
            return None

    def update_session_activity(self, session_id: str) -> bool:
        """Update session last activity timestamp"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE agent_sessions
                        SET last_activity = NOW()
                        WHERE session_id = %s AND state = 'active'
                    """, (session_id,))
                    affected = cursor.rowcount
                    conn.commit()
                    return affected > 0
        except Exception as e:
            logger.error(f"MySQLSessionManager: Error updating activity: {e}")
            self.stats['db_errors'] += 1
            return False

    def extend_session(self, session_id: str, extension_seconds: int = None) -> bool:
        """Extend session expiration time"""
        extension = extension_seconds or self.session_timeout
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE agent_sessions
                        SET expires_at = GREATEST(expires_at, NOW()) + INTERVAL %s SECOND
                        WHERE session_id = %s AND state = 'active'
                    """, (extension, session_id))
                    affected = cursor.rowcount
                    conn.commit()
                    logger.debug(f"Extended session {session_id} by {extension} seconds")
                    return affected > 0
        except Exception as e:
            logger.error(f"MySQLSessionManager: Error extending session: {e}")
            self.stats['db_errors'] += 1
            return False

    def terminate_session(self, session_id: str, reason: str = "manual") -> bool:
        """Terminate a specific session"""
        try:
            with self._get_connection() as conn:
                with conn.cursor(dictionary=True) as cursor:
                    # Get session info for logging
                    cursor.execute("SELECT agent_id FROM agent_sessions WHERE session_id = %s", (session_id,))
                    row = cursor.fetchone()

                    if not row:
                        return False

                    # Update state to terminated
                    cursor.execute(
                        "UPDATE agent_sessions SET state = 'terminated' WHERE session_id = %s",
                        (session_id,)
                    )
                    conn.commit()

                    self.stats['sessions_terminated'] += 1
                    logger.info(f"MySQLSessionManager: Terminated session {session_id} for agent {row['agent_id']}: {reason}")
                    return True

        except Exception as e:
            logger.error(f"MySQLSessionManager: Error terminating session: {e}")
            self.stats['db_errors'] += 1
            return False

    def terminate_agent_session(self, agent_id: str, reason: str = "new_session") -> bool:
        """Terminate all sessions for a specific agent"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE agent_sessions
                        SET state = 'terminated'
                        WHERE agent_id = %s AND state IN ('active', 'suspended')
                    """, (agent_id,))
                    affected = cursor.rowcount
                    conn.commit()

                    if affected > 0:
                        self.stats['sessions_terminated'] += affected
                        logger.info(f"MySQLSessionManager: Terminated {affected} session(s) for agent {agent_id}: {reason}")
                    return affected > 0

        except Exception as e:
            logger.error(f"MySQLSessionManager: Error terminating agent sessions: {e}")
            self.stats['db_errors'] += 1
            return False

    def get_session_by_agent(self, agent_id: str) -> Optional[SessionInfo]:
        """Get active session for an agent"""
        try:
            with self._get_connection() as conn:
                with conn.cursor(dictionary=True) as cursor:
                    cursor.execute("""
                        SELECT * FROM agent_sessions
                        WHERE agent_id = %s AND state IN ('active', 'suspended')
                        ORDER BY created_at DESC LIMIT 1
                    """, (agent_id,))
                    row = cursor.fetchone()

                    if row:
                        return self._row_to_session_info(row)
                    return None

        except Exception as e:
            logger.error(f"MySQLSessionManager: Error getting session by agent: {e}")
            self.stats['db_errors'] += 1
            return None

    def suspend_session(self, session_id: str, reason: str = "admin") -> bool:
        """Suspend a session temporarily"""
        suspension_timeout = int(os.getenv('SESSION_SUSPENSION_TIMEOUT_SECS', '86400'))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Accept both 'active' and 'suspended' to make suspend idempotent.
                    # When partner A pre-suspends B's session, B's own on_close() must
                    # also return True so CivCom is preserved (not destroyed).
                    cursor.execute("""
                        UPDATE agent_sessions
                        SET state = 'suspended', expires_at = NOW() + INTERVAL %s SECOND
                        WHERE session_id = %s AND state IN ('active', 'suspended')
                    """, (suspension_timeout, session_id))
                    affected = cursor.rowcount
                    conn.commit()

                    if affected > 0:
                        logger.info(f"MySQLSessionManager: Suspended session {session_id}: {reason} (expires in {suspension_timeout}s)")
                    return affected > 0

        except Exception as e:
            logger.error(f"MySQLSessionManager: Error suspending session: {e}")
            self.stats['db_errors'] += 1
            return False

    def resume_session(self, session_id: str) -> bool:
        """Resume a suspended session"""
        try:
            with self._get_connection() as conn:
                with conn.cursor(dictionary=True) as cursor:
                    # Check if session exists and is suspended
                    cursor.execute("""
                        SELECT * FROM agent_sessions
                        WHERE session_id = %s AND state = 'suspended'
                    """, (session_id,))
                    row = cursor.fetchone()

                    if not row:
                        return False

                    # Check expiration
                    if datetime.now() > row['expires_at']:
                        cursor.execute(
                            "UPDATE agent_sessions SET state = 'expired' WHERE session_id = %s",
                            (session_id,)
                        )
                        conn.commit()
                        logger.info(f"Cannot resume expired session {session_id}")
                        return False

                    # Resume the session
                    cursor.execute("""
                        UPDATE agent_sessions
                        SET state = 'active', last_activity = NOW()
                        WHERE session_id = %s
                    """, (session_id,))
                    conn.commit()

                    logger.info(f"MySQLSessionManager: Resumed session {session_id}")
                    return True

        except Exception as e:
            logger.error(f"MySQLSessionManager: Error resuming session: {e}")
            self.stats['db_errors'] += 1
            return False

    def try_resume_session_for_agent(self, agent_id: str, api_token: str, game_id: Optional[str] = None) -> Optional[SessionInfo]:
        """
        Atomically try to resume a suspended session for an agent.

        This is the key method for reconnection - finds a suspended session,
        verifies the token, and resumes it in a single atomic operation.

        Args:
            agent_id: The agent identifier
            api_token: The API token to verify
            game_id: Optional game_id to match. If provided, only resumes sessions
                     for the same game (prevents cross-game session resume bugs).
        """
        MAX_RESUME_ATTEMPTS = int(os.getenv('MAX_SESSION_RESUME_ATTEMPTS', '5'))

        try:
            with self._get_connection() as conn:
                with conn.cursor(dictionary=True) as cursor:
                    # Find suspended session for this agent
                    # If game_id is provided, also filter by game_id to prevent
                    # resuming sessions from a different game (E142 bug fix)
                    if game_id:
                        cursor.execute("""
                            SELECT * FROM agent_sessions
                            WHERE agent_id = %s AND game_id = %s AND state = 'suspended' AND expires_at > NOW()
                            ORDER BY created_at DESC LIMIT 1
                        """, (agent_id, game_id))
                    else:
                        cursor.execute("""
                            SELECT * FROM agent_sessions
                            WHERE agent_id = %s AND state = 'suspended' AND expires_at > NOW()
                            ORDER BY created_at DESC LIMIT 1
                        """, (agent_id,))
                    row = cursor.fetchone()

                    if not row:
                        return None

                    session_id = row['session_id']

                    # Increment resume attempts
                    new_attempts = row['resume_attempts'] + 1
                    cursor.execute(
                        "UPDATE agent_sessions SET resume_attempts = %s WHERE session_id = %s",
                        (new_attempts, session_id)
                    )

                    # Rate limiting check
                    if new_attempts > MAX_RESUME_ATTEMPTS:
                        logger.warning(
                            f"Rate limit exceeded for session {session_id}: "
                            f"{new_attempts} attempts (max {MAX_RESUME_ATTEMPTS})"
                        )
                        conn.commit()
                        self.stats['authentication_failures'] += 1
                        return None

                    # Verify token
                    if not TokenHasher.verify_token(api_token, row['api_token_hash']):
                        logger.warning(f"Token mismatch for session {session_id} - rejecting resume attempt ({new_attempts}/{MAX_RESUME_ATTEMPTS})")
                        conn.commit()
                        self.stats['authentication_failures'] += 1
                        return None

                    # All checks passed - resume the session
                    new_connection_count = row['connection_count'] + 1
                    cursor.execute("""
                        UPDATE agent_sessions
                        SET state = 'active',
                            last_activity = NOW(),
                            connection_count = %s,
                            resume_attempts = 0
                        WHERE session_id = %s
                    """, (new_connection_count, session_id))
                    conn.commit()

                    logger.info(f"MySQLSessionManager: Resumed session {session_id} for agent {agent_id} (connection #{new_connection_count})")

                    # Return updated session info
                    session = self._row_to_session_info(row)
                    session.state = SessionState.ACTIVE
                    session.connection_count = new_connection_count
                    session.resume_attempts = 0
                    return session

        except Exception as e:
            logger.error(f"MySQLSessionManager: Error resuming session for agent: {e}")
            self.stats['db_errors'] += 1
            return None

    def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired sessions with rate limiting.

        To avoid excessive database queries, this method only runs if at least
        cleanup_interval seconds have passed since the last cleanup.
        """
        import time
        now = time.time()

        # Rate limit cleanup to avoid excessive DB queries on high traffic
        if now - self.last_cleanup < self.cleanup_interval:
            return 0

        self.last_cleanup = now

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        DELETE FROM agent_sessions
                        WHERE expires_at < NOW() OR state IN ('expired', 'terminated')
                    """)
                    affected = cursor.rowcount
                    conn.commit()

                    if affected > 0:
                        logger.info(f"MySQLSessionManager: Cleaned up {affected} expired sessions")
                    return affected

        except Exception as e:
            logger.error(f"MySQLSessionManager: Error cleaning up sessions: {e}")
            self.stats['db_errors'] += 1
            return 0

    def get_active_session_count(self) -> int:
        """Get count of active sessions"""
        try:
            with self._get_connection() as conn:
                with conn.cursor(dictionary=True) as cursor:
                    cursor.execute("SELECT COUNT(*) as count FROM agent_sessions WHERE state = 'active'")
                    row = cursor.fetchone()
                    return row['count'] if row else 0
        except Exception as e:
            logger.error(f"MySQLSessionManager: Error getting session count: {e}")
            self.stats['db_errors'] += 1
            return 0

    def get_session_stats(self) -> Dict[str, Any]:
        """Get session management statistics"""
        # Optimized: Single query instead of N+1 pattern (was: 2 separate queries)
        # Also provides atomic snapshot of both counts
        active_count = 0
        total_count = 0
        try:
            with self._get_connection() as conn:
                with conn.cursor(dictionary=True) as cursor:
                    cursor.execute("""
                        SELECT
                            SUM(CASE WHEN state = 'active' THEN 1 ELSE 0 END) as active_count,
                            COUNT(*) as total_count
                        FROM agent_sessions
                    """)
                    row = cursor.fetchone()
                    active_count = int(row['active_count'] or 0)
                    total_count = int(row['total_count'] or 0)
        except Exception:
            pass

        return {
            **self.stats,
            'active_sessions': active_count,
            'total_sessions': total_count,
            'session_timeout': self.session_timeout,
            'max_concurrent_sessions': self.max_concurrent_sessions,
            'backend': 'mysql'
        }

    def _row_to_session_info(self, row: Dict[str, Any]) -> SessionInfo:
        """Convert a database row to SessionInfo"""
        created_at = row['created_at']
        last_activity = row['last_activity']
        expires_at = row['expires_at']

        # Convert datetime to timestamp if needed
        if isinstance(created_at, datetime):
            created_at = created_at.timestamp()
        if isinstance(last_activity, datetime):
            last_activity = last_activity.timestamp()
        if isinstance(expires_at, datetime):
            expires_at = expires_at.timestamp()

        return SessionInfo(
            session_id=row['session_id'],
            agent_id=row['agent_id'],
            api_token_hash=row['api_token_hash'],
            created_at=created_at,
            last_activity=last_activity,
            expires_at=expires_at,
            player_id=row.get('player_id'),
            civserver_port=row.get('civserver_port'),
            game_id=row.get('game_id'),
            connection_count=row.get('connection_count', 0),
            state=SessionState(row['state']),
            resume_attempts=row.get('resume_attempts', 0)
        )

    def _generate_session_id(self, agent_id: str) -> str:
        """Generate secure session ID"""
        data = f"{agent_id}:{time.time()}:{uuid.uuid4()}"
        session_id = hmac.new(
            self.session_secret.encode('utf-8'),
            data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return f"sess_{session_id[:32]}"

    def _get_secure_session_secret(self) -> str:
        """Get or generate secure session secret"""
        secret = os.getenv('SESSION_SECRET')

        if not secret:
            env = os.getenv('ENVIRONMENT', 'development').lower()
            if env == 'production':
                raise ValueError(
                    "SESSION_SECRET environment variable is required in production. "
                    "Generate with: python -c 'import secrets; print(secrets.token_urlsafe(64))'"
                )
            secret = secrets.token_urlsafe(64)
            logger.warning(
                "No SESSION_SECRET set. Generated random secret for development. "
                "Set SESSION_SECRET environment variable for production."
            )

        if len(secret) < 32:
            raise ValueError("SESSION_SECRET must be at least 32 characters long")

        return secret


class InMemorySessionManager:
    """
    In-memory session manager (original implementation).
    Used as fallback when MySQL is unavailable.
    """

    def __init__(self,
                 session_timeout: int = 3600,
                 max_concurrent_sessions: int = 100,
                 cleanup_interval: int = 300):
        self.session_timeout = session_timeout
        self.max_concurrent_sessions = max_concurrent_sessions
        self.cleanup_interval = cleanup_interval

        # Session storage
        self.sessions: Dict[str, SessionInfo] = {}
        self.agent_to_session: Dict[str, str] = {}

        # Session security
        self.session_secret = self._get_secure_session_secret()

        # Thread safety
        self._session_lock = threading.RLock()

        # Cleanup tracking
        self.last_cleanup = time.time()

        # Statistics
        self.stats = {
            'sessions_created': 0,
            'sessions_expired': 0,
            'sessions_terminated': 0,
            'authentication_attempts': 0,
            'authentication_failures': 0
        }

    def create_session(self, agent_id: str, api_token: str, game_id: str = None) -> Optional[SessionInfo]:
        """Create a new session for an agent"""
        with self._session_lock:
            try:
                if len(self.sessions) >= self.max_concurrent_sessions:
                    logger.warning(f"Maximum concurrent sessions reached: {self.max_concurrent_sessions}")
                    return None

                self.terminate_agent_session(agent_id)

                session_id = self._generate_session_id(agent_id)
                api_token_hash = TokenHasher.hash_token(api_token)

                now = time.time()
                session = SessionInfo(
                    session_id=session_id,
                    agent_id=agent_id,
                    api_token_hash=api_token_hash,
                    created_at=now,
                    last_activity=now,
                    expires_at=now + self.session_timeout,
                    game_id=game_id,
                    state=SessionState.ACTIVE
                )

                self.sessions[session_id] = session
                self.agent_to_session[agent_id] = session_id

                self.stats['sessions_created'] += 1
                logger.info(f"InMemorySessionManager: Created session for agent {agent_id}: {session_id}")

                return session

            except Exception as e:
                logger.error(f"Failed to create session for agent {agent_id}: {e}")
                return None

    def validate_session(self, session_id: str, api_token: Optional[str] = None) -> Optional[SessionInfo]:
        """Validate an existing session"""
        self.stats['authentication_attempts'] += 1

        try:
            session = self.sessions.get(session_id)
            if not session:
                self.stats['authentication_failures'] += 1
                return None

            if session.state != SessionState.ACTIVE:
                logger.warning(f"Session {session_id} is not active: {session.state}")
                self.stats['authentication_failures'] += 1
                return None

            now = time.time()
            if now > session.expires_at:
                logger.info(f"Session {session_id} expired")
                session.state = SessionState.EXPIRED
                self.stats['sessions_expired'] += 1
                self.stats['authentication_failures'] += 1
                return None

            if api_token:
                if not TokenHasher.verify_token(api_token, session.api_token_hash):
                    logger.warning(f"Invalid API token for session {session_id}")
                    self.stats['authentication_failures'] += 1
                    return None

            session.last_activity = now
            logger.debug(f"Validated session {session_id} for agent {session.agent_id}")
            return session

        except Exception as e:
            logger.error(f"Error validating session {session_id}: {e}")
            self.stats['authentication_failures'] += 1
            return None

    def update_session_activity(self, session_id: str) -> bool:
        """Update session last activity timestamp"""
        session = self.sessions.get(session_id)
        if session and session.state == SessionState.ACTIVE:
            session.last_activity = time.time()
            return True
        return False

    def extend_session(self, session_id: str, extension_seconds: int = None) -> bool:
        """Extend session expiration time"""
        session = self.sessions.get(session_id)
        if not session or session.state != SessionState.ACTIVE:
            return False

        extension = extension_seconds or self.session_timeout
        session.expires_at = max(session.expires_at, time.time()) + extension
        logger.debug(f"Extended session {session_id} by {extension} seconds")
        return True

    def terminate_session(self, session_id: str, reason: str = "manual") -> bool:
        """Terminate a specific session"""
        session = self.sessions.get(session_id)
        if not session:
            return False

        session.state = SessionState.TERMINATED

        if session.agent_id in self.agent_to_session:
            del self.agent_to_session[session.agent_id]

        del self.sessions[session_id]

        self.stats['sessions_terminated'] += 1
        logger.info(f"Terminated session {session_id} for agent {session.agent_id}: {reason}")

        return True

    def terminate_agent_session(self, agent_id: str, reason: str = "new_session") -> bool:
        """Terminate all sessions for a specific agent"""
        session_id = self.agent_to_session.get(agent_id)
        if session_id:
            return self.terminate_session(session_id, reason)
        return False

    def get_session_by_agent(self, agent_id: str) -> Optional[SessionInfo]:
        """Get active session for an agent"""
        session_id = self.agent_to_session.get(agent_id)
        if session_id:
            return self.sessions.get(session_id)
        return None

    def cleanup_expired_sessions(self) -> int:
        """Clean up expired and terminated sessions"""
        now = time.time()

        if now - self.last_cleanup < self.cleanup_interval:
            return 0

        self.last_cleanup = now

        sessions_to_remove = []
        for session_id, session in self.sessions.items():
            should_remove = False

            if session.state in [SessionState.EXPIRED, SessionState.TERMINATED]:
                should_remove = True
            elif now > session.expires_at:
                session.state = SessionState.EXPIRED
                self.stats['sessions_expired'] += 1
                should_remove = True

            if should_remove:
                sessions_to_remove.append(session_id)

        for session_id in sessions_to_remove:
            session = self.sessions[session_id]
            if session.agent_id in self.agent_to_session:
                del self.agent_to_session[session.agent_id]
            del self.sessions[session_id]

        if sessions_to_remove:
            logger.info(f"Cleaned up {len(sessions_to_remove)} expired sessions")

        return len(sessions_to_remove)

    def get_active_session_count(self) -> int:
        """Get count of active sessions"""
        return len([s for s in self.sessions.values() if s.state == SessionState.ACTIVE])

    def get_session_stats(self) -> Dict[str, Any]:
        """Get session management statistics"""
        active_sessions = self.get_active_session_count()

        return {
            **self.stats,
            'active_sessions': active_sessions,
            'total_sessions': len(self.sessions),
            'session_timeout': self.session_timeout,
            'max_concurrent_sessions': self.max_concurrent_sessions,
            'backend': 'in_memory'
        }

    def suspend_session(self, session_id: str, reason: str = "admin") -> bool:
        """Suspend a session temporarily"""
        with self._session_lock:
            session = self.sessions.get(session_id)
            # Accept both ACTIVE and SUSPENDED to make suspend idempotent.
            # When partner A pre-suspends B's session, B's own on_close() must
            # also return True so CivCom is preserved (not destroyed).
            if session and session.state in (SessionState.ACTIVE, SessionState.SUSPENDED):
                session.state = SessionState.SUSPENDED
                suspension_timeout = int(os.getenv('SESSION_SUSPENSION_TIMEOUT_SECS', '86400'))
                session.expires_at = time.time() + suspension_timeout
                logger.info(f"Suspended session {session_id}: {reason} (expires in {suspension_timeout}s)")
                return True
            return False

    def resume_session(self, session_id: str) -> bool:
        """Resume a suspended session"""
        with self._session_lock:
            session = self.sessions.get(session_id)
            if session and session.state == SessionState.SUSPENDED:
                if time.time() <= session.expires_at:
                    session.state = SessionState.ACTIVE
                    session.last_activity = time.time()
                    logger.info(f"Resumed session {session_id}")
                    return True
                else:
                    session.state = SessionState.EXPIRED
                    logger.info(f"Cannot resume expired session {session_id}")
            return False

    def try_resume_session_for_agent(self, agent_id: str, api_token: str, game_id: Optional[str] = None) -> Optional[SessionInfo]:
        """
        Atomically try to resume a suspended session for an agent.

        Args:
            agent_id: The agent identifier
            api_token: The API token to verify
            game_id: Optional game_id to match. If provided, only resumes sessions
                     for the same game (prevents cross-game session resume bugs).
        """
        MAX_RESUME_ATTEMPTS = int(os.getenv('MAX_SESSION_RESUME_ATTEMPTS', '5'))

        with self._session_lock:
            session_id = self.agent_to_session.get(agent_id)
            if not session_id:
                return None

            session = self.sessions.get(session_id)
            if not session:
                del self.agent_to_session[agent_id]
                return None

            # game_id validation: if provided, only resume if it matches the session's game_id
            # This prevents resuming a session from a different game (E142 bug fix)
            if game_id and session.game_id != game_id:
                logger.info(
                    f"Session resume skipped for {agent_id}: game_id mismatch "
                    f"(session={session.game_id}, requested={game_id})"
                )
                return None

            if session.state != SessionState.SUSPENDED:
                logger.debug(f"Session {session_id} for agent {agent_id} is {session.state}, not SUSPENDED")
                return None

            if time.time() > session.expires_at:
                session.state = SessionState.EXPIRED
                logger.info(f"Session {session_id} expired, cannot resume")
                return None

            session.resume_attempts += 1
            session.last_resume_attempt = time.time()
            if session.resume_attempts > MAX_RESUME_ATTEMPTS:
                logger.warning(
                    f"Rate limit exceeded for session {session_id}: "
                    f"{session.resume_attempts} attempts (max {MAX_RESUME_ATTEMPTS})"
                )
                self.stats['authentication_failures'] += 1
                return None

            if not TokenHasher.verify_token(api_token, session.api_token_hash):
                logger.warning(f"Token mismatch for session {session_id} - rejecting resume attempt ({session.resume_attempts}/{MAX_RESUME_ATTEMPTS})")
                self.stats['authentication_failures'] += 1
                return None

            session.state = SessionState.ACTIVE
            session.last_activity = time.time()
            session.connection_count += 1
            session.resume_attempts = 0

            logger.info(f"Resumed suspended session {session_id} for agent {agent_id} (connection #{session.connection_count})")
            return session

    def _generate_session_id(self, agent_id: str) -> str:
        """Generate secure session ID"""
        data = f"{agent_id}:{time.time()}:{uuid.uuid4()}"
        session_id = hmac.new(
            self.session_secret.encode('utf-8'),
            data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return f"sess_{session_id[:32]}"

    def _get_secure_session_secret(self) -> str:
        """Get or generate secure session secret"""
        secret = os.getenv('SESSION_SECRET')

        if not secret:
            env = os.getenv('ENVIRONMENT', 'development').lower()
            if env == 'production':
                raise ValueError(
                    "SESSION_SECRET environment variable is required in production. "
                    "Generate with: python -c 'import secrets; print(secrets.token_urlsafe(64))'"
                )
            secret = secrets.token_urlsafe(64)
            logger.warning(
                "No SESSION_SECRET set. Generated random secret for development. "
                "Set SESSION_SECRET environment variable for production."
            )

        if len(secret) < 32:
            raise ValueError("SESSION_SECRET must be at least 32 characters long")

        return secret


class SessionManager:
    """
    Wrapper session manager that tries MySQL first, falls back to in-memory.

    This provides the same API as the original SessionManager while adding
    persistence through MySQL. If MySQL is unavailable, it gracefully
    falls back to in-memory storage.
    """

    def __init__(self,
                 db_config: Optional[Dict[str, Any]] = None,
                 session_timeout: int = 3600,
                 max_concurrent_sessions: int = 100,
                 cleanup_interval: int = 300):

        self.session_timeout = session_timeout
        self.max_concurrent_sessions = max_concurrent_sessions

        # Initialize backends
        self._mysql_backend: Optional[MySQLSessionManager] = None
        self._memory_backend = InMemorySessionManager(
            session_timeout=session_timeout,
            max_concurrent_sessions=max_concurrent_sessions,
            cleanup_interval=cleanup_interval
        )

        # Try to initialize MySQL backend
        if db_config and MYSQL_AVAILABLE:
            try:
                self._mysql_backend = MySQLSessionManager(
                    db_config=db_config,
                    session_timeout=session_timeout,
                    max_concurrent_sessions=max_concurrent_sessions,
                    cleanup_interval=cleanup_interval
                )
                if self._mysql_backend.is_available():
                    logger.info("SessionManager: MySQL backend initialized successfully")
                else:
                    logger.warning("SessionManager: MySQL backend not available, using in-memory fallback")
                    self._mysql_backend = None
            except Exception as e:
                logger.warning(f"SessionManager: Failed to initialize MySQL backend: {e}, using in-memory fallback")
                self._mysql_backend = None
        elif not MYSQL_AVAILABLE:
            logger.info("SessionManager: mysql-connector-python not installed, using in-memory backend")
        else:
            logger.info("SessionManager: No database config provided, using in-memory backend")

    def _get_backend(self) -> SessionManagerBackend:
        """Get the active backend, preferring MySQL if available"""
        if self._mysql_backend and self._mysql_backend.is_available():
            return self._mysql_backend
        return self._memory_backend

    @property
    def backend_name(self) -> str:
        """Get the name of the active backend"""
        if self._mysql_backend and self._mysql_backend.is_available():
            return "mysql"
        return "in_memory"

    # Delegate all methods to the active backend

    def create_session(self, agent_id: str, api_token: str, game_id: str = None) -> Optional[SessionInfo]:
        return self._get_backend().create_session(agent_id, api_token, game_id)

    def validate_session(self, session_id: str, api_token: Optional[str] = None) -> Optional[SessionInfo]:
        return self._get_backend().validate_session(session_id, api_token)

    def update_session_activity(self, session_id: str) -> bool:
        return self._get_backend().update_session_activity(session_id)

    def extend_session(self, session_id: str, extension_seconds: int = None) -> bool:
        return self._get_backend().extend_session(session_id, extension_seconds)

    def terminate_session(self, session_id: str, reason: str = "manual") -> bool:
        return self._get_backend().terminate_session(session_id, reason)

    def terminate_agent_session(self, agent_id: str, reason: str = "new_session") -> bool:
        return self._get_backend().terminate_agent_session(agent_id, reason)

    def get_session_by_agent(self, agent_id: str) -> Optional[SessionInfo]:
        return self._get_backend().get_session_by_agent(agent_id)

    def suspend_session(self, session_id: str, reason: str = "admin") -> bool:
        return self._get_backend().suspend_session(session_id, reason)

    def resume_session(self, session_id: str) -> bool:
        return self._get_backend().resume_session(session_id)

    def try_resume_session_for_agent(self, agent_id: str, api_token: str, game_id: Optional[str] = None) -> Optional[SessionInfo]:
        return self._get_backend().try_resume_session_for_agent(agent_id, api_token, game_id)

    def cleanup_expired_sessions(self) -> int:
        return self._get_backend().cleanup_expired_sessions()

    def get_active_session_count(self) -> int:
        return self._get_backend().get_active_session_count()

    def get_session_stats(self) -> Dict[str, Any]:
        return self._get_backend().get_session_stats()


def get_db_config_from_env() -> Optional[Dict[str, Any]]:
    """
    Get database configuration from environment variables.
    Returns None if required variables are not set.
    """
    host = os.getenv('DB_HOST')
    user = os.getenv('DB_USER')
    password = os.getenv('DB_PASSWORD')
    database = os.getenv('DB_NAME', 'freeciv_web')

    if not all([host, user, password]):
        return None

    return {
        'host': host,
        'user': user,
        'password': password,
        'database': database,
        'charset': 'utf8mb4',
        'collation': 'utf8mb4_unicode_ci'
    }


# Global session manager instance
# Initializes with MySQL backend if DB_HOST/DB_USER/DB_PASSWORD are set
_db_config = get_db_config_from_env()
session_manager = SessionManager(
    db_config=_db_config,
    session_timeout=int(os.getenv('SESSION_TIMEOUT_SECONDS', '3600')),
    max_concurrent_sessions=int(os.getenv('MAX_CONCURRENT_SESSIONS', '100'))
)

# Periodic cleanup callback (lazy-initialized)
_cleanup_callback = None


def _sync_dead_markers(civcom_registry):
    """Propagate dead-connection timestamps from WS handlers to CivCom instances.

    CivCom threads don't directly know when the WS handler's connection died.
    This syncs the `_connection_dead_since` timestamp from the handler to the
    CivCom's `_dead_since` attribute, enabling TTL-based cleanup.
    """
    for key, civcom in civcom_registry.get_all_instances():
        # Skip if already marked
        if getattr(civcom, '_dead_since', None) is not None:
            continue

        handler = getattr(civcom, 'civwebserver', None)
        if handler is None:
            # Handler detached — mark as dead now
            civcom._dead_since = time.time()
        elif getattr(handler, '_connection_dead', False):
            # Handler's connection is dead — propagate the timestamp
            civcom._dead_since = getattr(handler, '_connection_dead_since', None) or time.time()


def start_periodic_cleanup(interval_ms: int = 300000) -> None:
    """
    Start a periodic cleanup callback using Tornado's PeriodicCallback.

    This should be called once during application startup (after IOLoop is available)
    to ensure expired sessions are cleaned up at regular intervals, regardless of
    traffic patterns.

    Args:
        interval_ms: Cleanup interval in milliseconds (default: 5 minutes)

    Example:
        from session_manager import start_periodic_cleanup
        # Call after Tornado IOLoop is initialized
        start_periodic_cleanup()
    """
    global _cleanup_callback

    if _cleanup_callback is not None:
        logger.warning("Periodic cleanup already started, ignoring duplicate call")
        return

    try:
        from tornado.ioloop import PeriodicCallback

        def do_cleanup():
            try:
                cleaned = session_manager.cleanup_expired_sessions()
                if cleaned > 0:
                    logger.debug(f"Periodic cleanup removed {cleaned} expired sessions")
            except Exception as e:
                logger.error(f"Periodic cleanup error: {e}")

            # Paused game-session cleanup — release ports that exceeded reconnect window.
            try:
                from game_session_manager import game_session_manager
                from tornado.ioloop import IOLoop

                async def _cleanup_stale_paused_sessions():
                    try:
                        cleaned_paused = await game_session_manager.cleanup_stale_paused_sessions()
                        if cleaned_paused > 0:
                            logger.info(
                                f"Periodic cleanup released {cleaned_paused} stale paused game session(s)"
                            )
                    except Exception as e:
                        logger.error(f"Stale paused-session cleanup failed: {e}")

                IOLoop.current().add_callback(
                    lambda: asyncio.ensure_future(_cleanup_stale_paused_sessions())
                )
            except Exception as e:
                logger.error(f"Stale paused-session cleanup scheduling error: {e}")

            # Dead CivCom cleanup — gentle TTL (24h default, configurable)
            # Gives agent-clash plenty of time to reconnect before cleaning up
            try:
                from state_extractor import civcom_registry
                _sync_dead_markers(civcom_registry)
                max_age = int(os.getenv('SESSION_SUSPENSION_TIMEOUT_SECS', '86400'))
                civcom_cleaned = civcom_registry.cleanup_dead_civcoms(max_age)
                if civcom_cleaned > 0:
                    logger.info(f"Periodic cleanup removed {civcom_cleaned} dead CivCom(s)")
            except Exception as e:
                logger.error(f"Dead CivCom cleanup error: {e}")

        _cleanup_callback = PeriodicCallback(do_cleanup, interval_ms)
        _cleanup_callback.start()
        logger.info(f"Started periodic session cleanup (interval: {interval_ms}ms)")
    except ImportError:
        logger.warning("Tornado not available, periodic cleanup disabled")
