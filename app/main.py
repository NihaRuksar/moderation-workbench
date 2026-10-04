from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.seed import seed
from app.routes import content


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once when the app starts: create tables and add policy v1 if needed
    seed()
    yield
    # Anything after yield would run when the app shuts down (nothing needed yet)


app = FastAPI(title="Content Moderation and Appeals Workbench", lifespan=lifespan)
app.include_router(content.router)

@app.get("/health")
def health():
    return {"status": "ok"}