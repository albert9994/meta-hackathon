"""Local test app for Dev 3 only: community routes without the Baseten smoke test."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.core import database
from backend.routes.community_routes import router as community_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield


app = FastAPI(title="VibeRide (Dev 3 test)", lifespan=lifespan)
app.include_router(community_router)
