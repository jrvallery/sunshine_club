"""Application entry point for the Sunshine Club dashboard API.

Route handlers live in ``sunshine_api.routers`` and shared orchestration
helpers live in ``sunshine_api.services``. Keeping this file small makes the
HTTP surface easy to scan and prevents route, persistence, and run-execution
logic from drifting back into one module.
"""

from fastapi import FastAPI

from sunshine_api.routers import files, health, pipeline, review, runs, semantic


def create_app() -> FastAPI:
    """Create the FastAPI application and register all API routers."""
    app = FastAPI(title="Sunshine Club API")
    app.include_router(health.router)
    app.include_router(pipeline.router)
    app.include_router(review.router)
    app.include_router(files.router)
    app.include_router(runs.router)
    app.include_router(semantic.router)
    return app


app = create_app()
