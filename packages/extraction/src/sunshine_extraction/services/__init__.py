"""Pipeline service boundaries used by CLIs and LangGraph nodes.

The current implementation delegates to the legacy sample pipeline module.
Keeping these imports behind focused service modules lets us move the actual
implementations out of that legacy module incrementally.
"""
