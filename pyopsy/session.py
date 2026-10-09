"""Run one session and publish snapshots."""

import os
import threading
import time
import webbrowser

from pyopsy.collect.functions import (
    FunctionCollector,
    filter_function_rows,
    serialize_function_rows,
)
from pyopsy.collect.lines import LineCollector
from pyopsy.collect.memory import MemoryCollector
from pyopsy.collect.wall import WallCollector, marks
from pyopsy.hub import (
    HUB_ENV,
    PARENT_ENV,
    Hub,
    HubClient,
    http_port,
    is_parent,
    mpi_rank,
)
from pyopsy.serve.server import PageServer
from pyopsy.tree import build_tree
from pyopsy.view import CliView, FileView

_session = None


def get_session():
    """Return the open session.

    The result is None when no session is open.
    """
    return _session


def set_session(session):
    """Store the open session.

    Pass None when the session stops.
    """
    global _session
    _session = session


def build_snapshot(
    session_time,
    process_id,
    rank,
    port,
    wall,
    function_data,
    line_data,
    memory,
    processes=None,
):
    """Build one snapshot.

    The four data blocks stay side by side.
    A process list is present only for the parent page.
    """
    snapshot = {
        "session_time": session_time,
        "runtime": sum((row.get("total_wall_time") or 0) for row in (wall or [])),
        "process_id": process_id,
        "rank": rank,
        "port": port,
        "wall": wall,
        "function_data": function_data,
        "line_data": line_data,
        "memory": memory,
    }
    if processes is not None:
        snapshot["processes"] = processes
    return snapshot


class Session:
    """Record function data, memory, wall time, and line data."""

    def __init__(
        self,
        open_browser=True,
        interval=0.5,
        host="127.0.0.1",
        port=8765,
        cli=False,
        log=None,
    ):
        self.open_browser = open_browser
        self.interval = interval
        self.host = host
        self.base_port = port
        self.port = http_port(port)
        self.cli = cli
        self.log_path = log
        self.functions = FunctionCollector()
        self.memory = MemoryCollector()
        self.wall = WallCollector()
        self.lines = LineCollector()
        self.hub = None
        self.client = None
        self.server = None
        self._file = None
        self._cli = None
        self._started = time.perf_counter()
        self._stop = threading.Event()
        self._worker = None
        self._latest = None
        self._lock = threading.Lock()

    def start(self):
        """Start the session.

        The session records function data and memory.
        The session does not record line data for an unmarked function.
        """
        set_session(self)
        self._started = time.perf_counter()
        self.memory.start()
        self.functions.start()
        self.wall.start()
        self.lines.start()
        for mark in marks():
            if mark.lines:
                self.lines.add_function(mark.func)
        parent = is_parent()
        if parent:
            self.hub = Hub(self.host)
            self.hub.start()
            self.server = PageServer(
                self.host,
                self.port,
                self.latest,
            )
            self.port = self.server.start()
            url = f"http://{self.host}:{self.port}/"
            print(f"Pyopsy page: {url}", flush=True)
            if self.open_browser:
                try:
                    webbrowser.open(url)
                except OSError:
                    pass
            if self.log_path:
                self._file = FileView()
                self._file.start(self.log_path)
            if self.cli:
                self._cli = CliView()
                self._cli.start()
        else:
            self.client = HubClient()
            self.client.connect()
        self._stop.clear()
        self._worker = threading.Thread(
            target=self._publish,
            name="pyopsy-session",
            daemon=True,
        )
        self._worker.start()
        _install_fork_hook()

    def stop(self):
        """Stop the session.

        The context exit frees the tool id.
        """
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=1.0)
            self._worker = None
        if self.server is not None:
            self.server.stop()
            self.server = None
        self.functions.stop()
        self.memory.stop()
        self.wall.stop()
        self.lines.stop()
        if self.hub is not None:
            self.hub.stop()
            self.hub = None
            os.environ.pop(HUB_ENV, None)
            os.environ.pop(PARENT_ENV, None)
        if self.client is not None:
            self.client.close()
            self.client = None
        if self._file is not None:
            self._file.stop()
            self._file = None
        if self._cli is not None:
            self._cli.stop()
            self._cli = None
        set_session(None)

    def enter_lines(self, func):
        """Start line data for one marked function."""
        code = getattr(func, "__code__", None)
        if code is None:
            return
        self.lines.add_function(func)
        self.lines.enter(code)

    def leave_lines(self, func):
        """Stop line data for one marked function."""
        code = getattr(func, "__code__", None)
        if code is None:
            return
        self.lines.leave(code)

    def snapshot(self):
        """Build one snapshot from every collector."""
        self.functions.pause()
        try:
            keep_files = []
            for mark in marks():
                code = getattr(mark.func, "__code__", None)
                if code is not None:
                    keep_files.append(code.co_filename)
            function_rows = serialize_function_rows(
                filter_function_rows(self.functions.snapshot(), keep_files)
            )
            tree = build_tree(function_rows)
            snapshot = build_snapshot(
                session_time=time.perf_counter() - self._started,
                process_id=os.getpid(),
                rank=mpi_rank(),
                port=self.port,
                wall=self.wall.snapshot(),
                function_data={"rows": function_rows, "tree": tree},
                line_data=self.lines.snapshot(),
                memory=self.memory.snapshot(),
            )
            if self.hub is not None:
                children = self.hub.latest()
                processes = [
                    {
                        "process_id": os.getpid(),
                        "rank": snapshot["rank"],
                        "port": self.port,
                        "label": "parent",
                    }
                ]
                for child_id, child in children.items():
                    processes.append(
                        {
                            "process_id": child_id,
                            "rank": child.get("rank"),
                            "port": child.get("port"),
                            "label": "child",
                            "snapshot": child,
                        }
                    )
                snapshot["processes"] = processes
            return snapshot
        finally:
            self.functions.resume()

    def latest(self):
        """Return the last snapshot for the page."""
        with self._lock:
            if self._latest is None:
                return self.snapshot()
            return self._latest

    def after_fork(self):
        """Reconnect a child after fork."""
        if is_parent():
            return
        if self.server is not None:
            self.server.stop()
            self.server = None
        if self.hub is not None:
            self.hub.stop()
            self.hub = None
        self.lines.claim_tool_id()
        if self._file is not None:
            self._file.stop()
            self._file = None
        if self._cli is not None:
            self._cli.stop()
            self._cli = None
        self.client = HubClient()
        self.client.connect()

    def _publish(self):
        """Store or send snapshots until the session stops."""
        while not self._stop.is_set():
            snapshot = self.snapshot()
            with self._lock:
                self._latest = snapshot
            if self.client is not None:
                self.client.send(snapshot)
            if self._file is not None:
                self._file.write(snapshot)
            if self._cli is not None:
                self._cli.draw(snapshot)
            if self._stop.wait(self.interval):
                break

    def __enter__(self):
        """Start the session."""
        self.start()
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        """Stop the session."""
        self.stop()
        return False


def session(
    open_browser=True,
    interval=0.5,
    host="127.0.0.1",
    port=8765,
    cli=False,
    log=None,
):
    """Open a session that shows a live page."""
    return Session(
        open_browser=open_browser,
        interval=interval,
        host=host,
        port=port,
        cli=cli,
        log=log,
    )


_fork_hook = False


def _install_fork_hook():
    """Reconnect the child after fork."""
    global _fork_hook
    if _fork_hook:
        return
    if not hasattr(os, "register_at_fork"):
        return

    def after_in_child():
        current = get_session()
        if current is not None:
            current.after_fork()

    os.register_at_fork(after_in_child=after_in_child)
    _fork_hook = True
