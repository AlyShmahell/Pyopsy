"""Check the file sink and the CLI screen."""

import io
import json
import os
import tempfile
import unittest

import pyopsy
from pyopsy.hub import PARENT_ENV
from pyopsy.view import CliView, FileView


class _Tty(io.StringIO):
    """A stream that reports as a TTY."""

    def isatty(self):
        """Return True so the CLI draws a screen."""
        return True


class FileViewTests(unittest.TestCase):
    """Append one JSON line per snapshot."""

    def test_two_samples(self):
        """A second sample appends a second line."""
        handle, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(handle)
        try:
            view = FileView()
            view.start(path)
            view.write({"session_time": 0.1, "wall": []})
            view.write({"session_time": 0.2, "wall": []})
            view.stop()
            with open(path, encoding="utf-8") as log:
                lines = [line for line in log.read().splitlines() if line]
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[1])["session_time"], 0.2)
        finally:
            os.remove(path)

    def test_session_child_skips_file(self):
        """A child snapshot path does not open the log file."""
        handle, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(handle)
        os.remove(path)
        os.environ[PARENT_ENV] = "0"
        try:
            with pyopsy.session(open_browser=False, port=0, log=path, interval=0.2):
                pass
            self.assertFalse(os.path.exists(path))
        finally:
            os.environ.pop(PARENT_ENV, None)
            if os.path.exists(path):
                os.remove(path)


class CliViewTests(unittest.TestCase):
    """Draw wall time and RSS on a TTY."""

    def test_screen_has_wall_and_rss(self):
        """A TTY-like stream receives wall time and RSS text."""
        stream = _Tty()
        view = CliView(stream=stream)
        view.draw(
            {
                "session_time": 1.25,
                "memory": {
                    "rss_text": "12.00MB",
                    "peak_rss_text": "13.00MB",
                    "traced_text": "1.00MB",
                },
                "wall": [
                    {
                        "name": "work",
                        "kind": "function",
                        "call_count": 2,
                        "wall_time": 0.01,
                        "total_wall_time": 0.02,
                        "mem_mean": 1024,
                        "mem_peak": 2048,
                    }
                ],
                "function_data": {
                    "rows": [
                        {
                            "name": "work",
                            "ncalls": 2,
                            "tottime": 0.01,
                            "cumtime": 0.02,
                        }
                    ]
                },
            }
        )
        text = stream.getvalue()
        self.assertIn("work", text)
        self.assertIn("12.00MB", text)
        self.assertIn("Runtime", text)
        self.assertIn("0.020 s", text)
        self.assertIn("Mem mean", text)
        self.assertIn("1.00KB", text)
        self.assertIn("2.00KB", text)
        self.assertIn("Wall time is the time of the marked function.", text)

    def test_second_draw_clears(self):
        """A second draw keeps one Session time header after the clear prefix."""
        stream = _Tty()
        view = CliView(stream=stream)
        sample = {
            "session_time": 1.0,
            "memory": {"rss_text": "1.00MB", "peak_rss_text": "1.00MB", "traced_text": "0.0B"},
            "wall": [],
            "function_data": {"rows": []},
        }
        view.draw(sample)
        sample["session_time"] = 2.0
        view.draw(sample)
        last = stream.getvalue().rsplit("\033[2J\033[H", 1)[-1]
        self.assertEqual(last.count("Session time"), 1)
