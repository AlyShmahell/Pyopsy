"""Check the marked function without a session."""

import asyncio
import json
import unittest

import pyopsy


class DecoratorTests(unittest.TestCase):
    """Record wall time when no session is open."""

    def test_str_json(self):
        """str returns wall time and memory JSON after a call."""

        @pyopsy.profiler
        def work(count):
            return sum(range(count))

        work(1000)
        payload = json.loads(str(work))
        self.assertEqual(payload["func"], "work")
        self.assertEqual(payload["kind"], "function")
        self.assertIn("mem_mean", payload)
        self.assertIn("mem_peak", payload)
        self.assertGreaterEqual(payload["perfc"], 0)

    def test_kind_stays_in_wall(self):
        """A generator and an async function set kind on wall time."""

        @pyopsy.profiler
        def numbers(count):
            for index in range(count):
                yield index

        @pyopsy.profiler
        async def square(value):
            return value * value

        list(numbers(3))
        asyncio.run(square(4))
        self.assertEqual(numbers.wall_row()["kind"], "generator")
        self.assertEqual(square.wall_row()["kind"], "async_function")
        self.assertNotIn("kind", {"ncalls": 1, "tottime": 0.1, "cumtime": 0.1})
        self.assertNotIn("wall_time", numbers.profile)

    def test_str_memory_in_session(self):
        """str records traced memory while a session is open."""

        @pyopsy.profiler
        def work():
            return bytearray(64 * 1024)

        with pyopsy.session(open_browser=False, port=0, interval=0.2):
            work()
            payload = json.loads(str(work))
        self.assertNotEqual(payload["mem_peak"], "0.0B")
        self.assertGreater(work.wall_row()["mem_peak"], 0)
