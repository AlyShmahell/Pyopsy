"""Check a session snapshot."""

import threading
import time
import unittest

import pyopsy
from pyopsy.collect.functions import FunctionCollector


@pyopsy.profiler
def add(value):
    return value + 1


class SessionTests(unittest.TestCase):
    """Keep wall time beside function data."""

    def test_kind_not_copied(self):
        """The decorator does not write wall time into function data."""

        @pyopsy.profiler
        def numbers(count):
            for index in range(count):
                yield index

        with pyopsy.session(open_browser=False, port=0, interval=0.2) as current:
            list(numbers(4))
            add(2)
            snapshot = current.snapshot()
        self.assertEqual(numbers.wall_row()["kind"], "generator")
        for row in snapshot["function_data"]["rows"]:
            self.assertNotIn("wall_time", row)
            self.assertNotIn("kind", row)

    def test_worker_rows_merge(self):
        """Two workers that call one function become one row."""
        collector = FunctionCollector()

        def work():
            return sum(range(2000))

        collector.start()
        try:
            workers = [
                threading.Thread(target=work),
                threading.Thread(target=work),
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
            rows = collector.snapshot()
        finally:
            collector.stop()
        matches = [row for row in rows if row["name"] == "work"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["ncalls"], 2)

    def test_function_data_skips_stdlib_wait(self):
        """The page rows do not include wait from threading.py."""

        @pyopsy.profiler
        def work():
            return sum(range(2000))

        with pyopsy.session(open_browser=False, port=0, interval=0.1) as current:
            work()
            time.sleep(0.25)
            snapshot = current.snapshot()
        for row in snapshot["function_data"]["rows"]:
            if row["name"] == "wait":
                self.assertNotIn("threading.py", row["filename"])

    def test_allocating_function_records_mem(self):
        """A large allocation raises mem on the function row and the icicle."""

        @pyopsy.profiler
        def grow():
            return bytearray(256 * 1024)

        with pyopsy.session(open_browser=False, port=0, interval=0.2) as current:
            grow()
            snapshot = current.snapshot()
        self.assertGreater(grow.wall_row()["mem_peak"], 0)
        rows = [row for row in snapshot["function_data"]["rows"] if row["name"] == "grow"]
        self.assertTrue(rows)
        self.assertGreater(rows[0]["mem"], 0)
        self.assertGreater(rows[0]["mem_peak"], 0)
        nodes = [
            item
            for item in snapshot["function_data"]["tree"]["icicle"]
            if item["name"] == "grow"
        ]
        self.assertTrue(nodes)
        self.assertGreater(nodes[0]["mem"], 0)
