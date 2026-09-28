"""Sample FastAPI service for DataRobot's Workload API.

Run locally:      uvicorn app.main:app --reload
Deploy:            see README.md (dr workload config / dr workload up)

The one non-obvious piece here is ROOT_PATH: the DataRobot edge gateway serves
this workload at a path prefix (/api/v2/endpoints/workloads/<workload-id>/)
but strips that prefix before the request reaches the container. FastAPI's
`root_path` tells Starlette to keep routing on the stripped path (so inbound
requests still match) while prepending the prefix to every URL it emits
(OpenAPI schema, docs UI, redirects) so the browser stays inside the prefix.
DataRobot auto-injects WORKLOAD_ID into every workload container, so the
prefix is derived at startup with no extra configuration required.
"""

import logging
import os
import socket

from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fastapi-sample")

WORKLOAD_ID = os.getenv("WORKLOAD_ID")
ROOT_PATH = f"/api/v2/endpoints/workloads/{WORKLOAD_ID}" if WORKLOAD_ID else ""

logger.info("Starting with WORKLOAD_ID=%s ROOT_PATH=%r", WORKLOAD_ID, ROOT_PATH)

app = FastAPI(title="DataRobot FastAPI Sample", root_path=ROOT_PATH)


class EchoRequest(BaseModel):
    message: str
    times: int = 1


class EchoResponse(BaseModel):
    echoed: list[str]
    hostname: str


@app.get("/healthz")
def healthz() -> dict:
    """Liveness/readiness target. Cheap, dependency-free, never gated on auth.

    Probes hit the container directly (bypassing the edge), so this must
    respond regardless of anything else going on in the app.
    """
    return {"status": "ok"}


@app.get("/")
def index() -> dict:
    """Service identity — confirms which replica answered and that the
    sub-path prefix resolved correctly."""
    return {
        "service": "fastapi-sample",
        "workload_id": WORKLOAD_ID,
        "root_path": ROOT_PATH,
        "hostname": socket.gethostname(),
    }


@app.post("/echo", response_model=EchoResponse)
def echo(payload: EchoRequest) -> EchoResponse:
    """Trivial POST endpoint demonstrating request validation."""
    return EchoResponse(
        echoed=[payload.message] * payload.times,
        hostname=socket.gethostname(),
    )
