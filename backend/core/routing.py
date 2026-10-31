import os
import httpx
from typing import List, Tuple, Dict, Any

# ============================================================================
# VibeRide GIS Routing Engine
# OpenRouteService with resilient fallback to OpenStreetMap Public Bike Router
# ============================================================================

ORS_API_KEY = os.getenv("OPENROUTESERVICE_API_KEY", "")

def format_as_geojson(coordinates: List[List[float]], distance_km: float, duration_min: float) -> Dict[str, Any]:
    """
    Wraps coordinates and route statistics into the standard GeoJSON format.
    """
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": coordinates  # Points list [lon, lat]
                },
                "properties": {
                    "distance_km": distance_km,
                    "duration_min": duration_min
                }
            }
        ]
    }

async def calculate_bike_route(coordinates: List[Tuple[float, float]]) -> Dict[str, Any]:
    """
    Calculates the cycling route across the provided waypoints.
    
    Args:
        coordinates: A list of points strictly in [lon, lat] format (GeoJSON standard).
                     Example: [[26.0558, 44.4447], [26.0963, 44.4150]]
                     
    Returns:
        A GeoJSON FeatureCollection containing the route geometry and summary metrics.
    """
    if len(coordinates) < 2:
        raise ValueError("At least 2 points (origin and destination) are required to calculate a route.")

    # ------------------------------------------------------------------------
    # Option 1: OpenRouteService (if there is an API key)
    # ------------------------------------------------------------------------
    if ORS_API_KEY:
        try:
            url = "https://api.openrouteservice.org/v2/directions/cycling-regular/geojson"
            headers = {
                "Authorization": ORS_API_KEY,
                "Content-Type": "application/json"
            }
            payload = {
                "coordinates": coordinates,
                "options": {
                    "avoid_features": ["highways"]
                }
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    feature = data["features"][0]
                    summary = feature["properties"]["summary"]
                    dist_km = round(summary["distance"] / 1000.0, 2)
                    dur_min = round(summary["duration"] / 60.0, 1)
                    coords = feature["geometry"]["coordinates"]
                    return format_as_geojson(coords, dist_km, dur_min)
        except Exception as e:
            print(f"[Warning] OpenRouteService unavailable ({e}). Falling back to OSM...")

    # ------------------------------------------------------------------------
    # Option 2: Fallback OpenStreetMap (Free, public, without an API key)
    # ------------------------------------------------------------------------
    coord_string = ";".join([f"{lon},{lat}" for lon, lat in coordinates])
    osm_url = f"https://routing.openstreetmap.de/routed-bike/route/v1/driving/{coord_string}?overview=full&geometries=geojson"

    async with httpx.AsyncClient(timeout=12.0) as client:
        res = await client.get(osm_url)
        if res.status_code != 200:
            raise RuntimeError(f"Error calculating route from OSM: status code {res.status_code}")
        
        data = res.json()
        if "routes" not in data or len(data["routes"]) == 0:
            raise RuntimeError("No valid route could be found between these points.")
            
        route = data["routes"][0]
        dist_km = round(route["distance"] / 1000.0, 2)
        dur_min = round(route["duration"] / 60.0, 1)
        coords = route["geometry"]["coordinates"]
        
        return format_as_geojson(coords, dist_km, dur_min)


# ============================================================================
# QUICK TEST
# ============================================================================
if __name__ == "__main__":
    import asyncio

    async def test_run():
        print("🚴‍♂️ Verifying valid GeoJSON generation...\n")
        test_points = [
            [26.0558, 44.4447],  # UPB Regie
            [26.0976, 44.4342],  # Origo Coffee
            [26.0963, 44.4150]   # Carol Park
        ]

        geojson_result = await calculate_bike_route(test_points)
        
        props = geojson_result["features"][0]["properties"]
        geom = geojson_result["features"][0]["geometry"]
        
        print("✅ GeoJSON structure created successfully!")
        print(f"📦 GeoJSON Type: {geojson_result['type']}")
        print(f"📏 Distance: {props['distance_km']} km | ⏱️ Time: {props['duration_min']} min")
        print(f"📍 Points [lon, lat] in line: {len(geom['coordinates'])} points")

    asyncio.run(test_run())