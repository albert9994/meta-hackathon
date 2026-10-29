import json
import logging
import os
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("vibe_planner")


# =====================================================================
# 1. PYDANTIC V2 DATA CONTRACTS
# =====================================================================

class Waypoint(BaseModel):
    name: str = Field(..., description="Name of the urban landmark or stop")
    lat: float = Field(..., ge=-90.0, le=90.0, description="GPS latitude")
    lon: float = Field(..., ge=-180.0, le=180.0, description="GPS longitude")
    type: str = Field(
        default="stop",
        description="Type: origin, destination, coffee, park, fountain, viewpoint, etc.",
    )


class ChillAudioCue(BaseModel):
    name: str = Field(..., description="Name of the green zone or tranquil point")
    lat: float = Field(..., ge=-90.0, le=90.0, description="GPS latitude trigger")
    lon: float = Field(..., ge=-180.0, le=180.0, description="GPS longitude trigger")
    cue: str = Field(
        ...,
        description="Short spoken text (10-15 seconds) with a calming/mindful tone for earphones",
    )


class VibePlan(BaseModel):
    origin: Waypoint = Field(..., description="Starting point")
    destination: Waypoint = Field(..., description="End point (identical to origin in Loop Mode)")
    intermediate_stops: list[Waypoint] = Field(
        default_factory=list,
        description="Relaxing waypoints (drinking fountains, specialty coffee, parks, viewpoints)",
    )
    vibe_title: str = Field(..., description="Creative, peaceful title of the route")
    audio_intro: str = Field(
        ...,
        description="Welcome audio message synthesized at the start of the ride",
    )
    avoid_tags: list[str] = Field(
        default_factory=list,
        description="GIS avoidance tags: exposed_wind_corridors, headwind_boulevards, cobblestones, etc.",
    )
    chill_cues: list[ChillAudioCue] = Field(
        default_factory=list,
        description="Geolocated mindful audio cues along the route",
    )


# =====================================================================
# 2. SYSTEM PROMPT & ANCHORS
# =====================================================================

SYSTEM_PROMPT = """You are the core AI Routing & Mindfulness Copilot for VibeRide, an urban micro-mobility navigation system (bicycles & e-scooters) focused strictly on calm, shade, low-stress streets, and sensory mindfulness (NEVER speed, fitness, or aggressive commuting).

### CORE ROUTING & VIBE RULES:
1. Point-to-Point vs. Loop Mode:
- If the user specifies both origin and destination, plan a smooth path between them using quiet, tree-lined streets and parks.
- LOOP MODE: If the user requests a timed or destination-free ride (e.g., "a 30-minute chill ride", "an evening loop from a specific location"), set destination to the exact same coordinates and name as origin, and populate intermediate_stops with 2 to 4 scenic waypoints that form a circular loop.

2. Headwind Nullifier & Environmental Shield (avoid_tags):
- Protect the rider from micro-mobility stressors.
- Include appropriate tags such as:
- "exposed_wind_corridors", "headwind_boulevards" (Headwind Nullifier)
- "sunset_west_glare", "unshaded_asphalt", "heavy_traffic_arterials" (Environmental Shield)
- "cobblestones", "tram_tracks", "degraded_pavement" (Surface Shield)

3. Relaxation Stops (intermediate_stops):
- Add restorative stops matching the user's intent: drinking water fountains ("fountain"), specialty coffee ("coffee"), shaded parks ("park"), or viewpoints ("viewpoint").

4. Geolocated Mindfulness (chill_cues):
- Generate 2 to 3 chill_cues along green or quiet sections of the path.
- Each cue must be a 25-45 word script (10-15 seconds of spoken audio in English), prompting the rider to drop their shoulders, breathe deeply, or appreciate the canopy shade.

### ANCHOR LANDMARKS (BUCHAREST REFERENCE):
When routing in Bucharest, use accurate coordinates anchored around these verified locations:
- UPB Regie: lat 44.4447, lon 26.0558
- Cotroceni (Historic Residential Quarter): lat 44.4328, lon 26.0697
- Carol Park: lat 44.4150, lon 26.0963
- Cismigiu Gardens: lat 44.4361, lon 26.0906
- King Mihai I Park (Herastrau): lat 44.4708, lon 26.0841
- Origo Coffee Shop: lat 44.4342, lon 26.0976

If another global city is requested (e.g., Amsterdam, Paris, Austin, Tokyo), resolve valid GPS coordinates for calm parks and cafes in that specific city.

### OUTPUT CONTRACT:
Respond ONLY with a valid JSON object matching this schema (no markdown formatting, no explanatory prose):
{
  "origin": {"name": "string", "lat": 0.0, "lon": 0.0, "type": "origin"},
  "destination": {"name": "string", "lat": 0.0, "lon": 0.0, "type": "destination"},
  "intermediate_stops": [
    {"name": "string", "lat": 0.0, "lon": 0.0, "type": "coffee | park | fountain | viewpoint"}
  ],
  "vibe_title": "string",
  "audio_intro": "string",
  "avoid_tags": ["string"],
  "chill_cues": [
    {"name": "string", "lat": 0.0, "lon": 0.0, "cue": "string"}
  ]
}
"""


# =====================================================================
# 3. AGENT IMPLEMENTATION
# =====================================================================

class VibePlannerAgent:
    """
    Autonomous agent generating tranquil micro-mobility routes (VibePlan)
    powered by meta-models/muse-spark-open-1026 hosted on Baseten.
    """

    MODEL_ID = "meta-models/muse-spark-open-1026"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = (api_key or os.getenv("BASETEN_API_KEY", "")).strip()

        self._client: Optional[OpenAI] = None
        if self.api_key:
            # Client identic cu cel functional din backend/main.py
            self._client = OpenAI(
                base_url="https://inference.baseten.co/v1",
                api_key=self.api_key,
            )
        else:
            logger.warning(
                "BASETEN_API_KEY is not set in environment. Falling back to local deterministic plan."
            )

    @staticmethod
    def build_fallback_plan(
        user_prompt: str = "",
        city: str = "Bucharest",
        loop_mode: bool = False,
    ) -> VibePlan:
        """
        Returns a deterministic, production-safe VibePlan if Baseten is
        unreachable or returns malformed output.
        """
        is_loop = loop_mode or any(
            kw in user_prompt.lower()
            for kw in ["loop", "minute", "circular", "roundtrip", "no destination"]
        )

        origin_wp = Waypoint(
            name="Cotroceni - Elefterie Square",
            lat=44.4328,
            lon=26.0697,
            type="origin",
        )

        if is_loop:
            dest_wp = Waypoint(
                name="Cotroceni - Elefterie Square",
                lat=44.4328,
                lon=26.0697,
                type="destination",
            )
            vibe_title = "Cotroceni Canopy & Cismigiu Shaded Loop"
            audio_intro = (
                "Route set. We are heading on a tranquil loop through historic Cotroceni, "
                "bypassing windy boulevards under old linden trees."
            )
        else:
            dest_wp = Waypoint(
                name="Carol Park - Main Esplanade",
                lat=44.4150,
                lon=26.0963,
                type="destination",
            )
            vibe_title = "Cotroceni Shaded Corridors to Carol Park"
            audio_intro = (
                "Welcome to VibeRide. We will navigate through quiet residential streets "
                "into the park canopy, avoiding heavy traffic axes."
            )

        return VibePlan(
            origin=origin_wp,
            destination=dest_wp,
            intermediate_stops=[
                Waypoint(
                    name="Doctor Lister Public Fountain",
                    lat=44.4335,
                    lon=26.0715,
                    type="fountain",
                ),
                Waypoint(
                    name="Cismigiu Gardens Magnolia Path",
                    lat=44.4361,
                    lon=26.0906,
                    type="park",
                ),
                Waypoint(
                    name="Origo Specialty Coffee",
                    lat=44.4342,
                    lon=26.0976,
                    type="coffee",
                ),
            ],
            vibe_title=vibe_title,
            audio_intro=audio_intro,
            avoid_tags=[
                "exposed_wind_corridors",
                "sunset_west_glare",
                "cobblestones",
                "tram_tracks",
                "heavy_traffic_arterials",
            ],
            chill_cues=[
                ChillAudioCue(
                    name="Cotroceni Tree Canopy",
                    lat=44.4332,
                    lon=26.0704,
                    cue=(
                        "Drop your shoulders and loosen your grip on the handlebars. "
                        "The wind is blocked by the tree canopy here. Take a deep breath."
                    ),
                ),
                ChillAudioCue(
                    name="Cismigiu Lake Oasis",
                    lat=44.4365,
                    lon=26.0912,
                    cue=(
                        "Ease your pedaling cadence. Enjoy the reflection of trees on the water "
                        "and let the city noise fade behind you."
                    ),
                ),
            ],
        )

    def generate_plan(
        self,
        user_prompt: str,
        city: str = "Bucharest",
        wind_direction_deg: Optional[int] = None,
        time_of_day: str = "sunset",
    ) -> VibePlan:
        """
        Generates and validates a VibePlan using Meta Muse Spark on Baseten.
        """
        if not self._client:
            logger.info("Baseten client not configured. Serving fallback plan.")
            return self.build_fallback_plan(user_prompt=user_prompt, city=city)

        environmental_context = (
            f"City: {city} | Time of day: {time_of_day} | "
            f"Wind direction (deg): {wind_direction_deg if wind_direction_deg is not None else 'calm/variable'}"
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"[Environmental Context: {environmental_context}]\n"
                    f"User Ride Request: {user_prompt}"
                ),
            },
        ]

        try:
            logger.info("Requesting plan from %s: '%s'", self.MODEL_ID, user_prompt)
            # Apel direct, identic cu main.py
            response = self._client.chat.completions.create(
                model=self.MODEL_ID,
                messages=messages,
            )

            raw_content = response.choices[0].message.content
            if not raw_content:
                raise ValueError("Model returned an empty payload.")

            cleaned = raw_content.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                cleaned = "\n".join(lines).strip()

            parsed_json = json.loads(cleaned)
            vibe_plan = VibePlan.model_validate(parsed_json)
            logger.info("Successfully validated VibePlan: '%s'", vibe_plan.vibe_title)
            return vibe_plan

        except Exception as exc:
            underlying = getattr(exc, "__cause__", None)
            logger.error(
                "Failed to generate VibePlan (%s: %s | Cause: %s). Activating fallback plan.",
                type(exc).__name__,
                exc,
                underlying,
            )
            return self.build_fallback_plan(user_prompt=user_prompt, city=city)


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


# =====================================================================
# 4. CLI LOCAL VALIDATION
# =====================================================================

if __name__ == "__main__":
    print("=== VibeRide AI Planner - Test Execution (Branch: feature/ai-agents) ===")

    agent = VibePlannerAgent()

    # Test 1: Point A -> Point B ride at sunset with wind & glare shield
    prompt_ab = (
        "Take me on a calm sunset ride from UPB Regie to Carol Park. "
        "Avoid direct sun glare, rough cobblestone, and stop for water and specialty coffee at Origo."
    )
    print(f"\n[Test 1 - Point A to B] Prompt: {prompt_ab}")
    plan_ab = agent.generate_plan(
        user_prompt=prompt_ab,
        city="Bucharest",
        wind_direction_deg=270,
        time_of_day="sunset",
    )
    print(plan_ab.model_dump_json(indent=2))

    # Test 2: Loop Mode (35-minute circular scenic ride)
    prompt_loop = (
        "I have 35 minutes for a relaxed circular ride starting from Cotroceni, "
        "sticking to quiet shaded streets and Cismigiu."
    )
    print(f"\n[Test 2 - Loop Mode] Prompt: {prompt_loop}")
    plan_loop = agent.generate_plan(
        user_prompt=prompt_loop,
        city="Bucharest",
        wind_direction_deg=90,
        time_of_day="late_afternoon",
    )
    print(plan_loop.model_dump_json(indent=2))