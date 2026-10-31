"""
VibeRide - Community, Safety & Feed routes (Developer 3).

Endpoints
    POST /api/vision/audit    street photo -> spatial safety report (Dev 1 vision agent)
    POST /api/ride/finish     ride stats + recap + quiz + badge (Dev 1 storyteller agent)
    GET  /api/feed            community feed
    POST /api/feed            share a ride photo to the feed        (additive to the contract)
    GET  /api/leaderboard     private crew ranking
    GET  /api/hazards         anonymous open-data hazard map          (additive to the contract)

Contract with Developer 1 (agents). Each callable may be sync or async and may
return a dict or a JSON string:

    backend.agents.vision_inspector.inspect_street_image(image_base64: str, mime_type: str) -> dict
    backend.agents.storyteller.generate_ride_story(route_title: str, distance_km: float,
                                                   duration_min: float, vibe_preset: str) -> dict

If the names differ, change only the two constants below.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import importlib
import inspect
import json
import logging
import re
import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.core import database as db

logger = logging.getLogger("viberide.community")

router = APIRouter(prefix="/api", tags=["community"])

# --- Dev 1 integration points ------------------------------------------------
VISION_AGENT = ("backend.agents.vision_inspector", "inspect_street_image")
STORY_AGENT = ("backend.agents.storyteller", "generate_ride_story")

VISION_TIMEOUT_SEC = 25.0
STORY_TIMEOUT_SEC = 20.0

# --- Limits -------------------------------------------------------------------
MAX_AUDIT_IMAGE_BYTES = 6 * 1024 * 1024
MAX_FEED_IMAGE_BYTES = 2_500_000
MAX_REQUEST_BYTES = 9 * 1024 * 1024
_DATA_URI_RE = re.compile(r"^data:image/[a-zA-Z0-9.+-]+;base64,", re.IGNORECASE)


# =============================================================================
# Schemas (Pydantic v2) - key names match Section 4 of the blueprint
# =============================================================================
class RideFinishRequest(BaseModel):
    user_name: str = Field(min_length=1, max_length=40)
    crew_code: Optional[str] = Field(default=None, max_length=40)
    route_title: str = Field(min_length=1, max_length=120)
    distance_km: float = Field(gt=0, le=500)
    duration_min: float = Field(gt=0, le=1440)
    vibe_preset: str = Field(default="green_shady", max_length=40)

    @field_validator("user_name", "route_title", "vibe_preset", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @field_validator("crew_code")
    @classmethod
    def _crew(cls, v: Optional[str]) -> Optional[str]:
        return db.normalize_crew_code(v)  # raises ValueError -> 422


class RideStats(BaseModel):
    distance_km: float
    duration_min: float
    avg_speed_kmh: float


class Quiz(BaseModel):
    question: str = Field(min_length=1)
    options: list[str] = Field(min_length=3, max_length=3)
    correct_index: int = Field(ge=0, le=2)
    fun_fact: str = ""


class Badge(BaseModel):
    title: str = Field(min_length=1)
    lore: str = ""


class RideFinishResponse(BaseModel):
    stats: RideStats
    recap_text: str
    quiz: Quiz
    badge: Badge


class VisionAuditResponse(BaseModel):
    bike_friendly: bool
    surface: str
    shade_level: str
    hazard_detected: Optional[str] = None
    audio_alert: str


class VisionAuditJSON(BaseModel):
    image_base64: str = Field(min_length=16)
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lon: Optional[float] = Field(default=None, ge=-180, le=180)


class FeedPostRequest(BaseModel):
    user_name: str = Field(min_length=1, max_length=40)
    caption: str = Field(default="", max_length=280)
    image_base64: Optional[str] = None
    badge_title: Optional[str] = Field(default=None, max_length=80)
    stats: dict[str, Any] = Field(default_factory=dict)
    crew_code: Optional[str] = Field(default=None, max_length=40)

    @field_validator("user_name", "caption", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @field_validator("crew_code")
    @classmethod
    def _crew(cls, v: Optional[str]) -> Optional[str]:
        return db.normalize_crew_code(v)

    @field_validator("stats")
    @classmethod
    def _small_stats(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v, default=str)) > 1000:
            raise ValueError("stats payload too large")
        return v


class FeedPost(BaseModel):
    id: int
    user_name: str
    caption: str
    image_base64: Optional[str] = None
    badge_title: Optional[str] = None
    stats: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class LeaderboardEntry(BaseModel):
    rank: int
    user_name: str
    total_km: float
    ride_count: int
    badge_title: Optional[str] = None
    badge_lore: Optional[str] = None


class HazardOut(BaseModel):
    id: int
    lat: float
    lon: float
    hazard_type: str
    surface: Optional[str] = None
    shade_level: Optional[str] = None
    audio_alert: Optional[str] = None
    created_at: str


# =============================================================================
# Helpers
# =============================================================================
class AgentUnavailable(RuntimeError):
    """Developer 1's agent module/function is missing or not importable yet."""


async def _call_agent(target: tuple[str, str], timeout: float, *args: Any) -> dict[str, Any]:
    module_name, func_name = target
    try:
        func = getattr(importlib.import_module(module_name), func_name)
    except (ImportError, AttributeError) as exc:
        raise AgentUnavailable(f"{module_name}.{func_name} is not available: {exc}") from exc

    if inspect.iscoroutinefunction(func):
        result = await asyncio.wait_for(func(*args), timeout)
    else:
        result = await asyncio.wait_for(asyncio.to_thread(func, *args), timeout)
        if inspect.isawaitable(result):
            result = await asyncio.wait_for(result, timeout)

    if isinstance(result, (str, bytes)):
        try:
            result = json.loads(result)
        except ValueError as exc:
            raise ValueError("agent returned text that is not valid JSON") from exc
    if not isinstance(result, dict):
        raise ValueError(f"agent returned {type(result).__name__}, expected a JSON object")
    return result


async def _db(func, /, *args, **kwargs):
    """Run a blocking SQLite call off the event loop and map DB errors to HTTP 503."""
    try:
        return await asyncio.to_thread(func, *args, **kwargs)
    except sqlite3.Error as exc:
        logger.exception("Database error in %s", getattr(func, "__name__", func))
        raise HTTPException(status_code=503, detail="Community database is temporarily unavailable.") from exc


def _sniff_image_mime(data: bytes) -> Optional[str]:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _decode_image_b64(raw: str, max_bytes: int) -> tuple[bytes, str]:
    """Strip an optional data-URI prefix, decode, size-check and sniff the image type."""
    cleaned = _DATA_URI_RE.sub("", raw.strip())
    cleaned = re.sub(r"\s+", "", cleaned)
    if len(cleaned) > max_bytes * 4 // 3 + 8:
        raise HTTPException(status_code=413, detail="Image is too large.")
    try:
        data = base64.b64decode(cleaned, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="image_base64 is not valid base64.") from exc
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="Image is too large.")
    mime = _sniff_image_mime(data)
    if mime is None:
        raise HTTPException(status_code=415, detail="Unsupported image type. Use JPEG, PNG or WebP.")
    return data, mime


def _parse_coord(value: Any, low: float, high: float, name: str) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{name} must be a number.") from exc
    if not (low <= number <= high):
        raise HTTPException(status_code=422, detail=f"{name} is out of range.")
    return number


def _clean_hazard(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in {"", "none", "null", "n/a", "false"} else text


def _normalize_vision(raw: dict[str, Any]) -> VisionAuditResponse:
    """Coerce the model's JSON into the strict /api/vision/audit contract."""
    if "bike_friendly" not in raw:
        raise ValueError("vision agent output is missing 'bike_friendly'")
    hazard = _clean_hazard(raw.get("hazard_detected"))
    alert = str(raw.get("audio_alert") or "").strip()
    if not alert:
        alert = (
            f"Caution: {hazard.replace('_', ' ')} ahead. Slow down."
            if hazard else "Path looks clear. Ride mindfully."
        )
    return VisionAuditResponse(
        bike_friendly=raw["bike_friendly"],
        surface=str(raw.get("surface") or "unknown"),
        shade_level=str(raw.get("shade_level") or "unknown"),
        hazard_detected=hazard,
        audio_alert=alert,
    )


_FALLBACK_BADGES = {
    "green_shady": ("🌿 The Shade Cartographer", "Chose leafy canopies over loud boulevards and mapped the calm side of the city."),
    "historic_chill": ("🏛️ The Chill Chronicler", "Rolled past old facades at a relaxed pace, reading the city like a slow history book."),
    "pitstop": ("☕ The Cortado Commuter", "Turned a simple trip into a tour of the city's best pit stops."),
}
_DEFAULT_BADGE = ("🧘 Zen Drifter", "Glided through the city at a calm pace, far from the noise.")


def _fallback_story(req: RideFinishRequest) -> dict[str, Any]:
    title, lore = _FALLBACK_BADGES.get(req.vibe_preset, _DEFAULT_BADGE)
    return {
        "recap_text": (
            f"You picked calm over chaos on \"{req.route_title}\". "
            f"{req.distance_km:g} km of low-stress riding with zero horn-honking required."
        ),
        "quiz": {
            "question": "Which kind of street is usually the calmest for a rider?",
            "options": ["A tree-lined residential street", "A six-lane boulevard", "A highway on-ramp"],
            "correct_index": 0,
            "fun_fact": "Tree-lined side streets usually mean less traffic noise and more shade than main arteries.",
        },
        "badge": {"title": title, "lore": lore},
    }


def _merge_story(req: RideFinishRequest, stats: RideStats, raw: dict[str, Any]) -> RideFinishResponse:
    """Validate the agent's story; replace any invalid part with the fallback for that part."""
    fallback = _fallback_story(req)
    recap = str(raw.get("recap_text") or "").strip() or fallback["recap_text"]
    try:
        quiz = Quiz.model_validate(raw.get("quiz"))
    except ValidationError:
        logger.warning("Storyteller returned an invalid quiz; using fallback quiz.")
        quiz = Quiz.model_validate(fallback["quiz"])
    try:
        badge = Badge.model_validate(raw.get("badge"))
    except ValidationError:
        logger.warning("Storyteller returned an invalid badge; using fallback badge.")
        badge = Badge.model_validate(fallback["badge"])
    return RideFinishResponse(stats=stats, recap_text=recap, quiz=quiz, badge=badge)


async def _read_audit_payload(request: Request) -> tuple[str, str, Optional[float], Optional[float]]:
    """Accept multipart (file) or JSON (image_base64). Returns (b64, mime, lat, lon)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="Request body is too large.")

    content_type = (request.headers.get("content-type") or "").lower()

    if content_type.startswith("multipart/form-data"):
        try:
            form = await request.form()
        except Exception as exc:  # malformed multipart / missing python-multipart
            raise HTTPException(status_code=400, detail="Could not read multipart form data.") from exc
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(status_code=422, detail="Multipart field 'file' (image) is required.")
        data = await upload.read(MAX_AUDIT_IMAGE_BYTES + 1)
        if len(data) > MAX_AUDIT_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Image is too large.")
        if not data:
            raise HTTPException(status_code=422, detail="Uploaded image is empty.")
        mime = _sniff_image_mime(data)
        if mime is None:
            raise HTTPException(status_code=415, detail="Unsupported image type. Use JPEG, PNG or WebP.")
        lat = _parse_coord(form.get("lat"), -90, 90, "lat")
        lon = _parse_coord(form.get("lon"), -180, 180, "lon")
        return base64.b64encode(data).decode("ascii"), mime, lat, lon

    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Send multipart 'file' or JSON with 'image_base64'.") from exc
    try:
        payload = VisionAuditJSON.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json(include_url=False, include_input=False))) from exc
    data, mime = _decode_image_b64(payload.image_base64, MAX_AUDIT_IMAGE_BYTES)
    return base64.b64encode(data).decode("ascii"), mime, payload.lat, payload.lon


# =============================================================================
# Routes
# =============================================================================
@router.post("/vision/audit", response_model=VisionAuditResponse)
async def vision_audit(request: Request) -> VisionAuditResponse:
    """
    Spatial Safety Sensor. Optional ``lat``/``lon`` (form fields or JSON keys) are
    only sent when the rider opts in to share the hazard anonymously.
    """
    image_b64, mime, lat, lon = await _read_audit_payload(request)

    try:
        raw = await _call_agent(VISION_AGENT, VISION_TIMEOUT_SEC, image_b64, mime)
        result = _normalize_vision(raw)
    except AgentUnavailable as exc:
        logger.error("%s", exc)
        raise HTTPException(status_code=503, detail="Street scanner is not available right now.") from exc
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Street scanner timed out. Try again.") from exc
    except (ValueError, ValidationError) as exc:
        logger.warning("Invalid vision agent output: %s", exc)
        raise HTTPException(status_code=502, detail="Street scanner returned an unreadable result.") from exc
    except Exception as exc:  # model/network failure inside Dev 1's code
        logger.exception("Vision agent failed")
        raise HTTPException(status_code=502, detail="Street scanner failed. Try again.") from exc

    if result.hazard_detected and lat is not None and lon is not None:
        try:
            await _db(
                db.add_hazard_report,
                lat=lat, lon=lon, hazard_type=result.hazard_detected,
                surface=result.surface, shade_level=result.shade_level, audio_alert=result.audio_alert,
            )
        except HTTPException:
            logger.warning("Hazard not stored (database unavailable); audit result still returned.")
    return result


@router.post("/ride/finish", response_model=RideFinishResponse)
async def finish_ride(req: RideFinishRequest) -> RideFinishResponse:
    """Compute stats, ask the storyteller for recap/quiz/badge, log aggregate km only."""
    stats = RideStats(
        distance_km=round(req.distance_km, 2),
        duration_min=round(req.duration_min, 1),
        avg_speed_kmh=round(req.distance_km / (req.duration_min / 60.0), 1),
    )

    try:
        raw = await _call_agent(
            STORY_AGENT, STORY_TIMEOUT_SEC,
            req.route_title, req.distance_km, req.duration_min, req.vibe_preset,
        )
    except AgentUnavailable as exc:
        logger.warning("%s - using built-in story.", exc)
        raw = {}
    except asyncio.TimeoutError:
        logger.warning("Storyteller timed out - using built-in story.")
        raw = {}
    except Exception:
        logger.exception("Storyteller failed - using built-in story.")
        raw = {}

    response = _merge_story(req, stats, raw)

    if req.crew_code:  # solo riders: nothing is stored at all
        try:
            await _db(
                db.record_ride,
                user_name=req.user_name, crew_code=req.crew_code,
                distance_km=req.distance_km, route_title=req.route_title,
                badge_title=response.badge.title, badge_lore=response.badge.lore,
            )
        except HTTPException:
            logger.warning("Ride not logged to crew (database unavailable); stats still returned.")
    return response


@router.post("/feed", status_code=201)
async def create_feed_post(post: FeedPostRequest) -> dict[str, int]:
    """Share a ride photo/caption. With ``crew_code`` the post is visible to that crew only."""
    image_b64: Optional[str] = None
    if post.image_base64:
        data, _mime = _decode_image_b64(post.image_base64, MAX_FEED_IMAGE_BYTES)
        image_b64 = base64.b64encode(data).decode("ascii")
    if not post.caption and image_b64 is None:
        raise HTTPException(status_code=422, detail="A post needs a caption or a photo.")

    post_id = await _db(
        db.add_feed_post,
        user_name=post.user_name, caption=post.caption, image_base64=image_b64,
        badge_title=post.badge_title, stats=post.stats, crew_code=post.crew_code,
    )
    return {"id": post_id}


@router.get("/feed", response_model=list[FeedPost])
async def get_feed(
    crew: Optional[str] = Query(default=None, max_length=40),
    limit: int = Query(default=20, ge=1, le=db.MAX_FEED_LIMIT),
    before_id: Optional[int] = Query(default=None, ge=1),
) -> list[dict[str, Any]]:
    try:
        crew_code = db.normalize_crew_code(crew)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await _db(db.list_feed, crew_code, limit, before_id)


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
async def get_leaderboard(
    scope: str = Query(default="weekly", pattern="^(weekly|all_time)$"),
    crew: str = Query(..., min_length=2, max_length=40),
) -> list[dict[str, Any]]:
    """Private crew ranking by kilometres ('Mindful Miles'), with each rider's current badge."""
    try:
        crew_code = db.normalize_crew_code(crew)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if crew_code is None:
        raise HTTPException(status_code=422, detail="crew is required.")
    return await _db(db.get_leaderboard, crew_code, scope)


@router.get("/hazards", response_model=list[HazardOut])
async def get_hazards(
    min_lat: Optional[float] = Query(default=None, ge=-90, le=90),
    max_lat: Optional[float] = Query(default=None, ge=-90, le=90),
    min_lon: Optional[float] = Query(default=None, ge=-180, le=180),
    max_lon: Optional[float] = Query(default=None, ge=-180, le=180),
    limit: int = Query(default=200, ge=1, le=db.MAX_HAZARD_LIMIT),
) -> list[dict[str, Any]]:
    """Anonymous, auto-expiring hazards for the map layer (optionally inside a bounding box)."""
    return await _db(
        db.list_hazards,
        min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon, limit=limit,
    )
