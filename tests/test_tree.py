"""Check the call tree."""

import unittest

from pyopsy.collect.functions import function_key, merge_function_rows
from pyopsy.tree import build_tree


class TreeTests(unittest.TestCase):
    """Build a call tree from known callee lists."""

    def test_recursive_call(self):
        """A recursive call is one edge from a function to itself."""
        key = function_key("rec.py", 1, "walk")
        rows = [
            {
                "name": "walk",
                "filename": "rec.py",
                "firstlineno": 1,
                "ncalls": 3,
                "tottime": 0.1,
                "cumtime": 0.3,
                "callees": {
                    key: {"ncalls": 2, "tottime": 0.05, "cumtime": 0.2},
                },
            }
        ]
        tree = build_tree(rows)
        self.assertEqual(len(tree["nodes"]), 1)
        self.assertEqual(tree["edges"][0]["caller"], tree["edges"][0]["callee"])
        self.assertEqual(len(tree["icicle"]), 1)
        self.assertEqual(tree["icicle"][0]["children"][0]["name"], "walk")
        self.assertEqual(tree["icicle"][0]["mem"], 0)

    def test_two_roots(self):
        """Two functions with no shared caller stay two icicle roots."""
        rows = [
            {
                "name": "hot",
                "filename": "a.py",
                "firstlineno": 1,
                "ncalls": 1,
                "tottime": 0.1,
                "cumtime": 0.1,
                "callees": {},
            },
            {
                "name": "other",
                "filename": "a.py",
                "firstlineno": 8,
                "ncalls": 1,
                "tottime": 0.01,
                "cumtime": 0.01,
                "callees": {},
            },
        ]
        tree = build_tree(rows)
        names = sorted(item["name"] for item in tree["icicle"])
        self.assertEqual(names, ["hot", "other"])
        self.assertEqual(len(tree["icicle"]), 2)


class MergeTests(unittest.TestCase):
    """Merge function rows from two workers."""

    def test_two_workers_one_row(self):
        """Two worker snapshots merge into one function row."""
        row = {
            "name": "work",
            "filename": "a.py",
            "firstlineno": 4,
            "ncalls": 1,
            "tottime": 0.2,
            "cumtime": 0.5,
            "callees": {},
        }
        merged = merge_function_rows([[row], [dict(row)]])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["ncalls"], 2)
        self.assertAlmostEqual(merged[0]["tottime"], 0.4)
        self.assertAlmostEqual(merged[0]["cumtime"], 1.0)
