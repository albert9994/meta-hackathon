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
    Împachetează coordonatele și statisticile în formatul standard internațional GeoJSON.
    Acesta este exact formatul cerut de colegul de pe Mobile (Dev 3).
    """
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": coordinates  # Listă de puncte [lon, lat]
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
    Calculează traseul pentru bicicletă între punctele date.
    
    PARAMETRU:
    coordinates: Listă de puncte în format STRICT [lon, lat]
                 Exemplu: [[26.0558, 44.4447], [26.0963, 44.4150]]
                 
    RETURNEAZĂ:
    Un GeoJSON FeatureCollection conform contractului din Secțiunea 4.
    """
    if len(coordinates) < 2:
        raise ValueError("Ai nevoie de cel puțin 2 puncte (Start și Sosire) pentru un traseu.")

    # ------------------------------------------------------------------------
    # Opțiunea 1: OpenRouteService (dacă există cheie API)
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
            print(f"[Avertisment] OpenRouteService indisponibil ({e}). Comutăm pe fallback OSM...")

    # ------------------------------------------------------------------------
    # Opțiunea 2: Fallback OpenStreetMap (Gratuit, public, fără cheie API)
    # ------------------------------------------------------------------------
    coord_string = ";".join([f"{lon},{lat}" for lon, lat in coordinates])
    osm_url = f"https://routing.openstreetmap.de/routed-bike/route/v1/driving/{coord_string}?overview=full&geometries=geojson"

    async with httpx.AsyncClient(timeout=12.0) as client:
        res = await client.get(osm_url)
        if res.status_code != 200:
            raise RuntimeError(f"Eroare la calcularea rutei de pe OSM: cod status {res.status_code}")
        
        data = res.json()
        if "routes" not in data or len(data["routes"]) == 0:
            raise RuntimeError("Nu s-a putut găsi nicio rută validă între aceste puncte.")
            
        route = data["routes"][0]
        dist_km = round(route["distance"] / 1000.0, 2)
        dur_min = round(route["duration"] / 60.0, 1)
        coords = route["geometry"]["coordinates"]
        
        return format_as_geojson(coords, dist_km, dur_min)


# ============================================================================
# BLOC DE TEST RAPID
# ============================================================================
if __name__ == "__main__":
    import asyncio

    async def test_run():
        print("🚴‍♂️ Verificăm generarea de GeoJSON valid...\n")
        puncte_test = [
            [26.0558, 44.4447],  # UPB Regie
            [26.0976, 44.4342],  # Origo Coffee
            [26.0963, 44.4150]   # Parcul Carol
        ]

        geojson_result = await calculate_bike_route(puncte_test)
        
        props = geojson_result["features"][0]["properties"]
        geom = geojson_result["features"][0]["geometry"]
        
        print("✅ Structură GeoJSON creată cu succes!")
        print(f"📦 Tip GeoJSON: {geojson_result['type']}")
        print(f"📏 Distanță: {props['distance_km']} km | ⏱️ Timp: {props['duration_min']} min")
        print(f"📍 Puncte [lon, lat] în linie: {len(geom['coordinates'])} puncte")

    asyncio.run(test_run())