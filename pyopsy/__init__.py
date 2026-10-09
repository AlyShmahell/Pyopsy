"""Pyopsy records wall time, memory, function data, and line data."""

from pyopsy.decorator import Pyopsy as profiler
from pyopsy.session import session

__all__ = ["profiler", "session"]
