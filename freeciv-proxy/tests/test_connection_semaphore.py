#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for the per-port connection semaphore that limits concurrent observer handshakes.

The semaphore prevents overwhelming civserver when many observers connect simultaneously.
It queues connection handshakes so only MAX_CONCURRENT_HANDSHAKES can be in progress
per civserver port at any time.
"""

import importlib.util
import os
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import freeciv-proxy.py using importlib (file has hyphen in name)
spec = importlib.util.spec_from_file_location(
    "freeciv_proxy",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "freeciv-proxy.py")
)
freeciv_proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(freeciv_proxy)

# Import the functions/variables to test
get_port_semaphore = freeciv_proxy.get_port_semaphore
cleanup_port_semaphore = freeciv_proxy.cleanup_port_semaphore
MAX_CONCURRENT_HANDSHAKES = freeciv_proxy.MAX_CONCURRENT_HANDSHAKES
_port_semaphores = freeciv_proxy._port_semaphores
_semaphore_lock = freeciv_proxy._semaphore_lock


class TestGetPortSemaphore(unittest.TestCase):
    """Test get_port_semaphore() function"""

    def setUp(self):
        """Clear semaphores before each test"""
        with _semaphore_lock:
            _port_semaphores.clear()

    def tearDown(self):
        """Clean up semaphores after each test"""
        with _semaphore_lock:
            _port_semaphores.clear()

    def test_creates_new_semaphore_for_new_port(self):
        """Test that a new semaphore is created for a port not seen before"""
        port = 6001
        self.assertNotIn(port, _port_semaphores)

        semaphore = get_port_semaphore(port)

        self.assertIsInstance(semaphore, threading.Semaphore)
        self.assertIn(port, _port_semaphores)
        self.assertIs(_port_semaphores[port], semaphore)

    def test_returns_existing_semaphore_for_same_port(self):
        """Test that the same semaphore is returned for the same port"""
        port = 6002
        semaphore1 = get_port_semaphore(port)
        semaphore2 = get_port_semaphore(port)

        self.assertIs(semaphore1, semaphore2)

    def test_different_ports_get_different_semaphores(self):
        """Test that different ports get different semaphores"""
        semaphore1 = get_port_semaphore(6001)
        semaphore2 = get_port_semaphore(6002)

        self.assertIsNot(semaphore1, semaphore2)

    def test_semaphore_has_correct_initial_count(self):
        """Test that the semaphore starts with MAX_CONCURRENT_HANDSHAKES permits"""
        port = 6003
        semaphore = get_port_semaphore(port)

        # Acquire all permits - should succeed
        acquired = []
        for i in range(MAX_CONCURRENT_HANDSHAKES):
            result = semaphore.acquire(blocking=False)
            acquired.append(result)
            self.assertTrue(result, f"Failed to acquire permit {i+1}")

        # Next acquire should fail (non-blocking)
        result = semaphore.acquire(blocking=False)
        self.assertFalse(result, "Should not be able to acquire more than MAX_CONCURRENT_HANDSHAKES")

        # Release all
        for _ in acquired:
            semaphore.release()

    def test_thread_safety_of_creation(self):
        """Test that concurrent calls to get_port_semaphore are thread-safe"""
        port = 6004
        results = []
        errors = []

        def get_semaphore():
            try:
                sem = get_port_semaphore(port)
                results.append(sem)
            except Exception as e:
                errors.append(e)

        # Create multiple threads trying to get the same port's semaphore
        threads = [threading.Thread(target=get_semaphore) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")
        self.assertEqual(len(results), 10)
        # All threads should have gotten the same semaphore
        self.assertTrue(all(s is results[0] for s in results))


class TestCleanupPortSemaphore(unittest.TestCase):
    """Test cleanup_port_semaphore() function"""

    def setUp(self):
        """Clear semaphores before each test"""
        with _semaphore_lock:
            _port_semaphores.clear()

    def tearDown(self):
        """Clean up semaphores after each test"""
        with _semaphore_lock:
            _port_semaphores.clear()

    def test_removes_existing_semaphore(self):
        """Test that cleanup removes an existing semaphore"""
        port = 6005
        get_port_semaphore(port)
        self.assertIn(port, _port_semaphores)

        cleanup_port_semaphore(port)

        self.assertNotIn(port, _port_semaphores)

    def test_cleanup_nonexistent_port_is_safe(self):
        """Test that cleaning up a non-existent port doesn't raise an error"""
        port = 9999
        self.assertNotIn(port, _port_semaphores)

        # Should not raise
        cleanup_port_semaphore(port)

        self.assertNotIn(port, _port_semaphores)

    def test_cleanup_allows_new_semaphore_creation(self):
        """Test that after cleanup, a new semaphore can be created for the same port"""
        port = 6006
        semaphore1 = get_port_semaphore(port)

        cleanup_port_semaphore(port)

        semaphore2 = get_port_semaphore(port)
        self.assertIsNot(semaphore1, semaphore2)


class TestSemaphoreBlocking(unittest.TestCase):
    """Test that the semaphore correctly blocks when at capacity"""

    def setUp(self):
        """Clear semaphores before each test"""
        with _semaphore_lock:
            _port_semaphores.clear()

    def tearDown(self):
        """Clean up semaphores after each test"""
        with _semaphore_lock:
            _port_semaphores.clear()

    def test_blocks_when_at_capacity(self):
        """Test that acquisition blocks when semaphore is at capacity"""
        port = 6007
        semaphore = get_port_semaphore(port)

        # Acquire all available permits
        for _ in range(MAX_CONCURRENT_HANDSHAKES):
            self.assertTrue(semaphore.acquire(blocking=False))

        # Now try to acquire with timeout - should fail
        start = time.time()
        result = semaphore.acquire(blocking=True, timeout=0.1)
        elapsed = time.time() - start

        self.assertFalse(result)
        self.assertGreaterEqual(elapsed, 0.09)  # Should have waited ~0.1s

        # Clean up
        for _ in range(MAX_CONCURRENT_HANDSHAKES):
            semaphore.release()

    def test_unblocks_when_released(self):
        """Test that blocked acquisition proceeds when semaphore is released"""
        port = 6008
        semaphore = get_port_semaphore(port)
        acquired_event = threading.Event()
        unblocked = [False]

        # Acquire all available permits
        for _ in range(MAX_CONCURRENT_HANDSHAKES):
            semaphore.acquire(blocking=False)

        def waiting_thread():
            # This will block until a permit is released
            semaphore.acquire(blocking=True)
            unblocked[0] = True
            acquired_event.set()
            semaphore.release()

        t = threading.Thread(target=waiting_thread)
        t.start()

        # Give thread time to start and block
        time.sleep(0.05)
        self.assertFalse(unblocked[0], "Thread should be blocked")

        # Release one permit
        semaphore.release()

        # Wait for thread to acquire
        acquired_event.wait(timeout=1.0)
        t.join(timeout=1.0)

        self.assertTrue(unblocked[0], "Thread should have been unblocked")

        # Clean up remaining permits
        for _ in range(MAX_CONCURRENT_HANDSHAKES - 1):
            semaphore.release()


class TestCivComSemaphoreRelease(unittest.TestCase):
    """Test CivCom._release_handshake_semaphore() method"""

    def setUp(self):
        """Clear semaphores before each test"""
        with _semaphore_lock:
            _port_semaphores.clear()

    def tearDown(self):
        """Clean up semaphores after each test"""
        with _semaphore_lock:
            _port_semaphores.clear()

    def test_release_is_idempotent(self):
        """Test that calling _release_handshake_semaphore multiple times is safe"""
        from civcom import CivCom

        port = 6009
        semaphore = get_port_semaphore(port)

        # Create a mock civcom with the semaphore
        mock_civwebserver = Mock()
        mock_civwebserver.loginpacket = '{"username":"test","port":6009}'

        civcom = CivCom("test_user", port, "test_key", mock_civwebserver)
        civcom.port_semaphore = semaphore

        # Acquire the semaphore (simulating what get_civcom does)
        semaphore.acquire(blocking=False)

        # First release should work
        civcom._release_handshake_semaphore()
        self.assertIsNone(civcom.port_semaphore)
        self.assertTrue(civcom.handshake_complete.is_set())

        # Second release should not raise
        civcom._release_handshake_semaphore()  # Should be a no-op

    def test_release_with_no_semaphore_is_safe(self):
        """Test that release with no semaphore assigned doesn't raise"""
        from civcom import CivCom

        mock_civwebserver = Mock()
        mock_civwebserver.loginpacket = '{"username":"test","port":6010}'

        civcom = CivCom("test_user", 6010, "test_key", mock_civwebserver)
        # port_semaphore is None by default

        # Should not raise
        civcom._release_handshake_semaphore()

    def test_release_sets_handshake_complete_event(self):
        """Test that release sets the handshake_complete event"""
        from civcom import CivCom

        port = 6011
        semaphore = get_port_semaphore(port)

        mock_civwebserver = Mock()
        mock_civwebserver.loginpacket = '{"username":"test","port":6011}'

        civcom = CivCom("test_user", port, "test_key", mock_civwebserver)
        civcom.port_semaphore = semaphore
        semaphore.acquire(blocking=False)

        self.assertFalse(civcom.handshake_complete.is_set())

        civcom._release_handshake_semaphore()

        self.assertTrue(civcom.handshake_complete.is_set())


class TestConcurrentConnections(unittest.TestCase):
    """Integration tests for concurrent connection handling"""

    def setUp(self):
        """Clear semaphores before each test"""
        with _semaphore_lock:
            _port_semaphores.clear()

    def tearDown(self):
        """Clean up semaphores after each test"""
        with _semaphore_lock:
            _port_semaphores.clear()

    def test_queuing_behavior(self):
        """Test that connections are properly queued when at capacity"""
        port = 6012
        semaphore = get_port_semaphore(port)
        connection_order = []
        lock = threading.Lock()

        def simulate_connection(connection_id, delay_before_release):
            """Simulate a connection that acquires, does work, then releases"""
            semaphore.acquire(blocking=True)
            with lock:
                connection_order.append(f"acquired_{connection_id}")

            # Simulate handshake time
            time.sleep(delay_before_release)

            semaphore.release()
            with lock:
                connection_order.append(f"released_{connection_id}")

        # Start MAX_CONCURRENT_HANDSHAKES + 2 connections
        num_connections = MAX_CONCURRENT_HANDSHAKES + 2
        threads = []

        for i in range(num_connections):
            t = threading.Thread(
                target=simulate_connection,
                args=(i, 0.05)  # 50ms handshake time
            )
            threads.append(t)

        # Start all threads nearly simultaneously
        for t in threads:
            t.start()

        # Wait for all to complete
        for t in threads:
            t.join(timeout=5.0)

        # Verify behavior:
        # - First MAX_CONCURRENT_HANDSHAKES should acquire quickly
        # - Rest should wait and acquire as others release
        acquired_events = [e for e in connection_order if e.startswith("acquired_")]
        released_events = [e for e in connection_order if e.startswith("released_")]

        self.assertEqual(len(acquired_events), num_connections)
        self.assertEqual(len(released_events), num_connections)

    def test_max_concurrent_limit_enforced(self):
        """Test that no more than MAX_CONCURRENT_HANDSHAKES are active simultaneously"""
        port = 6013
        semaphore = get_port_semaphore(port)
        active_count = [0]
        max_observed = [0]
        lock = threading.Lock()
        all_started = threading.Barrier(MAX_CONCURRENT_HANDSHAKES + 3)

        def simulate_connection():
            """Simulate a connection and track concurrent count"""
            try:
                all_started.wait(timeout=2.0)  # Wait for all threads to start
            except threading.BrokenBarrierError:
                pass

            semaphore.acquire(blocking=True)

            with lock:
                active_count[0] += 1
                if active_count[0] > max_observed[0]:
                    max_observed[0] = active_count[0]

            # Simulate some work
            time.sleep(0.02)

            with lock:
                active_count[0] -= 1

            semaphore.release()

        # Start more threads than MAX_CONCURRENT_HANDSHAKES
        num_threads = MAX_CONCURRENT_HANDSHAKES + 3
        threads = [threading.Thread(target=simulate_connection) for _ in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        # The max concurrent should never exceed MAX_CONCURRENT_HANDSHAKES
        self.assertLessEqual(
            max_observed[0],
            MAX_CONCURRENT_HANDSHAKES,
            f"Max concurrent ({max_observed[0]}) exceeded limit ({MAX_CONCURRENT_HANDSHAKES})"
        )


class TestMaxConcurrentHandshakesConfig(unittest.TestCase):
    """Test MAX_CONCURRENT_HANDSHAKES configuration"""

    def test_default_value_is_reasonable(self):
        """Test that the default MAX_CONCURRENT_HANDSHAKES is a reasonable value"""
        # Should be at least 1
        self.assertGreaterEqual(MAX_CONCURRENT_HANDSHAKES, 1)
        # Should be reasonable (not too high to overwhelm server)
        self.assertLessEqual(MAX_CONCURRENT_HANDSHAKES, 10)
        # Default is 3 (one user's worth of observers)
        self.assertEqual(MAX_CONCURRENT_HANDSHAKES, 3)


if __name__ == '__main__':
    unittest.main()
