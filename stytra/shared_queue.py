"""Zero-copy, shared-memory-backed replacement for the (now unmaintained)
``arrayqueues`` package, built entirely on the standard library.

Provides ``IndexedArrayQueue`` and ``TimestampedArrayQueue`` with the same
constructor signature and ``get``/``put``/``clear`` behavior stytra already
relies on: ``get(timeout=...)`` raises stdlib ``queue.Empty`` on timeout and
blocks forever when no timeout is given, ``put`` raises stdlib ``queue.Full``
when the ring buffer has no free slot, and ``.queue.qsize()`` stays a cheap,
macOS-safe approximation (``multiprocessing.Queue.qsize()`` relies on
``sem_getvalue()``, which raises ``NotImplementedError`` on macOS).

Every queue instance in stytra's pipeline is used as a strictly
single-producer/single-consumer channel (confirmed by tracing every call
site), so no broadcast/multi-cursor consumption is implemented here.
"""

from datetime import datetime
from multiprocessing import Value, get_context
from multiprocessing import queues as mp_queues
from multiprocessing.shared_memory import SharedMemory
from queue import Empty, Full

import numpy as np


class CountedQueue(mp_queues.Queue):
    """``multiprocessing.Queue`` with a macOS-safe ``qsize()``/``empty()``,
    tracked via a shared counter instead of ``sem_getvalue()``."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("ctx", get_context())
        super().__init__(*args, **kwargs)
        self._counter = Value("l", 0)

    def __getstate__(self):
        return super().__getstate__() + (self._counter,)

    def __setstate__(self, state):
        *base_state, counter = state
        super().__setstate__(tuple(base_state))
        self._counter = counter

    def put(self, *args, **kwargs):
        super().put(*args, **kwargs)
        with self._counter.get_lock():
            self._counter.value += 1

    def get(self, *args, **kwargs):
        item = super().get(*args, **kwargs)
        with self._counter.get_lock():
            self._counter.value -= 1
        return item

    def qsize(self):
        return max(int(self._counter.value), 0)

    def empty(self):
        return self.qsize() <= 0


class _SharedRingQueue:
    """Pre-allocated ring buffer of frame slots on a
    ``multiprocessing.shared_memory.SharedMemory`` block, with put/get
    metadata (dtype, shape, slot index, plus any subclass-specific fields
    such as a timestamp) carried alongside on a small ``CountedQueue``.
    """

    def __init__(self, max_mbytes=100):
        self.maxbytes = int(max_mbytes * 1_000_000)
        self._shm = SharedMemory(create=True, size=max(self.maxbytes, 1))
        self._is_owner = True

        self.queue = CountedQueue()

        self._dtype = None
        self._shape = None
        self._n_slots = None
        self._ring = None
        # Circular write cursor. Producer-local only (single-producer):
        # never synchronized across processes, just like the rest of the
        # lazily-bound view state below.
        self._write_idx = 0

    # -- pickling: only the shared memory *name* crosses process boundaries,
    # never the live SharedMemory/ndarray view (rebuilt lazily on first use).
    def __getstate__(self):
        state = self.__dict__.copy()
        state["_shm_name"] = self._shm.name
        del state["_shm"]
        del state["_ring"]
        state["_is_owner"] = False
        return state

    def __setstate__(self, state):
        shm_name = state.pop("_shm_name")
        self.__dict__.update(state)
        self._shm = SharedMemory(name=shm_name, create=False)
        # Note: CPython's resource_tracker is a single background process
        # shared by the whole process family (parent + every spawned/forked
        # child), not one per process. Do NOT call resource_tracker.unregister()
        # here - that would wipe the *shared* tracking entry the owner still
        # needs, causing a double-unregister/KeyError when it later calls
        # unlink(). Only the owner's explicit unlink() (below) should ever
        # deregister; every other attach just leaves the redundant (harmless,
        # idempotent) registration in place until then.
        self._ring = None

    def _bind_view(self, dtype, shape, n_slots=None):
        dtype = np.dtype(dtype)
        shape = tuple(shape)
        if self._ring is not None and self._dtype == dtype and self._shape == shape:
            return

        itemsize = dtype.itemsize * int(np.prod(shape)) if shape else dtype.itemsize
        if n_slots is None:
            n_slots = max(self.maxbytes // itemsize, 1)

        self._dtype = dtype
        self._shape = shape
        self._n_slots = n_slots
        self._ring = np.ndarray((n_slots,) + shape, dtype=dtype, buffer=self._shm.buf)

    def _put(self, array, meta_extra):
        array = np.asarray(array)
        self._bind_view(array.dtype, array.shape)
        # Capacity is tracked via the metadata queue's own occupancy count
        # (already maintained by CountedQueue) rather than a separate
        # free-slot pool - avoids ever having to pre-enqueue one item per
        # ring slot, which is slow when n_slots is large.
        if self.queue.qsize() >= self._n_slots:
            raise Full("shared ring queue full ({} slots)".format(self._n_slots))
        slot = self._write_idx
        self._ring[slot, ...] = array
        self.queue.put(
            meta_extra + (str(self._dtype), self._shape, self._n_slots, slot)
        )
        self._write_idx = (self._write_idx + 1) % self._n_slots

    def _get(self, timeout=None):
        item = self.queue.get(timeout=timeout)
        *meta_extra, dtype_str, shape, n_slots, slot = item
        self._bind_view(dtype_str, shape, n_slots=n_slots)
        view = self._ring[slot, ...]
        return tuple(meta_extra) + (view,)

    def clear(self):
        """Drains and resets the queue without needing to read every item."""
        while True:
            try:
                self.queue.get_nowait()
            except Empty:
                break
        self._write_idx = 0

    def qsize(self):
        return self.queue.qsize()

    def empty(self):
        return self.queue.empty()

    def close(self):
        """Detach this process's local handle to the shared memory block
        and the metadata queue's own pipe/feeder thread."""
        try:
            self.queue.close()
        except Exception:
            pass
        try:
            self._shm.close()
        except Exception:
            pass

    def unlink(self):
        """Free the underlying shared memory. Only the owner (the process
        that constructed this queue, i.e. the main process) should call
        this, once every process using the queue has exited."""
        if not self._is_owner:
            return
        try:
            self._shm.unlink()
        except FileNotFoundError:
            pass


class IndexedArrayQueue(_SharedRingQueue):
    """Auto-tags each array with an incrementing index; ``get`` returns
    ``(timestamp, index, array)``."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._counter = 0

    def put(self, array):
        self._put(array, (datetime.now(), self._counter))
        self._counter += 1

    def get(self, timeout=None):
        return self._get(timeout=timeout)


class TimestampedArrayQueue(_SharedRingQueue):
    """``get`` returns ``(timestamp, array)``."""

    def put(self, array, timestamp=None):
        if timestamp is None:
            timestamp = datetime.now()
        self._put(array, (timestamp,))

    def get(self, timeout=None):
        return self._get(timeout=timeout)
