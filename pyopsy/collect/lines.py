"""Record line data for a marked function.

The line recorder uses sys.monitoring on the marked code object.
"""

import sys
import threading
import time


_EVENTS = None


def _events():
    """Return the local event set for a marked function."""
    global _EVENTS
    if _EVENTS is None:
        events = sys.monitoring.events
        _EVENTS = (
            events.LINE
            | events.PY_RETURN
            | events.PY_YIELD
            | events.PY_RESUME
            | events.PY_START
        )
    return _EVENTS


def _free_tool_id():
    """Take a free monitoring tool id.

    The collector leaves PROFILER_ID free.
    """
    skip = {sys.monitoring.PROFILER_ID}
    for tool_id in range(0, 6):
        if tool_id in skip:
            continue
        try:
            sys.monitoring.use_tool_id(tool_id, "pyopsy")
            return tool_id
        except ValueError:
            continue
    raise RuntimeError("Pyopsy cannot take a monitoring tool id.")


class _WorkerClock:
    """Hold the open line and the clock for one worker."""

    def __init__(self):
        self.stack = []


class LineCollector:
    """Record line number, hit count, and line time."""

    def __init__(self):
        self._tool_id = None
        self._lock = threading.Lock()
        self._local = threading.local()
        self._counts = {}
        self._rows = {}
        self._codes = {}

    def start(self):
        """Start the line recorder.

        The collector takes a free tool id.
        """
        self._tool_id = _free_tool_id()
        events = sys.monitoring.events
        sys.monitoring.register_callback(self._tool_id, events.LINE, self._on_line)
        sys.monitoring.register_callback(
            self._tool_id, events.PY_RETURN, self._on_return
        )
        sys.monitoring.register_callback(
            self._tool_id, events.PY_YIELD, self._on_yield
        )
        sys.monitoring.register_callback(
            self._tool_id, events.PY_RESUME, self._on_resume
        )
        sys.monitoring.register_callback(
            self._tool_id, events.PY_START, self._on_start
        )

    def add_function(self, func):
        """Remember a marked function for line data."""
        code = getattr(func, "__code__", None)
        if code is None:
            return
        self._codes[id(code)] = code

    def enter(self, code):
        """Turn on line events for a marked function.

        The last worker that leaves turns the events off.
        """
        if self._tool_id is None:
            return
        with self._lock:
            count = self._counts.get(id(code), 0) + 1
            self._counts[id(code)] = count
            if count == 1:
                sys.monitoring.set_local_events(self._tool_id, code, _events())

    def leave(self, code):
        """Turn off line events when the last worker leaves."""
        if self._tool_id is None:
            return
        self._close_open()
        clock = getattr(self._local, "clock", None)
        if clock is not None:
            while (
                clock.stack
                and clock.stack[-1]["code"] is code
                and not clock.stack[-1].get("suspended")
            ):
                clock.stack.pop()
        with self._lock:
            count = self._counts.get(id(code), 0) - 1
            if count <= 0:
                self._counts.pop(id(code), None)
                sys.monitoring.set_local_events(
                    self._tool_id, code, sys.monitoring.events.NO_EVENTS
                )
            else:
                self._counts[id(code)] = count

    def snapshot(self):
        """Return line data for each marked function."""
        with self._lock:
            functions = []
            for code in self._codes.values():
                rows = self._rows.get(id(code), {})
                line_rows = []
                for lineno in sorted(rows):
                    hits, line_time = rows[lineno]
                    line_rows.append(
                        {
                            "lineno": lineno,
                            "hits": hits,
                            "time": line_time / 1_000_000_000,
                        }
                    )
                functions.append(
                    {
                        "name": code.co_name,
                        "filename": code.co_filename,
                        "firstlineno": code.co_firstlineno,
                        "source": _source_lines(code),
                        "lines": line_rows,
                        "line_data_includes_recorder_time": bool(line_rows),
                    }
                )
        return functions

    def stop(self):
        """Stop the line recorder.

        The collector frees the tool id.
        """
        if self._tool_id is None:
            return
        events = sys.monitoring.events
        for event in (
            events.LINE,
            events.PY_RETURN,
            events.PY_YIELD,
            events.PY_RESUME,
            events.PY_START,
        ):
            sys.monitoring.register_callback(self._tool_id, event, None)
        for code in list(self._codes.values()):
            sys.monitoring.set_local_events(
                self._tool_id, code, events.NO_EVENTS
            )
        sys.monitoring.free_tool_id(self._tool_id)
        self._tool_id = None

    def claim_tool_id(self):
        """Take a new tool id after a fork."""
        self.stop()
        self.start()
        for code in self._codes.values():
            if self._counts.get(id(code), 0) > 0:
                sys.monitoring.set_local_events(self._tool_id, code, _events())

    def _clock(self):
        """Return the open-line stack for this worker."""
        clock = getattr(self._local, "clock", None)
        if clock is None:
            clock = _WorkerClock()
            self._local.clock = clock
        return clock

    def _on_start(self, code, _offset):
        """Push a frame when a marked function starts."""
        clock = self._clock()
        clock.stack.append(
            {
                "code": code,
                "line": None,
                "t0": time.perf_counter_ns(),
                "suspended": False,
            }
        )

    def _on_line(self, code, lineno):
        """Close the open line and open this line."""
        now = time.perf_counter_ns()
        clock = self._clock()
        if not clock.stack:
            clock.stack.append(
                {
                    "code": code,
                    "line": None,
                    "t0": now,
                    "suspended": False,
                }
            )
        frame = clock.stack[-1]
        self._charge(frame, now)
        frame["line"] = lineno
        frame["t0"] = now
        self._hit(code, lineno)

    def _on_return(self, code, _offset, _retval):
        """Close the open line when the function returns."""
        self._close_open()
        clock = getattr(self._local, "clock", None)
        if clock is not None and clock.stack:
            if clock.stack[-1]["code"] is code:
                clock.stack.pop()

    def _on_yield(self, _code, _offset, _retval):
        """Close the open line and drop the clock."""
        self._close_open()
        clock = getattr(self._local, "clock", None)
        if clock is not None and clock.stack:
            clock.stack[-1]["t0"] = None
            clock.stack[-1]["line"] = None
            clock.stack[-1]["suspended"] = True

    def _on_resume(self, _code, _offset):
        """Start the clock after a yield."""
        clock = self._clock()
        if not clock.stack:
            return
        clock.stack[-1]["t0"] = time.perf_counter_ns()
        clock.stack[-1]["line"] = None
        clock.stack[-1]["suspended"] = False

    def _close_open(self):
        """Charge the open line and clear the clock."""
        clock = getattr(self._local, "clock", None)
        if clock is None or not clock.stack:
            return
        frame = clock.stack[-1]
        now = time.perf_counter_ns()
        self._charge(frame, now)
        frame["line"] = None
        frame["t0"] = None

    def _charge(self, frame, now):
        """Add elapsed time to the open line."""
        if frame["line"] is None or frame["t0"] is None:
            return
        delta = now - frame["t0"]
        if delta < 0:
            return
        self._add_time(frame["code"], frame["line"], delta)

    def _hit(self, code, lineno):
        """Add one hit to a source line."""
        with self._lock:
            rows = self._rows.setdefault(id(code), {})
            hits, line_time = rows.get(lineno, (0, 0))
            rows[lineno] = (hits + 1, line_time)

    def _add_time(self, code, lineno, delta):
        """Add line time to a source line."""
        with self._lock:
            rows = self._rows.setdefault(id(code), {})
            hits, line_time = rows.get(lineno, (0, 0))
            rows[lineno] = (hits, line_time + delta)


def _source_lines(code):
    """Return the source lines of a marked function.

    The source starts at the def line. The source includes the body.
    """
    import linecache

    name = code.co_name
    start = code.co_firstlineno
    def_line = start
    for lineno in range(start, start + 40):
        text = linecache.getline(code.co_filename, lineno)
        stripped = text.lstrip()
        head = stripped.split("(", 1)[0]
        if stripped.startswith("def ") or stripped.startswith("async def "):
            if name in head.split():
                def_line = lineno
                break
    rows = []
    for lineno in range(def_line, def_line + 120):
        text = linecache.getline(code.co_filename, lineno)
        if not text:
            break
        stripped = text.lstrip()
        if (
            lineno > def_line
            and text
            and not text[0].isspace()
            and stripped
            and stripped.startswith(("def ", "async def ", "class "))
        ):
            break
        rows.append({"lineno": lineno, "text": text.rstrip("\n")})
    return rows
