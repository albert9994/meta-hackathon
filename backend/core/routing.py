import os
from typing import Any, Dict, List, Sequence

import httpx
from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# VibeRide GIS Routing Engine
# OpenRouteService with resilient fallback to OpenStreetMap Public Bike Router
# ============================================================================


def _ors_key() -> str:
    # Citit la apel (nu la import), ca sa prinda .env incarcat tarziu.
    return (os.getenv("OPENROUTESERVICE_API_KEY") or os.getenv("ORS_API_KEY") or "").strip()


def format_as_geojson(
    coordinates: List[List[float]],
    distance_km: float,
    duration_min: float,
    decibels_avoided_est_db: int = 25,
) -> Dict[str, Any]:
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
                    "coordinates": coordinates,  # Points list [lon, lat]
                },
                "properties": {
                    "distance_km": distance_km,
                    "duration_min": duration_min,
                    "decibels_avoided_est_db": decibels_avoided_est_db,
                },
            }
        ],
    }


def _dedupe(points: Sequence[Sequence[float]]) -> List[List[float]]:
    """Elimina punctele consecutive identice (segmente de lungime 0 sparg routerele)."""
    clean = [[float(points[0][0]), float(points[0][1])]]
    for p in points[1:]:
        lon, lat = float(p[0]), float(p[1])
        if abs(lon - clean[-1][0]) > 1e-5 or abs(lat - clean[-1][1]) > 1e-5:
            clean.append([lon, lat])
    return clean


def _valid_lonlat(p: Sequence[float]) -> bool:
    return (
        len(p) >= 2
        and -180 <= float(p[0]) <= 180
        and -90 <= float(p[1]) <= 90
    )


async def calculate_bike_route(coordinates: List[Sequence[float]]) -> Dict[str, Any]:
    """
    Calculates the cycling route across the provided waypoints.

    Args:
        coordinates: A list of points strictly in [lon, lat] format (GeoJSON standard).
                     Example: [[26.0558, 44.4447], [26.0963, 44.4150]]

    Returns:
        A GeoJSON FeatureCollection containing the route geometry and summary metrics.
    """
    if not coordinates or len(coordinates) < 2:
        raise ValueError("At least 2 points (origin and destination) are required to calculate a route.")
    if not all(_valid_lonlat(p) for p in coordinates):
        raise ValueError("Invalid coordinates: expected [lon, lat] within valid ranges.")

    coordinates = _dedupe(coordinates)
    if len(coordinates) < 2:
        raise ValueError("Route points collapse to a single location.")

    # ------------------------------------------------------------------------
    # Option 1: OpenRouteService (if there is an API key)
    # ------------------------------------------------------------------------
    api_key = _ors_key()
    if api_key:
        try:
            url = "https://api.openrouteservice.org/v2/directions/cycling-regular/geojson"
            headers = {
                "Authorization": api_key,
                "Content-Type": "application/json",
            }
            payload = {
                "coordinates": coordinates,
                "radiuses": [1000] * len(coordinates),  # snap pana la 1 km pe graful ciclabil
                "options": {"avoid_features": ["steps", "ferries"]},
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    feature = data["features"][0]
                    summary = feature["properties"]["summary"]
                    coords = [[c[0], c[1]] for c in feature["geometry"]["coordinates"]]
                    if len(coords) >= 2:
                        dist_km = round(summary["distance"] / 1000.0, 2)
                        dur_min = round(summary["duration"] / 60.0, 1)
                        return format_as_geojson(coords, dist_km, dur_min)
                    print("[Warning] ORS returned empty geometry. Falling back to OSM...")
                else:
                    print(f"[Warning] ORS {res.status_code}: {res.text[:200]}. Falling back to OSM...")
        except Exception as e:
            print(f"[Warning] OpenRouteService unavailable ({e}). Falling back to OSM...")

    # ------------------------------------------------------------------------
    # Option 2: Fallback OpenStreetMap (Free, public, without an API key)
    # ------------------------------------------------------------------------
    coord_string = ";".join(f"{lon},{lat}" for lon, lat in coordinates)
    osm_url = (
        f"https://routing.openstreetmap.de/routed-bike/route/v1/driving/{coord_string}"
        "?overview=full&geometries=geojson"
    )

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            res = await client.get(osm_url)
    except Exception as e:
        raise RuntimeError(f"OSM router unreachable: {e}") from e

    if res.status_code != 200:
        raise RuntimeError(f"Error calculating route from OSM: status code {res.status_code}")

    data = res.json()
    if not data.get("routes"):
        raise RuntimeError("No valid route could be found between these points.")

    route = data["routes"][0]
    coords = [[c[0], c[1]] for c in route["geometry"]["coordinates"]]
    if len(coords) < 2:
        raise RuntimeError("Routing returned an empty geometry.")

    dist_km = round(route["distance"] / 1000.0, 2)
    dur_min = round(route["duration"] / 60.0, 1)
    return format_as_geojson(coords, dist_km, dur_min)


# ============================================================================
# QUICK TEST
# ============================================================================
if __name__ == "__main__":
    import asyncio

    async def test_run():
        print("Verifying valid GeoJSON generation...\n")
        test_points = [
            [26.0558, 44.4447],  # UPB Regie
            [26.0976, 44.4342],  # Origo Coffee
            [26.0963, 44.4150],  # Carol Park
        ]

        geojson_result = await calculate_bike_route(test_points)

        props = geojson_result["features"][0]["properties"]
        geom = geojson_result["features"][0]["geometry"]

        print("GeoJSON structure created successfully!")
        print(f"GeoJSON Type: {geojson_result['type']}")
        print(
            f"Distance: {props['distance_km']} km | Time: {props['duration_min']} min | "
            f"Noise avoided: {props.get('decibels_avoided_est_db')} dB"
        )
        print(f"Points [lon, lat] in line: {len(geom['coordinates'])} points")
        print(f"First point: {geom['coordinates'][0]}  (expected ~[26.05, 44.44])")

    asyncio.run(test_run())