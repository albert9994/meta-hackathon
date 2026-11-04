import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from backend.agents.vibe_planner import VibePlannerAgent
from backend.agents.voice_copilot import VoiceCopilotAgent, VoiceCopilotResponse
from backend.core.routing import calculate_bike_route

logger = logging.getLogger("viberide.routing_routes")
router = APIRouter(prefix="/api/route", tags=["routing"])


# ============================================================================
# 1. ROUTE PLANNING CONTRACTS & ENDPOINT
# ============================================================================

class RouteRequest(BaseModel):
    user_prompt: str = Field(
        ...,
        min_length=1,
        description="Ride request, e.g. 'Chill sunset ride from UPB Regie to Carol Park'",
    )
    vibe_preset: Optional[str] = Field(default=None)
    city: str = Field(default="Bucharest")
    time_of_day: str = Field(default="sunset")
    wind_direction_deg: Optional[int] = Field(default=270)


@router.post("/plan")
async def plan_and_calculate_route(req: RouteRequest) -> Dict[str, Any]:
    """
    1. Genereaza traseul mindful & ancorele cu Meta Muse Spark (vibe_planner).
    2. Calculeaza geometria GeoJSON detaliata prin motorul GIS (routing).
    3. Returneaza pachetul complet pentru aplicatia mobila (harta + audio + cues).
    """
    prompt = (
        f"[Vibe: {req.vibe_preset}] {req.user_prompt}" if req.vibe_preset else req.user_prompt
    )

    # generate_plan e sincron (client OpenAI) -> il rulam in threadpool ca sa nu blocam event loop-ul.
    vibe_plan = await run_in_threadpool(
        VibePlannerAgent().generate_plan,
        user_prompt=prompt,
        city=req.city,
        wind_direction_deg=req.wind_direction_deg,
        time_of_day=req.time_of_day,
    )

    try:
        geojson = await calculate_bike_route(vibe_plan.to_geojson_coordinates())
    except Exception as exc:
        logger.warning("Routing failed for AI plan (%s). Retrying with fallback plan.", exc)
        vibe_plan = VibePlannerAgent.build_fallback_plan(user_prompt=req.user_prompt, city=req.city)
        try:
            geojson = await calculate_bike_route(vibe_plan.to_geojson_coordinates())
        except Exception as exc2:
            logger.error("Fallback routing failed: %s", exc2)
            raise HTTPException(status_code=502, detail=f"Routing unavailable: {exc2}")

    coords = geojson["features"][0]["geometry"]["coordinates"]
    if len(coords) < 2:
        raise HTTPException(status_code=502, detail="Routing returned an empty geometry.")

    # Injectam metadatele Zen direct in proprietatile rutei
    props = geojson["features"][0]["properties"]
    props["vibe_title"] = vibe_plan.vibe_title
    props["audio_intro"] = vibe_plan.audio_intro
    props["avoid_tags"] = vibe_plan.avoid_tags
    props["chill_cues"] = [cue.model_dump() for cue in vibe_plan.chill_cues]
    props["origin_name"] = vibe_plan.origin.name
    props["destination_name"] = vibe_plan.destination.name

    # GeoJSON standard ([lon, lat]) + planul separat (lat/lon) pentru markeri
    return {"geojson": geojson, "vibe_plan": vibe_plan.model_dump()}


# ============================================================================
# 2. VOICE COPILOT CONTRACTS & ENDPOINT
# ============================================================================

class CopilotVoiceRequest(BaseModel):
    user_utterance: str = Field(
        ...,
        description="Transcript of what the rider said hands-free",
        json_schema_extra={
            "example": "There's intense headwind and heavy traffic here, find me a quiet alley."
        },
    )
    current_street: Optional[str] = Field(
        default="moving on route",
        description="Current street name or contextual location",
    )


@router.post("/copilot", response_model=VoiceCopilotResponse)
async def copilot_voice_endpoint(req: CopilotVoiceRequest) -> VoiceCopilotResponse:
    """
    Interpreteaza comanda vocala a riderului in timp real, clasifica intentia
    si genereaza raspunsul audio zen si actiunea de rerutare/hazard prin Meta Muse Spark.
    """
    try:
        agent = VoiceCopilotAgent()
        return await run_in_threadpool(
            agent.process_voice_input,
            user_utterance=req.user_utterance,
            current_street=req.current_street,
        )
    except Exception as exc:
        logger.error("Error in /api/route/copilot: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))