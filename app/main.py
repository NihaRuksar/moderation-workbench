import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.logging_config import log_event
from app.seed import seed
from app.routes import appeals, content, pages, policy, queue
from app.logging_config import log_event, setup_logging

setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once when the app starts: create tables and add policy v1 if needed
    seed()
    yield
    # Anything after yield would run when the app shuts down (nothing needed yet)


app = FastAPI(title="Content Moderation and Appeals Workbench", lifespan=lifespan)
app.include_router(content.router)
app.include_router(queue.router)
app.include_router(appeals.router)
app.include_router(policy.router)
app.include_router(pages.router)
@app.middleware("http")
async def log_requests(request, call_next):
    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        log_event("http", "request_failed", logging.ERROR, method=request.method, path=request.url.path)
        raise
    log_event("http", "request", method=request.method, path=request.url.path, status=response.status_code, duration_ms=round((time.monotonic() - started) * 1000))
    return response
@app.get("/health")
def health():
    return {"status": "ok"}
@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/ui/queue")