"""Temporal worker placeholder.

The first implemented slice is synchronous through FastAPI so contracts can
settle before durable execution is wired in. Temporal will own ingestion,
review waits, import batches, and Drive action execution.
"""


async def run_worker() -> None:
    raise NotImplementedError("Temporal worker registration is planned for Phase 1 hardening.")
