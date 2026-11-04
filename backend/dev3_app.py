"""
Dev 3 local test app: community routes + a demo fallback for the street scanner.

Run from the repo root:
    uvicorn backend.dev3_app:app --host 0.0.0.0 --port 8000 --reload

Local testing only. The real app (Dev 2 / main.py) just needs:
    from backend.routes.community_routes import router as community_router
    app.include_router(community_router)

Demo fallback: if Dev 1's vision agent is missing, slow or crashes, /api/vision/audit
returns a canned result (header `X-VibeRide-Demo-Fallback: 1`) so the phone UI can be
tested end to end. It is never stored on the hazard map. Disable it with
    VIBERIDE_DEMO_FALLBACK=0
"""

import logging
import os
from contextlib import asynccontextmanager

try:  # optional: load .env if python-dotenv is installed
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.core import database
from backend.routes.community_routes import router as community_router
from backend.routes.community_routes import vision_audit as real_vision_audit

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("viberide.dev3_app")

DEMO_FALLBACK = os.getenv("VIBERIDE_DEMO_FALLBACK", "1") != "0"

# Same keys and value style as the /api/vision/audit contract.
DEMO_AUDIT = {
    "bike_friendly": True,
    "surface": "smooth_asphalt",
    "shade_level": "high",
    "hazard_detected": "tram_tracks",
    "audio_alert": "Caution: tram track groove detected on the bike path ahead.",
}

# Agent failures that may be replaced by the demo result. Bad input (4xx) never is.
FALLBACK_STATUS_CODES = {502, 503, 504}


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()  # creates tables, purges expired hazards
    yield


app = FastAPI(title="VibeRide (Dev 3 test)", lifespan=lifespan)

# Handy if you also open the Expo web build in a browser; native Expo Go does not need it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Registered BEFORE the community router, so this path wins over the router's identical one.
# It calls the real handler (image validation, multipart + JSON, anonymous hazard storage)
# and only steps in when the AI side fails.
@app.post("/api/vision/audit", tags=["community"], operation_id="vision_audit_demo_fallback")
async def vision_audit_with_demo_fallback(request: Request):
    try:
        return await real_vision_audit(request)
    except HTTPException as exc:
        if DEMO_FALLBACK and exc.status_code in FALLBACK_STATUS_CODES:
            logger.warning(
                "Vision agent unavailable (HTTP %s: %s) - returning DEMO result, not stored.",
                exc.status_code,
                exc.detail,
            )
            return JSONResponse(DEMO_AUDIT, headers={"X-VibeRide-Demo-Fallback": "1"})
        raise


app.include_router(community_router)
try:
    from backend.routes.navigation_routes import router as navigation_router
    app.include_router(navigation_router)
    logger.info("Navigation routes loaded successfully.")
except Exception as exc:
    logger.warning("Could not load navigation routes: %s", exc)