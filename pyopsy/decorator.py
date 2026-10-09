"""Mark a function and record wall time."""

import functools
import inspect
import json
import time
import tracemalloc

from pyopsy.collect.wall import register
from pyopsy.session import get_session
from pyopsy.view import format_bytes


def _kind(func):
    """Return the kind of a marked function."""
    if inspect.isasyncgenfunction(func):
        return "async_generator"
    if inspect.isgeneratorfunction(func):
        return "generator"
    if inspect.iscoroutinefunction(func):
        return "async_function"
    return "function"


class Pyopsy:
    """Mark a function and record wall time for each call."""

    def __init__(self, func=None, *, lines=False):
        self.func = None
        self.lines = lines
        self.kind = "function"
        self.profiled = False
        self.profile = {}
        self.wall_time = 0.0
        self.total_wall_time = 0.0
        self.call_count = 0
        self.mem_mean = 0.0
        self.mem_peak = 0.0
        self._memsamples = []
        if func is not None:
            self._bind(func)

    def _bind(self, func):
        """Attach this marker to one function."""
        self.func = func
        self.kind = _kind(func)
        functools.update_wrapper(self, func)
        register(self)

    def __call__(self, *args, **kwargs):
        """Mark a function, or run a marked function."""
        if self.func is None:
            self._bind(args[0])
            return self
        return self._run(args, kwargs)

    def wall_row(self):
        """Return wall time for the live page."""
        filename = ""
        firstlineno = 0
        name = ""
        if self.func is not None:
            name = self.func.__name__
            code = getattr(self.func, "__code__", None)
            if code is not None:
                filename = code.co_filename
                firstlineno = code.co_firstlineno
        return {
            "name": name,
            "filename": filename,
            "firstlineno": firstlineno,
            "kind": self.kind,
            "wall_time": self.wall_time,
            "total_wall_time": self.total_wall_time,
            "call_count": self.call_count,
            "lines": self.lines,
            "mem_mean": self.mem_mean,
            "mem_peak": self.mem_peak,
        }

    def __str__(self):
        """Return wall time and memory as JSON."""
        if not self.profiled:
            name = self.func.__name__ if self.func is not None else "function"
            return f"{name} has not run."
        return json.dumps(self.profile, indent=4)

    def _run(self, args, kwargs):
        """Run the marked function and record wall time."""
        session = get_session()
        if self.kind == "generator":
            return self._run_generator(session, args, kwargs)
        if self.kind == "async_generator":
            return self._run_async_generator(session, args, kwargs)
        if self.kind == "async_function":
            return self._run_async_function(session, args, kwargs)
        return self._run_function(session, args, kwargs)

    def _run_function(self, session, args, kwargs):
        """Run a sync function."""
        self._begin(session)
        start = time.perf_counter()
        try:
            result = self.func(*args, **kwargs)
        finally:
            self._sample_mem(session)
            self._end(session, start)
        return result

    def _run_async_function(self, session, args, kwargs):
        """Run an async function."""

        async def wrapper():
            self._begin(session)
            start = time.perf_counter()
            try:
                result = await self.func(*args, **kwargs)
            finally:
                self._sample_mem(session)
                self._end(session, start)
            return result

        return wrapper()

    def _run_generator(self, session, args, kwargs):
        """Run a generator.

        The line recorder starts and stops around each send.
        """

        def wrapper():
            start = time.perf_counter()
            self._begin_call(session)
            iterator = self.func(*args, **kwargs)
            try:
                incoming = None
                while True:
                    self._enter_lines(session)
                    try:
                        if incoming is None:
                            item = next(iterator)
                        else:
                            item = iterator.send(incoming)
                    except StopIteration:
                        break
                    finally:
                        self._leave_lines(session)
                    self._sample_mem(session)
                    incoming = yield item
            finally:
                self._end(session, start)

        return wrapper()

    def _run_async_generator(self, session, args, kwargs):
        """Run an async generator.

        The line recorder starts and stops around each asend.
        """

        async def wrapper():
            start = time.perf_counter()
            self._begin_call(session)
            iterator = self.func(*args, **kwargs)
            incoming = None
            try:
                while True:
                    self._enter_lines(session)
                    try:
                        item = await iterator.asend(incoming)
                    except StopAsyncIteration:
                        break
                    finally:
                        self._leave_lines(session)
                    self._sample_mem(session)
                    incoming = yield item
            finally:
                self._end(session, start)

        return wrapper()

    def _begin(self, session):
        """Start one marked call."""
        self._begin_call(session)
        self._enter_lines(session)

    def _begin_call(self, session):
        """Start wall time and memory for one call."""
        self._memsamples = []
        if session is None and not tracemalloc.is_tracing():
            tracemalloc.start()

    def _enter_lines(self, session):
        """Start the line recorder for this function."""
        if session is None or not self.lines:
            return
        session.enter_lines(self.func)

    def _leave_lines(self, session):
        """Stop the line recorder for this function."""
        if session is None or not self.lines:
            return
        session.leave_lines(self.func)

    def _sample_mem(self, _session):
        """Read traced Python memory for this call."""
        if tracemalloc.is_tracing():
            current, _peak = tracemalloc.get_traced_memory()
            self._memsamples.append(current)

    def _end(self, session, start):
        """Store wall time for this call."""
        if self.kind in ("function", "async_function"):
            self._leave_lines(session)
        elapsed = time.perf_counter() - start
        self.wall_time = elapsed
        self.total_wall_time += elapsed
        self.call_count += 1
        if not self._memsamples:
            self._memsamples.append(0)
        self.mem_mean = sum(self._memsamples) / len(self._memsamples)
        self.mem_peak = max(self._memsamples)
        if session is None and tracemalloc.is_tracing():
            tracemalloc.stop()
        self.profile = {
            "func": self.func.__name__,
            "kind": self.kind,
            "mem_mean": format_bytes(self.mem_mean),
            "mem_peak": format_bytes(self.mem_peak),
            "perfc": elapsed,
        }
        self.profiled = True
