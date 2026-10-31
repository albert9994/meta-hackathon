"""
VibeRide - Navigation & GIS Routing Routes.

Endpoints:
    POST /api/routes/calculate    Direct waypoint routing returning GeoJSON
"""

from typing import List, Tuple, Dict, Any
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.core.routing import calculate_bike_route

router = APIRouter(prefix="/api/routes", tags=["navigation"])


# =============================================================================
# Schemas (Pydantic v2 - Data Validation)
# =============================================================================

class Waypoint(BaseModel):
    name: str = Field(..., description="Waypoint identifier or human-readable label")
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees (WGS84)")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees (WGS84)")


class DirectRouteRequest(BaseModel):
    """
    Payload for calculating a bike route across multiple navigation waypoints.
    """
    origin: Waypoint = Field(..., description="Start location")
    destination: Waypoint = Field(..., description="Final destination")
    intermediate_stops: List[Waypoint] = Field(
        default_factory=list,
        description="Optional list of intermediate waypoints or scenic stops"
    )


# =============================================================================
# Routes
# =============================================================================

@router.post(
    "/calculate",
    summary="Calculate Cycling Route",
    description="Calculates a cycling route across waypoints and returns a GeoJSON FeatureCollection.",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK
)
async def calculate_direct_route(request: DirectRouteRequest) -> Dict[str, Any]:
    """
    Extracts coordinates from the request payload, orders them strictly as
    [lon, lat] pairs required by GIS engines, and invokes the bike router.
    """
    try:
        # Build coordinate sequence: origin -> intermediate stops -> destination
        coordinates: List[Tuple[float, float]] = [
            (request.origin.lon, request.origin.lat)
        ]

        for stop in request.intermediate_stops:
            coordinates.append((stop.lon, stop.lat))

        coordinates.append((request.destination.lon, request.destination.lat))

        geojson_route = await calculate_bike_route(coordinates)
        return geojson_route

    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except RuntimeError as re:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(re)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Route calculation pipeline failed: {str(exc)}"
        )