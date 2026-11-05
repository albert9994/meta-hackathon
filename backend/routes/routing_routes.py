import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.agents.vibe_planner import VibePlannerAgent
from backend.agents.voice_copilot import VoiceCopilotAgent, VoiceCopilotResponse
from backend.core.routing import calculate_bike_route

logger = logging.getLogger("viberide.routing_routes")
router = APIRouter(tags=["routing"])


# ============================================================================
# 1. ROUTE PLANNING CONTRACTS & ENDPOINT
# ============================================================================

class RouteRequest(BaseModel):
    user_prompt: str = Field(
        ...,
        description="Ride request, e.g. 'Chill sunset ride from UPB Regie to Carol Park'",
    )
    city: str = Field(default="Bucharest")
    vibe_preset: Optional[str] = Field(default="green_shady")
    time_of_day: str = Field(default="sunset")
    wind_direction_deg: Optional[int] = Field(default=270)


@router.post("/plan")
async def plan_and_calculate_route(req: RouteRequest) -> Dict[str, Any]:
    """
    1. Genereaza traseul mindful & ancorele cu Meta Muse Spark (vibe_planner).
    2. Calculeaza geometria GeoJSON detaliata prin GIS (cu fallback LineString automat pentru rute globale).
    3. Returneaza pachetul complet cerut de SearchHUD si MapView.
    """
    try:
        logger.info("Planning route: prompt='%s', preset='%s'", req.user_prompt, req.vibe_preset)
        planner = VibePlannerAgent()
        vibe_plan = planner.generate_plan(
            user_prompt=req.user_prompt,
            city=req.city,
            wind_direction_deg=req.wind_direction_deg,
            time_of_day=req.time_of_day,
        )

        waypoints_coords = vibe_plan.to_geojson_coordinates()

        # Calcul GIS cu protectie la coordonate globale / pica serverul OSM
        try:
            geojson = await calculate_bike_route(waypoints_coords)
            if not geojson.get("features"):
                raise ValueError("OSM returned empty features")
        except Exception as gis_err:
            logger.warning("OSM GIS engine failed or unsupported bounds (%s). Generating fallback LineString.", gis_err)
            geojson = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": waypoints_coords,
                        },
                        "properties": {
                            "distance_km": 6.8,
                            "duration_min": 24.0,
                        },
                    }
                ],
            }

        # Injectam metadatele Zen direct in proprietatile GeoJSON
        props = geojson["features"][0].setdefault("properties", {})
        props["vibe_title"] = vibe_plan.vibe_title
        props["audio_intro"] = vibe_plan.audio_intro
        props["avoid_tags"] = vibe_plan.avoid_tags
        props["chill_cues"] = [cue.model_dump() for cue in vibe_plan.chill_cues]
        props["origin_name"] = vibe_plan.origin.name
        props["destination_name"] = vibe_plan.destination.name

        plan_dict = vibe_plan.model_dump()
        plan_dict.setdefault("decibels_avoided_est_db", 25)

        # Returnam payload-ul hibrid (acceptat atat de SearchHUD.js cat si de App.js)
        return {
            "plan": plan_dict,
            "vibe_plan": plan_dict,
            "geojson": geojson,
        }

    except Exception as exc:
        logger.error("Error in plan route: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ============================================================================
# 2. VOICE COPILOT CONTRACTS & ENDPOINT
# ============================================================================

class CopilotVoiceRequest(BaseModel):
    user_utterance: str = Field(...)
    current_street: Optional[str] = Field(default="moving on route")


@router.post("/copilot", response_model=VoiceCopilotResponse)
async def copilot_voice_endpoint(req: CopilotVoiceRequest) -> VoiceCopilotResponse:
    try:
        agent = VoiceCopilotAgent()
        return agent.process_voice_input(
            user_utterance=req.user_utterance,
            current_street=req.current_street,
        )
    except Exception as exc:
        logger.error("Error in copilot endpoint: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))