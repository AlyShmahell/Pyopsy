"""Record RSS and traced Python memory.

This collector owns tracemalloc while a session is open.
"""

import threading
import time
import tracemalloc

import psutil

from pyopsy.view import format_bytes


class MemoryCollector:
    """Sample RSS and traced Python memory."""

    def __init__(self, interval=0.1):
        self.interval = interval
        self._process = None
        self._lock = threading.Lock()
        self._rss = 0
        self._peak_rss = 0
        self._traced = 0
        self._peak_traced = 0
        self._samples = []
        self._stop = threading.Event()
        self._worker = None

    def start(self):
        """Start memory sampling.

        The collector starts tracemalloc.
        """
        self._process = psutil.Process()
        if not tracemalloc.is_tracing():
            tracemalloc.start()
        self._stop.clear()
        self._sample()
        self._worker = threading.Thread(
            target=self._run,
            name="pyopsy-memory",
            daemon=True,
        )
        self._worker.start()

    def snapshot(self):
        """Return the latest memory sample."""
        with self._lock:
            samples = list(self._samples[-120:])
            rss = self._rss
            peak_rss = self._peak_rss
            traced = self._traced
            peak_traced = self._peak_traced
        return {
            "rss": rss,
            "rss_text": format_bytes(rss),
            "peak_rss": peak_rss,
            "peak_rss_text": format_bytes(peak_rss),
            "traced": traced,
            "traced_text": format_bytes(traced),
            "peak_traced": peak_traced,
            "peak_traced_text": format_bytes(peak_traced),
            "samples": samples,
        }

    def stop(self):
        """Stop memory sampling.

        The collector stops tracemalloc.
        """
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=1.0)
            self._worker = None
        if tracemalloc.is_tracing():
            tracemalloc.stop()

    def _run(self):
        """Sample memory until the session stops."""
        while not self._stop.wait(self.interval):
            self._sample()

    def _sample(self):
        """Read one memory sample."""
        rss = 0
        if self._process is not None:
            try:
                rss = int(self._process.memory_info().rss)
            except (psutil.Error, OSError):
                rss = 0
        traced = 0
        peak_traced = 0
        if tracemalloc.is_tracing():
            traced, peak_traced = tracemalloc.get_traced_memory()
        now = time.perf_counter()
        with self._lock:
            self._rss = rss
            if rss > self._peak_rss:
                self._peak_rss = rss
            self._traced = traced
            if peak_traced > self._peak_traced:
                self._peak_traced = peak_traced
            self._samples.append(
                {
                    "t": now,
                    "rss": rss,
                    "traced": traced,
                }
            )
            if len(self._samples) > 600:
                del self._samples[:300]
