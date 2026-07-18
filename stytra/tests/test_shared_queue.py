import multiprocessing
import time

import numpy as np
import pytest
from queue import Empty, Full

from stytra.shared_queue import IndexedArrayQueue, TimestampedArrayQueue


def test_timestamped_put_get_roundtrip():
    q = TimestampedArrayQueue(max_mbytes=5)
    try:
        frame = np.arange(100, dtype=np.uint8).reshape(10, 10)
        q.put(frame, timestamp=1.23)
        timestamp, out = q.get(timeout=1)
        assert timestamp == 1.23
        np.testing.assert_array_equal(out, frame)
    finally:
        q.close()
        q.unlink()


def test_indexed_put_get_roundtrip():
    q = IndexedArrayQueue(max_mbytes=5)
    try:
        frame = np.ones((4, 4), dtype=np.float32)
        q.put(frame)
        q.put(frame * 2)
        _, idx0, out0 = q.get(timeout=1)
        _, idx1, out1 = q.get(timeout=1)
        assert idx0 == 0
        assert idx1 == 1
        np.testing.assert_array_equal(out0, frame)
        np.testing.assert_array_equal(out1, frame * 2)
    finally:
        q.close()
        q.unlink()


def test_get_timeout_raises_empty():
    q = TimestampedArrayQueue(max_mbytes=5)
    try:
        with pytest.raises(Empty):
            q.get(timeout=0.05)
    finally:
        q.close()
        q.unlink()


def test_put_full_raises_full():
    frame = np.zeros((10, 10), dtype=np.uint8)
    # small enough to only fit a handful of slots
    q = TimestampedArrayQueue(max_mbytes=frame.nbytes * 3 / 1e6)
    try:
        with pytest.raises(Full):
            for _ in range(1000):
                q.put(frame)
    finally:
        q.close()
        q.unlink()


def test_clear_resets_capacity():
    frame = np.zeros((10, 10), dtype=np.uint8)
    q = TimestampedArrayQueue(max_mbytes=frame.nbytes * 3 / 1e6)
    try:
        with pytest.raises(Full):
            for _ in range(1000):
                q.put(frame)
        q.clear()
        # after clearing, the full slot pool should be available again
        for _ in range(2):
            q.put(frame)
    finally:
        q.close()
        q.unlink()


def _producer(q, n):
    for i in range(n):
        q.put(np.full((8, 8), i, dtype=np.uint8), timestamp=float(i))
    q.close()


def test_cross_process_put_get():
    q = TimestampedArrayQueue(max_mbytes=5)
    try:
        n = 20
        proc = multiprocessing.get_context("spawn").Process(
            target=_producer, args=(q, n)
        )
        proc.start()
        received = []
        for _ in range(n):
            timestamp, arr = q.get(timeout=5)
            received.append((timestamp, arr.copy()))
        proc.join(timeout=5)
        assert not proc.is_alive()
        for i, (timestamp, arr) in enumerate(received):
            assert timestamp == float(i)
            np.testing.assert_array_equal(arr, np.full((8, 8), i, dtype=np.uint8))
    finally:
        q.close()
        q.unlink()
