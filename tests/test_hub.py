"""Check the process hub."""

import unittest

from pyopsy.hub import Hub, HubClient, HUB_ENV, PARENT_ENV
import os


class HubTests(unittest.TestCase):
    """Move one child snapshot to the parent."""

    def test_parent_lists_child(self):
        """The hub stores a child snapshot. The parent lists that process."""
        hub = Hub()
        client = HubClient()
        try:
            hub.start()
            self.assertTrue(client.connect())
            child = {
                "process_id": 4242,
                "rank": 1,
                "port": 8766,
                "wall": [],
            }
            client.send(child)
            found = None
            for _ in range(50):
                latest = hub.latest()
                if 4242 in latest or "4242" in latest:
                    found = latest.get(4242, latest.get("4242"))
                    break
                import time

                time.sleep(0.02)
            self.assertIsNotNone(found)
            self.assertEqual(found["rank"], 1)
            processes = [
                {"process_id": os.getpid(), "label": "parent"},
                {"process_id": 4242, "label": "child", "snapshot": found},
            ]
            self.assertEqual(len(processes), 2)
        finally:
            client.close()
            hub.stop()
            os.environ.pop(HUB_ENV, None)
            os.environ.pop(PARENT_ENV, None)
