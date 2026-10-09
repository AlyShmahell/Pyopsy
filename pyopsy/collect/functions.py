"""Record function data for each worker.

One worker keeps one set of call counts.
The snapshot merges the workers by filename, first line, and name.
"""

import os
import sys
import threading
import time
import tracemalloc


def function_key(filename, firstlineno, name):
    """Return the merge key for one function."""
    return (filename, firstlineno, name)


def key_from_code(code):
    """Return the merge key for a code object or a built-in name."""
    if isinstance(code, str):
        return ("<builtin>", 0, code)
    return (code.co_filename, code.co_firstlineno, code.co_name)


def _stats():
    """Return blank call counts, times, and memory."""
    return {
        "ncalls": 0,
        "tottime": 0.0,
        "cumtime": 0.0,
        "mem": 0,
        "mem_own": 0,
        "mem_mean": 0.0,
        "mem_peak": 0,
    }


def _traced():
    """Return the current traced Python memory."""
    if tracemalloc.is_tracing():
        current, _peak = tracemalloc.get_traced_memory()
        return current
    return 0


def _add_stats(target, source):
    """Add one row of counts into another."""
    target["ncalls"] += source.get("ncalls") or 0
    target["tottime"] += source.get("tottime") or 0.0
    target["cumtime"] += source.get("cumtime") or 0.0
    target["mem"] += source.get("mem") or 0
    target["mem_own"] += source.get("mem_own") or 0
    peak = source.get("mem_peak") or 0
    if peak > target["mem_peak"]:
        target["mem_peak"] = peak
    if target["ncalls"]:
        target["mem_mean"] = target["mem"] / target["ncalls"]


def merge_function_rows(worker_rows):
    """Merge function rows from each worker.

    Two workers that call one function become one row.
    """
    merged = {}
    for rows in worker_rows:
        for row in rows:
            key = function_key(row["filename"], row["firstlineno"], row["name"])
            if key not in merged:
                item = _stats()
                item["name"] = row["name"]
                item["filename"] = row["filename"]
                item["firstlineno"] = row["firstlineno"]
                item["callees"] = {}
                merged[key] = item
            _add_stats(merged[key], row)
            item = merged[key]
            for callee_key, callee in row.get("callees", {}).items():
                if callee_key not in item["callees"]:
                    item["callees"][callee_key] = _stats()
                _add_stats(item["callees"][callee_key], callee)
    return list(merged.values())


def callee_id(key):
    """Return a JSON key for one callee."""
    return "{0}|{1}|{2}".format(*key)


def serialize_function_rows(rows):
    """Return function rows with string callee keys."""
    serial = []
    for row in rows:
        callees = {}
        for key, value in row.get("callees", {}).items():
            callees[callee_id(key)] = value
        item = dict(row)
        item["id"] = callee_id(
            function_key(row["filename"], row["firstlineno"], row["name"])
        )
        item["callees"] = callees
        serial.append(item)
    return serial


def _copy_rows(rows):
    """Copy function rows for a merge."""
    copies = []
    for row in rows.values():
        callees = {}
        for key, value in row["callees"].items():
            callees[key] = dict(value)
        copies.append(
            {
                "name": row["name"],
                "filename": row["filename"],
                "firstlineno": row["firstlineno"],
                "ncalls": row["ncalls"],
                "tottime": row["tottime"],
                "cumtime": row["cumtime"],
                "mem": row.get("mem") or 0,
                "mem_own": row.get("mem_own") or 0,
                "mem_mean": row.get("mem_mean") or 0.0,
                "mem_peak": row.get("mem_peak") or 0,
                "callees": callees,
            }
        )
    return copies


def _ours(code):
    """Return True when the code belongs to Pyopsy."""
    filename = getattr(code, "co_filename", "")
    return "pyopsy" in filename.replace("\\", "/")


def _stdlib_file(filename):
    """Return True when the file is in the Python library."""
    if not filename or filename.startswith("<"):
        return True
    path = os.path.normcase(os.path.abspath(filename))
    stdlib = os.path.normcase(os.path.abspath(os.path.dirname(os.__file__)))
    return path.startswith(stdlib + os.sep)


def filter_function_rows(rows, keep_files):
    """Keep rows from marked-function files.

    The filter drops Pyopsy frames and stdlib frames.
    """
    keep_abs = set()
    for path in keep_files:
        if path and not path.startswith("<"):
            keep_abs.add(os.path.abspath(path))
    kept = []
    kept_keys = set()
    for row in rows:
        path = row["filename"]
        if "pyopsy" in path.replace("\\", "/"):
            continue
        if _stdlib_file(path):
            continue
        abs_path = os.path.abspath(path) if path and not path.startswith("<") else path
        if abs_path not in keep_abs:
            continue
        kept.append(row)
        kept_keys.add(function_key(row["filename"], row["firstlineno"], row["name"]))
    filtered = []
    for row in kept:
        item = dict(row)
        item["callees"] = {
            key: value
            for key, value in row.get("callees", {}).items()
            if key in kept_keys
        }
        filtered.append(item)
    return filtered


class _WorkerState:
    """Hold the call stack and the function rows for one worker."""

    def __init__(self):
        self.stack = []
        self.rows = {}

    def row(self, key, name, filename, firstlineno):
        """Return the row for one function.

        The method creates the row on the first call.
        """
        if key not in self.rows:
            item = _stats()
            item["name"] = name
            item["filename"] = filename
            item["firstlineno"] = firstlineno
            item["callees"] = {}
            self.rows[key] = item
        return self.rows[key]


class FunctionCollector:
    """Record function data with one stack per worker."""

    def __init__(self):
        self._local = threading.local()
        self._lock = threading.Lock()
        self._workers = {}
        self._previous_profile = None
        self._previous_thread_profile = None
        self._active = False

    def start(self):
        """Start function data for this worker and for later workers.

        Start the session before you start a worker.
        """
        self._previous_profile = sys.getprofile()
        self._previous_thread_profile = threading.getprofile()
        self._active = True
        sys.setprofile(self._dispatch)
        threading.setprofile(self._dispatch)

    def pause(self):
        """Stop the profile hook for one snapshot."""
        sys.setprofile(self._previous_profile)

    def resume(self):
        """Restore the profile hook after one snapshot."""
        if self._active:
            sys.setprofile(self._dispatch)

    def snapshot(self):
        """Return merged function data from every worker."""
        with self._lock:
            copies = []
            for state in self._workers.values():
                copies.append(_copy_rows(state.rows))
        return merge_function_rows(copies)

    def stop(self):
        """Stop function data.

        The collector restores the previous profile hooks.
        """
        self._active = False
        sys.setprofile(self._previous_profile)
        threading.setprofile(self._previous_thread_profile)

    def _state(self):
        """Return the function rows for this worker."""
        state = getattr(self._local, "state", None)
        if state is None:
            state = _WorkerState()
            self._local.state = state
            with self._lock:
                self._workers[threading.get_ident()] = state
        return state

    def _dispatch(self, frame, event, _arg):
        """Record one call or one return for this worker."""
        if _ours(frame.f_code):
            return
        if event == "call":
            self._on_call(frame)
        elif event == "return":
            self._on_return()

    def _on_call(self, frame):
        """Push one Python call onto the worker stack."""
        code = frame.f_code
        if _ours(code):
            return
        state = self._state()
        now = time.perf_counter()
        state.stack.append((code, now, 0.0, _traced(), 0))

    def _on_return(self):
        """Pop one Python call and add the times."""
        state = getattr(self._local, "state", None)
        if state is None or not state.stack:
            return
        code, start, child, start_traced, child_mem = state.stack.pop()
        now = time.perf_counter()
        elapsed = now - start
        inline = elapsed - child
        if inline < 0:
            inline = 0.0
        delta = _traced() - start_traced
        if delta < 0:
            delta = 0
        own_mem = delta - child_mem
        if own_mem < 0:
            own_mem = 0
        key = key_from_code(code)
        row = state.row(key, code.co_name, code.co_filename, code.co_firstlineno)
        row["ncalls"] += 1
        row["tottime"] += inline
        row["cumtime"] += elapsed
        row["mem"] += delta
        row["mem_own"] += own_mem
        if delta > row["mem_peak"]:
            row["mem_peak"] = delta
        row["mem_mean"] = row["mem"] / row["ncalls"]
        if state.stack:
            parent_code, parent_start, parent_child, parent_traced, parent_child_mem = (
                state.stack[-1]
            )
            state.stack[-1] = (
                parent_code,
                parent_start,
                parent_child + elapsed,
                parent_traced,
                parent_child_mem + delta,
            )
            parent_key = key_from_code(parent_code)
            parent = state.row(
                parent_key,
                parent_code.co_name,
                parent_code.co_filename,
                parent_code.co_firstlineno,
            )
            callee = parent["callees"].get(key)
            if callee is None:
                callee = _stats()
                parent["callees"][key] = callee
            callee["ncalls"] += 1
            callee["tottime"] += inline
            callee["cumtime"] += elapsed
            callee["mem"] += delta
            callee["mem_own"] += own_mem
            if delta > callee["mem_peak"]:
                callee["mem_peak"] = delta
            callee["mem_mean"] = callee["mem"] / callee["ncalls"]
