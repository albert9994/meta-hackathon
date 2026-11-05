import json
import logging
import math
import os
import re
import urllib.parse
from typing import Any, Optional, Tuple, List

from dotenv import load_dotenv
import httpx
from openai import OpenAI
from pydantic import BaseModel, Field, model_validator

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("vibe_planner")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 VibeRideHackathon/2.0"
}

# Corectii rapide pentru typo-uri frecvente sau exonyme romanesti
TYPO_MAP = {
    r"\bsao\s*paula\b": "Sao Paulo",
    r"\bsao\s*paolo\b": "Sao Paulo",
    r"\bciudad\s+de\s+mexic\b": "Mexico City",
    r"\bmexic\b": "Mexico City",
    r"\blondra\b": "London",
    r"\broma\b": "Rome",
    r"\bviena\b": "Vienna",
    r"\baten[aă]\b": "Athens",
    r"\bvarsovia\b": "Warsaw",
    r"\bpraga\b": "Prague",
    r"\bbudapesta\b": "Budapest",
    r"\bbucuresti\b": "Bucharest",
    r"\bseverin\s+cetate\b": "Cetatea Medievala a Severinului, Drobeta-Turnu Severin",
    r"\bcetate\s+severin\b": "Cetatea Medievala a Severinului, Drobeta-Turnu Severin",
    r"\bpadurea\s+crihala\b": "Padurea Crihala, Drobeta-Turnu Severin",
    r"\bcrihala\b": "Padurea Crihala, Drobeta-Turnu Severin",
}


# =====================================================================
# 0. DEEP JSON PARSING & SMART NER GEOCODING
# =====================================================================

def extract_json(text: str) -> dict:
    """Extrage si despacheteaza obiectul JSON valid din output-ul LLM."""
    text = re.sub(r"<think>.*?</think>", "", (text or ""), flags=re.S).strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e <= s:
        raise ValueError("No JSON object in model output")
    blob = text[s : e + 1]
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        data = json.loads(re.sub(r",\s*([}\]])", r"\1", blob))

    # Daca modelul a impachetat raspunsul in {"plan": {...}} sau {"route": {...}}
    if isinstance(data, dict):
        for wrapper_key in ("plan", "vibe_plan", "route", "data", "result", "response"):
            if wrapper_key in data and isinstance(data[wrapper_key], dict):
                inner = data[wrapper_key]
                if any(k in inner for k in ("origin", "start", "destination", "end", "waypoints")):
                    return inner
    return data


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p = math.pi / 180
    h = (
        math.sin((lat2 - lat1) * p / 2) ** 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    )
    return 12742 * math.asin(math.sqrt(min(1.0, h)))


def _apply_typo_fixes(text: str) -> str:
    res = text
    for pattern, repl in TYPO_MAP.items():
        res = re.sub(pattern, repl, res, flags=re.I)
    return res


def _strip_conversational_clauses(prompt: str) -> str:
    """
    Taie propozitiile parazite de politete, intrebari si cerinte secundare
    (ex: 'can you help me?', 'and drink a good coffee on my way', '30 de min').
    """
    s = _apply_typo_fixes(prompt)

    # 1. Taiem tot ce urmeaza dupa conectori de cerinte secundare
    secondary_splits = [
        r"\bcan\s+you\b",
        r"\bcould\s+you\b",
        r"\bplease\b",
        r"\bte\s+rog\b",
        r"\band\s+(?:drink|eat|stop|visit|see|have|grab|get|find|make)\b",
        r"\bsi\s+(?:sa|vreau|bem|beau|mananc|oprim|vedem|vizitam)\b",
        r"\bwith\s+a\s+(?:stop|coffee|break|view)\b",
        r"\bcu\s+o?\s*(?:oprire|cafea|pauza)\b",
        r"\bon\s+my\s+way\b",
        r"\balong\s+the\s+way\b",
        r"\bpe\s+drum\b",
    ]
    for pat in secondary_splits:
        s = re.split(pat, s, flags=re.I)[0]

    # 2. Eliminam expresiile de timp / durata (ex: "30 de min", "1 ora", "for 45 minutes")
    s = re.sub(
        r"\b(?:for|pentru|cam|vreo|timp\s+de)?\s*\d+\s*(?:de\s*)?(?:min|minute|mins|minutes|ora|ore|hour|hours|h|km)\b",
        " ",
        s,
        flags=re.I,
    )

    # 3. Eliminam intro-urile conversationale de la inceput
    s = re.sub(
        r"^(?:hello|hi|hey|salut|buna|ola|yo|umm|well)[\s,!.:;-]*",
        "",
        s.strip(),
        flags=re.I,
    )
    s = re.sub(
        r"^(?:i\s+want\s+to\s+have\s+a\s+ride|i\s+want\s+to\s+ride|i\s+want\s+a\s+ride|i\s+would\s+like\s+to\s+go|i\s+want\s+to\s+go|i\s+want|take\s+me\s+on\s+a\s+ride|take\s+me|let'?s\s+go|vreau\s+sa\s+ma\s+plimb|vreau\s+sa\s+merg|vreau\s+un\s+traseu|vreau\s+o\s+ruta|vreau|du-ma\s+sa\s+ma\s+plimb|du\s+ma\s+sa\s+ma\s+plimb|du-ma|du\s+ma|hai\s+sa\s+mergem|sa\s+ma\s+plimb|sa\s+ma\s+duca)\b[\s,:;-]*",
        "",
        s.strip(),
        flags=re.I,
    )

    # 4. Eliminam sintagme de genul "prin centru din" -> lasam doar orasul
    s = re.sub(r"\b(?:prin|in|pe\s+la)\s+centru(?:l)?\s+(?:din|in|de\s+la)\b", "in", s, flags=re.I)
    s = re.sub(r"\b(?:downtown|city\s+center\s+of|center\s+of)\b", "", s, flags=re.I)

    return " ".join(s.split()).strip(" ?!.,;:-")


def extract_locations_ner(user_prompt: str) -> Tuple[Optional[str], Optional[str], bool]:
    """
    Returneaza (origin_query, destination_query, is_loop)
    Extragere inteligenta pentru A -> B sau Locatie Unica (Loop).
    """
    p_raw = user_prompt or ""
    p_low = p_raw.lower()

    # Detectam daca utilizatorul cere explicit o plimbare / tura / loop
    is_loop = bool(
        re.search(
            r"\b(loop|circular|roundtrip|circuit|tura|tur|plimb|plimbare|plimbe|ride\s+in|ride\s+around|cruise\s+in|cruise\s+around|explore)\b",
            p_low,
        )
        or re.search(r"\b\d+\s*(?:de\s*)?(?:min|minute|mins|ora|ore|hour|hours)\b", p_low)
    )

    cleaned = _strip_conversational_clauses(p_raw)

    # CAZUL 1: Ruta explicita A -> B (ex: "from X to Y", "din X in Y", "de la X spre Y", "X spre Y")
    ab_patterns = [
        r"(?:from|de\s+la|din|plecare\s+din)\s+(.+?)\s+(?:to|towards|until|in|la|spre|catre|pana\s+la|pana\s+in)\s+(.+)",
        r"^(.+?)\s+(?:to|towards|spre|catre|pana\s+la|pana\s+in|->|-)\s+(.+)$",
    ]
    for pat in ab_patterns:
        m = re.search(pat, cleaned, flags=re.I)
        if m:
            loc_a = m.group(1).strip(" ?!.,;:-")
            loc_b = m.group(2).strip(" ?!.,;:-")
            # Curatam prepozitiile reziduale din capete
            loc_a = re.sub(r"^(?:in|la|din|from|at)\s+", "", loc_a, flags=re.I).strip()
            loc_b = re.sub(r"^(?:in|la|din|to|at)\s+", "", loc_b, flags=re.I).strip()
            if loc_a and loc_b and loc_a.lower() != loc_b.lower():
                return loc_a, loc_b, False

    # CAZUL 2: Locatie introdusa prin prepozitie ("in Las Vegas", "prin Craiova", "around Tokyo")
    prep_match = re.search(
        r"\b(?:in|around|through|near|prin|pe\s+la|la|din|spre)\s+([A-Za-zÀ-ž0-9\s\-]{2,35})$",
        cleaned,
        flags=re.I,
    )
    if prep_match:
        loc = prep_match.group(1).strip(" ?!.,;:-")
        return loc, None, True

    # CAZUL 3: Daca au ramas 2 repere cunoscute lipite (ex: "Carol Herastrau", "Regie Militari")
    words = cleaned.split()
    if len(words) == 2 and not is_loop:
        return words[0], words[1], False

    # CAZUL 4: Extragem substantivele proprii (Cuvinte cu Majuscula din promptul original, ex: "Las Vegas")
    stop_caps = {"Hello", "Hi", "Hey", "Salut", "Vreau", "Du", "Duma", "Du-ma", "Take", "Can", "And", "Please", "Go", "Ride", "Chill", "Green", "Shady", "Historic", "Pitstop"}
    cap_chunks = re.findall(r"\b([A-ZÀ-Ž][a-zà-ž]+(?:\s+[A-ZÀ-Ž][a-zà-ž]+)*)\b", _apply_typo_fixes(p_raw))
    valid_caps = [c for c in cap_chunks if c not in stop_caps and len(c) >= 3]
    if len(valid_caps) >= 2 and not is_loop:
        return valid_caps[0], valid_caps[1], False
    elif len(valid_caps) == 1:
        return valid_caps[0], None, True

    # CAZUL 5: Returnam direct textul curatat
    if cleaned and len(cleaned) >= 2:
        return cleaned, None, True

    return None, None, True


def live_geocode(query: str) -> Optional[Tuple[float, float, str]]:
    """
    Geocodare universala ultra-fiabila (Photon + Nominatim fallback).
    """
    if not query:
        return None

    q = _apply_typo_fixes(query)
    # Stergem cuvinte parazite daca au mai scapat
    q = re.sub(
        r"\b(hello|hi|want|have|ride|help|me|drink|good|coffe|coffee|way|vreau|plimb|merg|traseu|ruta|min|minute|ora|ore)\b",
        " ",
        q,
        flags=re.I,
    )
    q = " ".join(q.split()).strip(" ?!.,;:-")
    if not q or len(q) < 2:
        return None

    # Dict rapid pentru reperele din Bucuresti / Ilfov & mari metropole (0 ms latenta)
    FAST_LOOKUP = {
        "las vegas": (36.1699, -115.1398, "Las Vegas Strip"),
        "vegas": (36.1699, -115.1398, "Las Vegas"),
        "new york": (40.7580, -73.9855, "New York City"),
        "nyc": (40.7580, -73.9855, "New York City"),
        "times square": (40.7580, -73.9855, "Times Square NYC"),
        "statue of liberty": (40.7033, -74.0170, "Battery Park (Liberty View)"),
        "sao paulo": (-23.5505, -46.6333, "São Paulo"),
        "mexico city": (19.4326, -99.1332, "Ciudad de México"),
        "craiova": (44.3182, 23.7965, "Centrul Istoric Craiova"),
        "regie": (44.4447, 26.0558, "UPB Regie Campus"),
        "upb": (44.4447, 26.0558, "UPB Regie Campus"),
        "herastrau": (44.4708, 26.0841, "Parcul Herăstrău"),
        "herăstrău": (44.4708, 26.0841, "Parcul Herăstrău"),
        "carol": (44.4150, 26.0963, "Parcul Carol"),
        "parcul carol": (44.4150, 26.0963, "Parcul Carol"),
        "arena": (44.4372, 26.1525, "Arena Națională"),
        "arena nationala": (44.4372, 26.1525, "Arena Națională"),
        "unirii": (44.4273, 26.1030, "Piața Unirii"),
        "piata unirii": (44.4273, 26.1030, "Piața Unirii"),
        "militari": (44.4335, 26.0150, "Militari Residence"),
        "militari residence": (44.4335, 26.0150, "Militari Residence"),
        "voluntari": (44.4920, 26.1910, "Voluntari"),
        "otopeni": (44.5510, 26.0790, "Otopeni"),
        "vacaresti": (44.4022, 26.1289, "Delta Văcărești"),
        "delta vacaresti": (44.4022, 26.1289, "Delta Văcărești"),
        "cismigiu": (44.4361, 26.0906, "Grădina Cișmigiu"),
        "cotroceni": (44.4328, 26.0697, "Cartierul Cotroceni"),
    }

    q_low = q.lower().strip()
    if q_low in FAST_LOOKUP:
        return FAST_LOOKUP[q_low]

    # 1. Photon Komoot API
    try:
        url = f"https://photon.komoot.io/api/?q={urllib.parse.quote(q)}&limit=1"
        with httpx.Client(timeout=2.5, headers=HEADERS) as client:
            res = client.get(url)
            if res.status_code == 200:
                feats = res.json().get("features", [])
                if feats:
                    coords = feats[0]["geometry"]["coordinates"]  # [lon, lat]
                    props = feats[0].get("properties", {})
                    name = props.get("name") or props.get("city") or q.title()
                    return float(coords[1]), float(coords[0]), name
    except Exception as exc:
        logger.debug("Photon failed for '%s': %s", q, exc)

    # 2. OSM Nominatim API
    try:
        nom_url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(q)}&format=json&limit=1"
        with httpx.Client(timeout=3.0, headers=HEADERS) as client:
            res = client.get(nom_url)
            if res.status_code == 200:
                data = res.json()
                if data and len(data) > 0:
                    lat = float(data[0]["lat"])
                    lon = float(data[0]["lon"])
                    name = data[0].get("display_name", q).split(",")[0].strip()
                    return lat, lon, name
    except Exception as exc:
        logger.debug("Nominatim failed for '%s': %s", q, exc)

    return None


def find_nearby_poi(lat: float, lon: float, poi_type: str = "coffee") -> Optional[Tuple[float, float, str]]:
    """Cauta un POI real (cafenea / parc) in apropierea coordonatelor date."""
    search_term = "specialty coffee cafe" if poi_type == "coffee" else "park garden plaza"
    try:
        url = f"https://photon.komoot.io/api/?q={urllib.parse.quote(search_term)}&lat={lat}&lon={lon}&limit=2"
        with httpx.Client(timeout=1.8, headers=HEADERS) as client:
            res = client.get(url)
            if res.status_code == 200:
                feats = res.json().get("features", [])
                for f in feats:
                    c = f["geometry"]["coordinates"]
                    if 0.2 <= _km(lat, lon, float(c[1]), float(c[0])) <= 6.0:
                        name = f.get("properties", {}).get("name")
                        if name:
                            return float(c[1]), float(c[0]), name
    except Exception:
        pass
    return None


# =====================================================================
# 1. SCHEME PYDANTIC V2 (ULTRA-TOLERANTE)
# =====================================================================

class Waypoint(BaseModel):
    name: str = "Waypoint"
    lat: float
    lon: float
    type: str = "stop"

    @model_validator(mode="before")
    @classmethod
    def normalize_coords(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Suport pentru {"coordinates": [lon, lat]}
            if "coordinates" in data and isinstance(data["coordinates"], (list, tuple)) and len(data["coordinates"]) >= 2:
                data.setdefault("lon", data["coordinates"][0])
                data.setdefault("lat", data["coordinates"][1])
            if "lat" not in data and "latitude" in data:
                data["lat"] = data["latitude"]
            if "lon" not in data:
                if "longitude" in data:
                    data["lon"] = data["longitude"]
                elif "lng" in data:
                    data["lon"] = data["lng"]
            if not data.get("name"):
                data["name"] = data.get("label") or data.get("title") or "Scenic Stop"
        return data


class ChillAudioCue(BaseModel):
    name: str = "Tranquil Zone"
    lat: float = 0.0
    lon: float = 0.0
    cue: str = "Drop your shoulders, breathe deeply, and enjoy the smooth cadence."

    @model_validator(mode="before")
    @classmethod
    def normalize_cue(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"name": "Mindful Moment", "lat": 0.0, "lon": 0.0, "cue": data}
        if isinstance(data, dict):
            if not data.get("cue"):
                data["cue"] = data.get("text") or data.get("message") or data.get("script") or "Enjoy the calm surroundings."
        return data


class VibePlan(BaseModel):
    origin: Waypoint
    destination: Waypoint
    intermediate_stops: List[Waypoint] = Field(default_factory=list)
    vibe_title: str = Field(default="Mindful Urban Glide")
    audio_intro: str = Field(default="Starting your mindful ride. Enjoy the calm corridors.")
    avoid_tags: List[str] = Field(default_factory=lambda: ["heavy_traffic", "unshaded_asphalt"])
    chill_cues: List[ChillAudioCue] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_plan(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("vibe_title"):
                data["vibe_title"] = data.get("title") or data.get("route_title") or data.get("name") or "Mindful Urban Glide"
            if not data.get("audio_intro"):
                data["audio_intro"] = data.get("intro") or data.get("audio") or data.get("description") or "Welcome to your mindful ride."
            if "intermediate_stops" not in data:
                data["intermediate_stops"] = data.get("waypoints") or data.get("stops") or []
            if "origin" not in data and "start" in data:
                data["origin"] = data["start"]
            if "destination" not in data and "end" in data:
                data["destination"] = data["end"]
            # Daca LLM-ul a omis destination (ex: loop mode), copiem origin
            if "origin" in data and "destination" not in data:
                data["destination"] = dict(data["origin"]) if isinstance(data["origin"], dict) else data["origin"]
        return data

    def to_geojson_coordinates(self) -> List[List[float]]:
        coords = [[self.origin.lon, self.origin.lat]]
        for stop in self.intermediate_stops:
            coords.append([stop.lon, stop.lat])
        coords.append([self.destination.lon, self.destination.lat])
        return coords

    def sanitize(self, center: Optional[tuple] = None, max_km: float = 25000.0) -> "VibePlan":
        def fix_lat_lon(w):
            if abs(w.lat) > 90 and abs(w.lon) <= 90:
                w.lat, w.lon = w.lon, w.lat
            return w

        self.origin = fix_lat_lon(self.origin)
        self.destination = fix_lat_lon(self.destination)
        self.intermediate_stops = [fix_lat_lon(w) for w in self.intermediate_stops][:4]
        for c in self.chill_cues:
            fix_lat_lon(c)
            if c.lat == 0.0 and c.lon == 0.0:
                c.lat, c.lon = self.origin.lat, self.origin.lon
        return self


# =====================================================================
# 2. PROMPT DE SISTEM GLOBAL
# =====================================================================

SYSTEM_PROMPT = """You are the core AI Routing & Mindfulness Copilot for VibeRide micro-mobility navigation.
You support ANY city, town, or landmark worldwide (e.g., Las Vegas, Bucharest, Craiova, Drobeta-Turnu Severin, Mexico City, Tokyo, Paris).

CRITICAL RULES:
1. Extract the exact city/landmarks requested by the user. NEVER default to Bucharest if another city is mentioned.
2. If the user asks for a general ride in a city (e.g., "ride in Las Vegas", "plimbare in Craiova") or mentions duration, create a scenic loop where destination is close to origin with 2-3 intermediate_stops.
3. If the user mentions coffee/cafe/drink/pitstop, include an intermediate stop with `"type": "coffee"`.
4. Return ONLY a valid JSON object matching this exact structure (no markdown, no prose):
{
  "origin": {"name": "string", "lat": 0.0, "lon": 0.0, "type": "origin"},
  "destination": {"name": "string", "lat": 0.0, "lon": 0.0, "type": "destination"},
  "intermediate_stops": [
    {"name": "string", "lat": 0.0, "lon": 0.0, "type": "coffee | park | fountain | viewpoint"}
  ],
  "vibe_title": "string",
  "audio_intro": "string",
  "avoid_tags": ["heavy_traffic", "unshaded_asphalt"],
  "chill_cues": [
    {"name": "string", "lat": 0.0, "lon": 0.0, "cue": "string"}
  ]
}
"""


# =====================================================================
# 3. AGENT IMPLEMENTATION
# =====================================================================

class VibePlannerAgent:
    MODEL_ID = "meta-models/muse-spark-open-1026"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = (api_key or os.getenv("BASETEN_API_KEY", "")).strip()
        self._client: Optional[OpenAI] = None
        if self.api_key:
            self._client = OpenAI(
                base_url="https://inference.baseten.co/v1",
                api_key=self.api_key,
                timeout=18.0,
                max_retries=0,
            )

    @staticmethod
    def build_fallback_plan(
        user_prompt: str = "",
        city: str = "Bucharest",
        loop_mode: bool = False,
    ) -> VibePlan:
        """
        Fallback inteligent cu NER bilingv (RO/EN), detectie de cafea/POI-uri
        si geocodare globala.
        """
        p_low = (user_prompt or "").lower()

        # Detectam daca utilizatorul vrea cafea / pitstop
        wants_coffee = bool(
            re.search(r"\b(coffe|coffee|cafe|cafea|cafenea|espresso|latte|cappuccino|cortado|pitstop|drink)\b", p_low)
        )
        wants_historic = bool(
            re.search(r"\b(historic|istoric|monument|muzeu|museum|cetate|old\s+town|centru\s+vechi|view)\b", p_low)
        )

        # 1. Extragem locatiile prin motorul NER
        loc_a, loc_b, is_loop_detected = extract_locations_ner(user_prompt)
        is_loop = loop_mode or is_loop_detected

        origin: Optional[Waypoint] = None
        destination: Optional[Waypoint] = None

        if loc_a and loc_b and not is_loop:
            g1 = live_geocode(loc_a)
            g2 = live_geocode(loc_b)
            if g1 and g2:
                origin = Waypoint(name=g1[2], lat=g1[0], lon=g1[1], type="origin")
                destination = Waypoint(name=g2[2], lat=g2[0], lon=g2[1], type="destination")
            elif g1:
                origin = Waypoint(name=g1[2], lat=g1[0], lon=g1[1], type="origin")
                is_loop = True
            elif g2:
                origin = Waypoint(name=g2[2], lat=g2[0], lon=g2[1], type="origin")
                is_loop = True

        if not origin and loc_a:
            g1 = live_geocode(loc_a)
            if g1:
                origin = Waypoint(name=g1[2], lat=g1[0], lon=g1[1], type="origin")

        # Ultima plasa de siguranta: cautam orice oras/locatie din prompt
        if not origin:
            g_any = live_geocode(_strip_conversational_clauses(user_prompt))
            if g_any:
                origin = Waypoint(name=g_any[2], lat=g_any[0], lon=g_any[1], type="origin")

        # Doar daca promptul chiar nu contine nicio locatie valida, folosim Regie -> Herastrau
        if not origin:
            origin = Waypoint(name="UPB Regie Campus", lat=44.4447, lon=26.0558, type="origin")
            destination = Waypoint(name="Parcul Herăstrău", lat=44.4708, lon=26.0841, type="destination")
            is_loop = False

        # 2. Construim opririle intermediare (cu suport pentru Cafea & Obiective)
        stops: List[Waypoint] = []
        primary_stop_type = "coffee" if wants_coffee else ("viewpoint" if wants_historic else "park")

        if is_loop or not destination or origin.name == destination.name:
            # Plasam finish-ul la ~350m de start pentru ca OSRM sa nu returneze ruta de 0 metri
            destination = Waypoint(
                name=f"{origin.name} Promenade Finish",
                lat=round(origin.lat + 0.0032, 4),
                lon=round(origin.lon - 0.0028, 4),
                type="destination",
            )

            # Incercam sa gasim o cafenea reala in zona daca s-a cerut cafea
            coffee_poi = find_nearby_poi(origin.lat, origin.lon, "coffee") if wants_coffee else None
            if coffee_poi:
                stops.append(Waypoint(name=coffee_poi[2], lat=coffee_poi[0], lon=coffee_poi[1], type="coffee"))
            else:
                stops.append(
                    Waypoint(
                        name=f"{origin.name} Specialty Coffee Roasters" if wants_coffee else f"{origin.name} Shaded Promenade",
                        lat=round(origin.lat + 0.0115, 4),
                        lon=round(origin.lon + 0.0095, 4),
                        type=primary_stop_type,
                    )
                )

            stops.extend([
                Waypoint(
                    name=f"{origin.name} Botanical Oasis",
                    lat=round(origin.lat + 0.0165, 4),
                    lon=round(origin.lon - 0.0075, 4),
                    type="park",
                ),
                Waypoint(
                    name=f"{origin.name} Heritage Viewpoint",
                    lat=round(origin.lat + 0.0065, 4),
                    lon=round(origin.lon - 0.0135, 4),
                    type="viewpoint",
                ),
            ])
            title = f"{origin.name} {'Coffee & ' if wants_coffee else ''}Mindful Circuit"
            intro = (
                f"Welcome to {origin.name}. We've planned a relaxed loop with a curated specialty coffee stop along the way."
                if wants_coffee
                else f"Welcome to your mindful loop around {origin.name}. Enjoy the calm streets and green corridors."
            )
        else:
            mid_lat = round((origin.lat + destination.lat) / 2 + 0.0025, 4)
            mid_lon = round((origin.lon + destination.lon) / 2 - 0.0025, 4)

            if wants_coffee:
                coffee_poi = find_nearby_poi(mid_lat, mid_lon, "coffee")
                if coffee_poi:
                    stops.append(Waypoint(name=coffee_poi[2], lat=coffee_poi[0], lon=coffee_poi[1], type="coffee"))
                else:
                    stops.append(Waypoint(name="Artisan Coffee Pitstop", lat=mid_lat, lon=mid_lon, type="coffee"))
            else:
                stops.append(
                    Waypoint(
                        name="Shaded Green Corridor",
                        lat=mid_lat,
                        lon=mid_lon,
                        type=primary_stop_type,
                    )
                )

            title = f"Mindful Glide: {origin.name} to {destination.name}"
            intro = f"Starting your calm ride from {origin.name} towards {destination.name}."

        first_stop = stops[0]

        return VibePlan(
            origin=origin,
            destination=destination,
            intermediate_stops=stops,
            vibe_title=title,
            audio_intro=intro,
            avoid_tags=["heavy_traffic_arterials", "exposed_wind_corridors", "unshaded_asphalt"],
            chill_cues=[
                ChillAudioCue(
                    name=first_stop.name,
                    lat=first_stop.lat,
                    lon=first_stop.lon,
                    cue="Drop your shoulders, breathe in deeply, and enjoy this tranquil segment.",
                )
            ],
        )

    def generate_plan(
        self,
        user_prompt: str,
        city: str = "Bucharest",
        wind_direction_deg: Optional[int] = None,
        time_of_day: str = "sunset",
    ) -> VibePlan:
        # Extragem indicii NER inainte de apelul LLM pentru a nu-l induce in eroare cu default-ul "Bucharest"
        loc_a, loc_b, is_loop = extract_locations_ner(user_prompt)
        detected_context = f"{loc_a} -> {loc_b}" if (loc_a and loc_b) else (loc_a or "Auto-detect from prompt")

        if not self._client:
            return self.build_fallback_plan(user_prompt=user_prompt, city=city, loop_mode=is_loop)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"[Detected Location Context: {detected_context} | Time: {time_of_day}]\n"
                    f"User Ride Request: {user_prompt}\n"
                    "Return valid JSON only."
                ),
            },
        ]

        try:
            logger.info("Requesting plan from %s: '%s' (NER: %s)", self.MODEL_ID, user_prompt, detected_context)
            response = self._client.chat.completions.create(
                model=self.MODEL_ID,
                messages=messages,
                temperature=0.2,
                max_tokens=2500,
            )

            choice = response.choices[0]
            msg = choice.message

            raw_content = getattr(msg, "content", None)
            if not raw_content and hasattr(msg, "reasoning_content"):
                raw_content = msg.reasoning_content
            if not raw_content and hasattr(msg, "reasoning"):
                raw_content = msg.reasoning
            if not raw_content and getattr(msg, "model_extra", None):
                raw_content = msg.model_extra.get("reasoning_content") or msg.model_extra.get("reasoning")

            if not raw_content:
                raise ValueError("Model returned an empty payload.")

            parsed_data = extract_json(raw_content)
            vibe_plan = VibePlan.model_validate(parsed_data).sanitize()

            # Protectie anti-halucinatie: daca utilizatorul a cerut Las Vegas / Craiova / Severin,
            # dar LLM-ul a returnat tot Bucuresti (lat ~44.43, lon ~26.08), suprascriem cu NER fallback!
            if loc_a and loc_a.lower() not in ("bucharest", "bucuresti", "regie", "herastrau", "carol", "unirii", "cotroceni", "cismigiu", "arena", "militari", "otopeni", "voluntari"):
                if _km(vibe_plan.origin.lat, vibe_plan.origin.lon, 44.4328, 26.0841) < 15.0:
                    logger.warning("LLM hallucinated Bucharest for '%s'. Forcing accurate NER geocoding.", loc_a)
                    return self.build_fallback_plan(user_prompt=user_prompt, city=city, loop_mode=is_loop)

            logger.info("Successfully validated VibePlan: '%s'", vibe_plan.vibe_title)
            return vibe_plan

        except Exception as exc:
            underlying = getattr(exc, "__cause__", None)
            logger.error(
                "Failed to generate VibePlan (%s: %s | Cause: %s). Activating smart NER fallback plan.",
                type(exc).__name__,
                exc,
                underlying,
            )
            return self.build_fallback_plan(user_prompt=user_prompt, city=city, loop_mode=is_loop)


def plan_vibe_ride(
    user_prompt: str,
    city: str = "Bucharest",
    wind_direction_deg: Optional[int] = None,
    time_of_day: str = "sunset",
) -> VibePlan:
    planner = VibePlannerAgent()
    return planner.generate_plan(
        user_prompt=user_prompt,
        city=city,
        wind_direction_deg=wind_direction_deg,
        time_of_day=time_of_day,
    )