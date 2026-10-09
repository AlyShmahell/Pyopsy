"""Read wall time from each marked function."""

_marks = []


def register(mark):
    """Add a marked function to the registry.

    The wall collector reads this registry.
    """
    _marks.append(mark)


def marks():
    """Return the marked functions."""
    return list(_marks)


class WallCollector:
    """Read wall time from the marked-function registry."""

    def start(self):
        """Start the wall collector.

        The decorator records wall time.
        """
        return None

    def snapshot(self):
        """Return wall time for each marked function."""
        rows = []
        for mark in _marks:
            rows.append(mark.wall_row())
        return rows

    def stop(self):
        """Stop the wall collector.

        The marked functions keep their last wall time.
        """
        return None
