import asyncio
import json
import logging
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from orchestrator import Orchestrator

app = FastAPI()
orch = Orchestrator()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = PROJECT_ROOT / "static"


# Suppress access logs for noisy health checks.
class HealthFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        msg = record.getMessage()
        return "/health" not in msg


logging.getLogger("uvicorn.access").addFilter(HealthFilter())

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunPayload(BaseModel):
    repo_url: str
    team_name: str
    leader_name: str
    retry_limit: int = 5


@app.post("/run-agent")
def run_agent(payload: RunPayload, background_tasks: BackgroundTasks):

    if orch.status.get("state") == "RUNNING":
        raise HTTPException(status_code=409, detail="Agent is already running")

    background_tasks.add_task(
        orch.run,
        payload.repo_url,
        payload.team_name,
        payload.leader_name,
        payload.retry_limit,
    )

    return {"status": "started"}


@app.get("/results")
def get_results():
    return orch.results.load()


@app.get("/timeline")
def get_timeline():
    return {"runs": orch.timeline, "steps": orch.status_mgr.timeline}


@app.get("/fixes")
def get_fixes():
    return orch.fixes


@app.get("/status")
def get_status():
    return orch.status_mgr.snapshot()


@app.get("/events")
async def stream_events(request: Request, last_id: int = 0):
    async def event_generator():
        cursor = int(last_id or 0)
        keepalive_ticks = 0
        while True:
            if await request.is_disconnected():
                break

            events = orch.event_bus.get_since(cursor)
            if events:
                for event in events:
                    cursor = max(cursor, event["id"])
                    payload = {
                        "type": event["type"],
                        "message": event["message"],
                        "timestamp": event["timestamp"],
                    }
                    yield (
                        f"id: {event['id']}\n"
                        f"event: {event['type']}\n"
                        f"data: {json.dumps(payload)}\n\n"
                    )
                keepalive_ticks = 0
            else:
                keepalive_ticks += 1
                if keepalive_ticks >= 15:
                    keepalive_ticks = 0
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.4)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/download-fixed-repo")
def download_fixed_repo():
    archive = Path("results/fixed_repo.zip")
    if not archive.exists():
        raise HTTPException(
            status_code=404, detail="Fixed repository archive not found"
        )
    return FileResponse(
        archive,
        filename="fixed_repo.zip",
        media_type="application/zip",
    )


if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/", include_in_schema=False)
    def serve_root():
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        # Preserve API routes and static-file direct hits.
        if full_path.startswith(
            (
                "run-agent",
                "results",
                "timeline",
                "fixes",
                "status",
                "events",
                "health",
                "download-fixed-repo",
            )
        ):
            raise HTTPException(status_code=404, detail="Not Found")

        candidate = FRONTEND_DIST / full_path
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
