import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core import database
from backend.routes.community_routes import router as community_router
from backend.routes.routing_routes import router as routing_router

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Creează tabelele SQLite și curăță hazardurile expirate la startup
    database.init_db()
    yield


app = FastAPI(
    title="VibeRide API",
    description="Mindful micro-mobility navigation copilot powered by Meta AI & Baseten",
    version="1.0.0",
    lifespan=lifespan,
)

# Permite apelurile din aplicația mobilă (Expo React Native de pe telefon/simulator)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Conectează rutele comunitare, auditul vizual, raportarea cursei și rutarea AI
app.include_router(community_router)
app.include_router(routing_router)


@app.get("/")
def health_check():
    return {
        "status": "online",
        "app": "VibeRide API",
        "model": "meta-models/muse-spark-open-1026 on Baseten",
    }