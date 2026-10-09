"""Move snapshots from a child process to the parent process."""

import json
import os
import socket
import threading

HUB_ENV = "PYOPSY_HUB"
PARENT_ENV = "PYOPSY_PARENT"


def hub_address():
    """Return the hub host and port from the environment."""
    raw = os.environ.get(HUB_ENV)
    if not raw:
        return None
    host, port_text = raw.rsplit(":", 1)
    return host, int(port_text)


def is_parent():
    """Return True when this process owns the hub."""
    parent = os.environ.get(PARENT_ENV)
    if parent is None:
        return True
    return int(parent) == os.getpid()


def mpi_rank():
    """Return the MPI rank when mpi4py is already loaded."""
    mpi_mod = sys_modules().get("mpi4py.MPI")
    if mpi_mod is not None:
        comm = getattr(mpi_mod, "COMM_WORLD", None)
        if comm is not None:
            return int(comm.Get_rank())
    package = sys_modules().get("mpi4py")
    if package is None:
        return None
    mpi = getattr(package, "MPI", None)
    if mpi is None:
        return None
    comm = getattr(mpi, "COMM_WORLD", None)
    if comm is None:
        return None
    return int(comm.Get_rank())


def sys_modules():
    """Return sys.modules.

    The hub does not import mpi4py.
    """
    import sys

    return sys.modules


def http_port(base=8765):
    """Return the page port for this process."""
    rank = mpi_rank()
    if rank is None:
        return base
    return base + rank


class Hub:
    """Accept snapshots from child processes."""

    def __init__(self, host="127.0.0.1"):
        self.host = host
        self.port = 0
        self._sock = None
        self._lock = threading.Lock()
        self._children = {}
        self._stop = threading.Event()
        self._worker = None

    def start(self):
        """Bind the hub and store the address in the environment."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, 0))
        self._sock.listen(32)
        self._sock.settimeout(0.5)
        self.port = self._sock.getsockname()[1]
        os.environ[HUB_ENV] = f"{self.host}:{self.port}"
        os.environ[PARENT_ENV] = str(os.getpid())
        self._stop.clear()
        self._worker = threading.Thread(
            target=self._accept,
            name="pyopsy-hub",
            daemon=True,
        )
        self._worker.start()
        return self.host, self.port

    def latest(self):
        """Return the latest snapshot from each child process."""
        with self._lock:
            return dict(self._children)

    def stop(self):
        """Close the hub socket."""
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._worker is not None:
            self._worker.join(timeout=1.0)
            self._worker = None

    def _accept(self):
        """Accept child connections until the hub stops."""
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except (TimeoutError, OSError):
                continue
            worker = threading.Thread(
                target=self._read,
                args=(conn,),
                name="pyopsy-hub-child",
                daemon=True,
            )
            worker.start()

    def _read(self, conn):
        """Read JSON lines from one child process."""
        buffer = b""
        try:
            conn.settimeout(1.0)
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(65536)
                except TimeoutError:
                    continue
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line:
                        continue
                    snapshot = json.loads(line.decode("utf-8"))
                    process_id = snapshot.get("process_id")
                    with self._lock:
                        self._children[process_id] = snapshot
        except (OSError, json.JSONDecodeError):
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass


class HubClient:
    """Send snapshots to the parent hub."""

    def __init__(self):
        self._sock = None

    def connect(self):
        """Connect to the hub address in the environment."""
        address = hub_address()
        if address is None:
            return False
        self.close()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect(address)
        except OSError:
            sock.close()
            return False
        self._sock = sock
        return True

    def send(self, snapshot):
        """Send one snapshot to the parent."""
        if self._sock is None:
            return
        payload = json.dumps(snapshot, separators=(",", ":")) + "\n"
        try:
            self._sock.sendall(payload.encode("utf-8"))
        except OSError:
            self.close()

    def close(self):
        """Close the hub connection."""
        if self._sock is None:
            return
        try:
            self._sock.close()
        except OSError:
            pass
        self._sock = None
