import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.agents.vibe_planner import VibePlannerAgent
from backend.core.routing import calculate_bike_route

logger = logging.getLogger("viberide.routing_routes")
router = APIRouter(prefix="/api/route", tags=["routing"])


class RouteRequest(BaseModel):
    user_prompt: str = Field(
        ...,
        description="Ride request, e.g. 'Chill sunset ride from UPB Regie to Carol Park'",
    )
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
    try:
        # 1. Planificare cu AI
        planner = VibePlannerAgent()
        vibe_plan = planner.generate_plan(
            user_prompt=req.user_prompt,
            city=req.city,
            wind_direction_deg=req.wind_direction_deg,
            time_of_day=req.time_of_day,
        )

        # 2. Extragere coordonate [lon, lat] pentru GIS
        waypoints_coords = vibe_plan.to_geojson_coordinates()

        # 3. Calculare geometrie bicicletă cu motorul GIS
        geojson = await calculate_bike_route(waypoints_coords)

        # 4. Injectam metadatele Zen direct in proprietatile rutei
        props = geojson["features"][0]["properties"]
        props["vibe_title"] = vibe_plan.vibe_title
        props["audio_intro"] = vibe_plan.audio_intro
        props["avoid_tags"] = vibe_plan.avoid_tags
        props["chill_cues"] = [cue.model_dump() for cue in vibe_plan.chill_cues]
        props["origin_name"] = vibe_plan.origin.name
        props["destination_name"] = vibe_plan.destination.name

        # Returnam atat formatul GeoJSON standard, cat si obiectul de vibe_plan separat
        return {
            "geojson": geojson,
            "vibe_plan": vibe_plan.model_dump(),
        }

    except Exception as exc:
        logger.error("Error in /api/route/plan: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))