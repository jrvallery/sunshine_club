from fastapi import FastAPI

from sunshine_core.models import FoundationRunRequest, ThinSliceOutcome
from sunshine_core.repository import InMemoryFoundationRepository
from sunshine_core.thin_slice import run_foundation_slice

app = FastAPI(title="Sunshine Club API")
repository = InMemoryFoundationRepository()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/admin/foundation/run-staged-file", response_model=ThinSliceOutcome)
def run_staged_file(request: FoundationRunRequest) -> ThinSliceOutcome:
    return run_foundation_slice(request, repository)
