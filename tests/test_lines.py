"""Check the line recorder."""

import time
import unittest

import pyopsy
from pyopsy.collect.lines import LineCollector


def _by_line(snapshot, name):
    for item in snapshot:
        if item["name"] == name:
            return {row["lineno"]: row for row in item["lines"]}
    return {}


class LineTests(unittest.TestCase):
    """Record line data for a marked function."""

    def test_hit_count_and_callee(self):
        """A marked function records lines. An unmarked callee has no rows."""

        def callee():
            return 1

        def marked():
            total = 0
            n = 2
            while n > 0:
                total += callee()
                n -= 1
            return total

        recorder = LineCollector()
        recorder.start()
        try:
            recorder.add_function(marked)
            recorder.enter(marked.__code__)
            marked()
            recorder.leave(marked.__code__)
            snapshot = recorder.snapshot()
        finally:
            recorder.stop()
        names = [item["name"] for item in snapshot]
        self.assertEqual(names, ["marked"])
        rows = _by_line(snapshot, "marked")
        add_line = marked.__code__.co_firstlineno + 4
        self.assertEqual(rows[add_line]["hits"], 2)
        self.assertGreater(rows[add_line]["time"], 0)

    def test_generator_pause(self):
        """A generator yield does not add the pause to the yielded line."""

        def stream():
            value = 1
            yield value
            value = 2
            yield value

        recorder = LineCollector()
        recorder.start()
        try:
            recorder.add_function(stream)
            iterator = stream()
            recorder.enter(stream.__code__)
            next(iterator)
            recorder.leave(stream.__code__)
            time.sleep(0.05)
            recorder.enter(stream.__code__)
            next(iterator)
            recorder.leave(stream.__code__)
            snapshot = recorder.snapshot()
        finally:
            recorder.stop()
        rows = _by_line(snapshot, "stream")
        yield_line = stream.__code__.co_firstlineno + 2
        self.assertIn(yield_line, rows)
        self.assertLess(rows[yield_line]["time"], 0.04)

    def test_hot_source_includes_body(self):
        """A marked function shows hits on the body, not only the decorator."""

        @pyopsy.profiler(lines=True)
        def hot(n):
            total = 0
            for index in range(n):
                total += index
            return total

        with pyopsy.session(open_browser=False, port=0, interval=0.2) as current:
            hot(50)
            snapshot = current.snapshot()
        items = [item for item in snapshot["line_data"] if item["name"] == "hot"]
        self.assertTrue(items)
        item = items[0]
        texts = [row["text"] for row in item["source"]]
        self.assertTrue(any("total += index" in text for text in texts))
        add_row = next(row for row in item["source"] if "total += index" in row["text"])
        hits = {row["lineno"]: row["hits"] for row in item["lines"]}
        self.assertGreater(hits.get(add_row["lineno"], 0), 0)
