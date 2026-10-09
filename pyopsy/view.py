"""Draw a live stats screen and append snapshots to a file."""

import json
import math
import sys

_CLEAR = "\033[2J\033[H"
_ALT_ON = "\033[?1049h"
_ALT_OFF = "\033[?1049l"


def format_bytes(count):
    """Return a short byte string.

    A zero count returns 0.0B.
    """
    if count <= 0:
        return "0.0B"
    units = ["B", "KB", "MB", "GB", "TB"]
    index = min(int(math.floor(math.log(count, 1024))), len(units) - 1)
    value = count / (1024 ** index)
    return f"{value:.2f}{units[index]}"


def _fmt_time(value):
    """Return a short time string."""
    if value is None:
        return "0.000 s"
    if value < 0.001:
        return f"{value * 1e6:.0f} us"
    return f"{value:.3f} s"


class CliView:
    """Redraw session stats on a terminal.

    The view writes to stderr.
    The view skips the screen when stderr is not a TTY.
    """

    def __init__(self, stream=None):
        self.stream = sys.stderr if stream is None else stream
        self._open = False

    def start(self):
        """Open the alternate screen."""
        if not self._tty():
            return
        self.stream.write(_ALT_ON + _CLEAR)
        self.stream.flush()
        self._open = True

    def stop(self):
        """Leave the alternate screen."""
        if not self._open:
            return
        self.stream.write(_ALT_OFF)
        self.stream.flush()
        self._open = False

    def draw(self, snapshot):
        """Draw one screen from one snapshot."""
        if not self._tty():
            return
        memory = snapshot.get("memory") or {}
        wall = snapshot.get("wall") or []
        runtime = snapshot.get("runtime")
        if runtime is None:
            runtime = sum((row.get("total_wall_time") or 0) for row in wall)
        rows = ((snapshot.get("function_data") or {}).get("rows")) or []
        rows = sorted(rows, key=lambda row: row.get("cumtime", 0), reverse=True)[:12]
        lines = [
            "Pyopsy",
            f"Session time  {_fmt_time(snapshot.get('session_time'))}",
            f"Runtime       {_fmt_time(runtime)}",
            f"RSS           {memory.get('rss_text', '0.0B')}",
            f"Peak RSS      {memory.get('peak_rss_text', '0.0B')}",
            f"Traced memory {memory.get('traced_text', '0.0B')}",
            "",
            "Marked functions",
            f"{'Name':<16} {'Kind':<14} {'Calls':>5} {'Wall':>10} {'Total':>10} {'Mem mean':>10} {'Mem peak':>10}",
        ]
        if not wall:
            lines.append("Mark a function with @pyopsy.profiler.")
        for row in wall:
            lines.append(
                f"{row['name']:<16} {row['kind']:<14} {row['call_count']:>5} "
                f"{_fmt_time(row['wall_time']):>10} {_fmt_time(row['total_wall_time']):>10} "
                f"{format_bytes(row.get('mem_mean') or 0):>10} {format_bytes(row.get('mem_peak') or 0):>10}"
            )
        lines.extend(
            [
                "",
                "Function data",
                f"{'Name':<16} {'Calls':>5} {'Own time':>10} {'Inclusive':>10} {'Mem mean':>10} {'Mem peak':>10}",
            ]
        )
        if not rows:
            lines.append("Function data appears after the first call.")
        for row in rows:
            lines.append(
                f"{row['name']:<16} {row['ncalls']:>5} "
                f"{_fmt_time(row['tottime']):>10} {_fmt_time(row['cumtime']):>10} "
                f"{format_bytes(row.get('mem_mean') or 0):>10} {format_bytes(row.get('mem_peak') or 0):>10}"
            )
        lines.append("")
        lines.append("Wall time is the time of the marked function.")
        self.stream.write(_CLEAR + "\n".join(lines) + "\n")
        self.stream.flush()

    def _tty(self):
        """Return True when the stream is a terminal."""
        return hasattr(self.stream, "isatty") and self.stream.isatty()


class FileView:
    """Append snapshots to a JSONL file."""

    def __init__(self):
        self._handle = None

    def start(self, path):
        """Open the path for append."""
        self._handle = open(path, "a", encoding="utf-8")

    def write(self, snapshot):
        """Write one snapshot as one JSON line."""
        if self._handle is None:
            return
        self._handle.write(json.dumps(snapshot, separators=(",", ":")) + "\n")
        self._handle.flush()

    def stop(self):
        """Close the file."""
        if self._handle is None:
            return
        self._handle.close()
        self._handle = None
