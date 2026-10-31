"""
VibeRide - Navigation & GIS Routing Routes (Developer 2).

Endpoints:
    POST /api/routes/plan         Natural language + Vibe AI planning
    POST /api/routes/calculate    Direct waypoint routing via GeoJSON
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.core.routing import calculate_bike_route

logger = logging.getLogger("viberide.navigation")

router = APIRouter(prefix="/api/routes", tags=["navigation"])

VIBE_AGENT = ("backend.agents.vibe_planner", "plan_vibe_route")
AGENT_TIMEOUT_SEC = 20.0

# =============================================================================
# Landmark Database & Presets for Deterministic Fallback (System Prompt 1)
# =============================================================================

BUCHAREST_LANDMARKS: Dict[str, Dict[str, Any]] = {
    "regie": {"name": "UPB Regie", "lat": 44.4447, "lon": 26.0558},
    "carol": {"name": "Carol Park", "lat": 44.4150, "lon": 26.0963},
    "cotroceni": {"name": "Historic Cotroceni", "lat": 44.4328, "lon": 26.0697, "type": "view"},
    "cismigiu": {"name": "Cișmigiu Gardens", "lat": 44.4361, "lon": 26.0906, "type": "park"},
    "herastrau": {"name": "Herăstrău Park (King Mihai I)", "lat": 44.4708, "lon": 26.0841, "type": "park"},
    "origo": {"name": "Origo Specialty Coffee", "lat": 44.4342, "lon": 26.0976, "type": "coffee"},
}

FALLBACK_PRESETS: Dict[str, Dict[str, Any]] = {
    "green_shady": {
        "origin": BUCHAREST_LANDMARKS["cismigiu"],
        "destination": BUCHAREST_LANDMARKS["herastrau"],
        "intermediate_stops": [
            {"name": "Kiseleff Shaded Boulevard", "lat": 44.4600, "lon": 26.0800, "type": "park"}
        ],
        "vibe_title": "Green Canopy & Lake Tour",
        "audio_intro": "Navigating calm shaded corridors towards Herăstrău.",
    },
    "historic_chill": {
        "origin": BUCHAREST_LANDMARKS["regie"],
        "destination": BUCHAREST_LANDMARKS["carol"],
        "intermediate_stops": [
            BUCHAREST_LANDMARKS["cotroceni"]
        ],
        "vibe_title": "Historic Villas & Low-Traffic Alleys",
        "audio_intro": "Rolling through quiet Cotroceni streets away from traffic.",
    },
    "pitstop": {
        "origin": BUCHAREST_LANDMARKS["regie"],
        "destination": BUCHAREST_LANDMARKS["cismigiu"],
        "intermediate_stops": [
            BUCHAREST_LANDMARKS["origo"]
        ],
        "vibe_title": "Cortado Commuter Special",
        "audio_intro": "Direct low-stress route with a curated specialty coffee stop.",
    }
}


# =============================================================================
# Schemas (Pydantic v2)
# =============================================================================

class Waypoint(BaseModel):
    name: str = Field(..., description="Waypoint identifier or human-readable label")
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees (WGS84)")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees (WGS84)")


class StopItem(Waypoint):
    type: Optional[str] = Field(default="view", description="Type of stop: coffee, park, view, gelato")


class RoutePlanRequest(BaseModel):
    user_prompt: str = Field(
        ...,
        min_length=3,
        description="Natural language request (e.g., 'Take me from UPB Regie to Carol Park through shady streets')"
    )
    vibe_preset: str = Field(
        default="green_shady",
        description="Selected mood preset: green_shady, historic_chill, pitstop"
    )
    city: str = Field(
        default="Bucharest",
        description="Target metropolitan area"
    )


class PlanDetails(BaseModel):
    origin: Waypoint
    destination: Waypoint
    intermediate_stops: List[StopItem] = Field(default_factory=list)
    vibe_title: str
    audio_intro: str


class RoutePlanResponse(BaseModel):
    plan: PlanDetails
    geojson: Dict[str, Any]


class DirectRouteRequest(BaseModel):
    origin: Waypoint = Field(..., description="Start location")
    destination: Waypoint = Field(..., description="Final destination")
    intermediate_stops: List[Waypoint] = Field(
        default_factory=list,
        description="Optional list of intermediate waypoints"
    )


# =============================================================================
# Agent Helpers & Fallback Engine
# =============================================================================

def _fallback_plan(request: RoutePlanRequest) -> Dict[str, Any]:
    """
    Selects a deterministic preset matching the requested vibe and checks
    if the prompt mentions specific known landmarks.
    """
    preset = FALLBACK_PRESETS.get(request.vibe_preset, FALLBACK_PRESETS["green_shady"])

    origin = dict(preset["origin"])
    destination = dict(preset["destination"])
    intermediate_stops = [dict(s) for s in preset["intermediate_stops"]]

    prompt_lower = request.user_prompt.lower()

    # Landmark matching based on keywords in prompt
    if "regie" in prompt_lower or "upb" in prompt_lower:
        origin = dict(BUCHAREST_LANDMARKS["regie"])

    if "herastrau" in prompt_lower or "herăstrău" in prompt_lower:
        destination = dict(BUCHAREST_LANDMARKS["herastrau"])
    elif "carol" in prompt_lower:
        destination = dict(BUCHAREST_LANDMARKS["carol"])
    elif "cismigiu" in prompt_lower or "cișmigiu" in prompt_lower:
        destination = dict(BUCHAREST_LANDMARKS["cismigiu"])

    if ("cafe" in prompt_lower or "coffee" in prompt_lower) and not any(s.get("type") == "coffee" for s in intermediate_stops):
        intermediate_stops.append(dict(BUCHAREST_LANDMARKS["origo"]))

    logger.info("Using dynamic fallback plan for preset '%s'", request.vibe_preset)

    return {
        "origin": origin,
        "destination": destination,
        "intermediate_stops": intermediate_stops,
        "vibe_title": preset["vibe_title"],
        "audio_intro": preset["audio_intro"],
        "avoid_tags": ["highways", "heavy_traffic"]
    }


async def _call_vibe_agent(req: RoutePlanRequest) -> Dict[str, Any]:
    """
    Calls Dev 1's vibe planner with timeout protection and JSON normalization.
    """
    module_name, func_name = VIBE_AGENT
    try:
        module = importlib.import_module(module_name)
        func = getattr(module, func_name)
    except (ImportError, AttributeError):
        logger.warning("Vibe planner agent is not available yet at %s.%s", module_name, func_name)
        return _fallback_plan(req)

    try:
        if inspect.iscoroutinefunction(func):
            result = await asyncio.wait_for(
                func(req.user_prompt, req.vibe_preset, req.city),
                timeout=AGENT_TIMEOUT_SEC
            )
        else:
            result = await asyncio.wait_for(
                asyncio.to_thread(func, req.user_prompt, req.vibe_preset, req.city),
                timeout=AGENT_TIMEOUT_SEC
            )
            if inspect.isawaitable(result):
                result = await asyncio.wait_for(result, timeout=AGENT_TIMEOUT_SEC)

        if isinstance(result, (str, bytes)):
            result = json.loads(result)

        if not isinstance(result, dict) or "origin" not in result or "destination" not in result:
            logger.warning("Agent returned invalid structure; utilizing fallback.")
            return _fallback_plan(req)

        return result

    except Exception as exc:
        logger.warning("Vibe planner call failed (%s); switching to fallback.", exc)
        return _fallback_plan(req)


# =============================================================================
# Routes
# =============================================================================

@router.post(
    "/plan",
    summary="Semantic AI Route Planning",
    description="Translates a natural language request and vibe into an urban cycling route with GeoJSON geometry.",
    response_model=RoutePlanResponse,
    status_code=status.HTTP_200_OK
)
async def plan_route(request: RoutePlanRequest) -> RoutePlanResponse:
    """
    Full pipeline:
    1. Interprets prompt & vibe via Meta Muse Spark (Dev 1) or fallback engine.
    2. Builds strict [lon, lat] GIS coordinate list.
    3. Calculates geometry via ORS / OSM fallback (Dev 2).
    4. Packages plan metadata and audio cues for the mobile app.
    """
    agent_output = await _call_vibe_agent(request)

    try:
        plan_details = PlanDetails(
            origin=Waypoint(**agent_output["origin"]),
            destination=Waypoint(**agent_output["destination"]),
            intermediate_stops=[StopItem(**stop) for stop in agent_output.get("intermediate_stops", [])],
            vibe_title=str(agent_output.get("vibe_title") or "Calm Urban Ride"),
            audio_intro=str(agent_output.get("audio_intro") or "Route calculated. Ride mindfully.")
        )
    except Exception as exc:
        logger.error("Plan validation error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Malformed route plan structure: {str(exc)}"
        )

    # Strict GIS [lon, lat] ordering
    coordinates: List[Tuple[float, float]] = [
        (plan_details.origin.lon, plan_details.origin.lat)
    ]
    for stop in plan_details.intermediate_stops:
        coordinates.append((stop.lon, stop.lat))
    coordinates.append((plan_details.destination.lon, plan_details.destination.lat))

    try:
        geojson = await calculate_bike_route(coordinates)
    except RuntimeError as re:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GIS Routing services unreachable: {str(re)}"
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Route calculation pipeline failed: {str(exc)}"
        )

    return RoutePlanResponse(plan=plan_details, geojson=geojson)


@router.post(
    "/calculate",
    summary="Calculate Direct Cycling Route",
    description="Calculates route geometry directly from explicit coordinates without invoking the LLM.",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK
)
async def calculate_direct_route(request: DirectRouteRequest) -> Dict[str, Any]:
    """
    Direct waypoint-to-waypoint GIS calculation route.
    """
    try:
        coordinates: List[Tuple[float, float]] = [
            (request.origin.lon, request.origin.lat)
        ]
        for stop in request.intermediate_stops:
            coordinates.append((stop.lon, stop.lat))
        coordinates.append((request.destination.lon, request.destination.lat))

        return await calculate_bike_route(coordinates)

    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except RuntimeError as re:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(re))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Route calculation pipeline failed: {str(exc)}"
        )