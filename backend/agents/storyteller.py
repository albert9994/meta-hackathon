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
logger = logging.getLogger("storyteller")


# =====================================================================
# 1. PYDANTIC V2 DATA CONTRACTS
# =====================================================================

class ZenMetrics(BaseModel):
    zen_score: int = Field(..., ge=0, le=100, description="Overall calmness score from 0 to 100")
    canopy_shade_pct: int = Field(..., ge=0, le=100, description="Percentage of ride under tree canopy")
    decibels_avoided_est_db: float = Field(
        ...,
        description="Estimated acoustic stress / traffic noise avoided compared to main boulevards",
    )
    wind_stress_nullified_km: float = Field(
        ...,
        description="Kilometers ridden in sheltered alleys instead of open headwind corridors",
    )
    mindful_badge: str = Field(
        ...,
        description="Poetic anti-Strava achievement title (e.g., 'Canopy Glider', 'Wind Whisperer')",
    )


class ZenRecap(BaseModel):
    vibe_title: str = Field(..., description="Evocative summary title of the completed journey")
    metrics: ZenMetrics = Field(..., description="Quantified serenity & mindful impact")
    story_narrative: str = Field(
        ...,
        description="2-3 soothing, reflective paragraphs capturing the sensory memory of the ride",
    )
    closing_mantra: str = Field(
        ...,
        description="A short grounding closing phrase for the rider (1 sentence)",
    )


# =====================================================================
# 2. SYSTEM PROMPT
# =====================================================================

STORYTELLER_SYSTEM_PROMPT = """You are the Zen Storyteller for VibeRide, an urban micro-mobility companion celebrating mindful, low-stress riding through the city.

### YOUR OBJECTIVES:
1. **Serenity Metrics (ZenMetrics)**:
   - Compute realistic, grounding metrics:
     - `zen_score`: 85-98.
     - `canopy_shade_pct`: estimate 70-90% for routes with parks and quiet residential quarters.
     - `decibels_avoided_est_db`: estimate acoustic reduction (15.0 to 24.0 dB quieter than boulevards).
     - `wind_stress_nullified_km`: sheltered distance in kilometers (e.g., 3.0 to 6.5 km).
     - `mindful_badge`: award elegant, peaceful titles (e.g., 'Canopy Glider', 'Amber Shadow Drifter', 'Quiet Lane Nomad').

2. **Concise Sensory Narrative**:
   - Write ONLY 1 or 2 SHORT paragraphs (total 50 to 75 words maximum) capturing the memory of the ride.
   - Designed for a mobile screen card: keep it punchy, poetic, and grounded.
   - Mention real sensory anchors: dappled light through old trees, shelter from the wind, the water pause, and the quiet rhythm of the wheels.
   - NEVER mention, attack, or reference Strava, speed metrics, or competing apps. Focus purely on presence, peace, and the urban green corridor.

3. **Language**:
   - Match the rider's language (English by default, or other if requested).

### OUTPUT CONTRACT:
Respond strictly with a valid JSON object matching this schema:
{
  "vibe_title": "string",
  "metrics": {
    "zen_score": 92,
    "canopy_shade_pct": 82,
    "decibels_avoided_est_db": 19.5,
    "wind_stress_nullified_km": 4.5,
    "mindful_badge": "string"
  },
  "story_narrative": "string",
  "closing_mantra": "string"
}
"""


# =====================================================================
# 3. AGENT IMPLEMENTATION
# =====================================================================

class StorytellerAgent:
    """
    Synthesizes sensory post-ride recaps and serenity metrics
    powered by meta-models/muse-spark-open-1026 on Baseten.
    """

    MODEL_ID = "meta-models/muse-spark-open-1026"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = (api_key or os.getenv("BASETEN_API_KEY", "")).strip()

        self._client: Optional[OpenAI] = None
        if self.api_key:
            self._client = OpenAI(
                base_url="https://inference.baseten.co/v1",
                api_key=self.api_key,
            )
        else:
            logger.warning("BASETEN_API_KEY is missing. Falling back to deterministic recap.")

    @staticmethod
    def build_fallback_recap(vibe_title: str = "Cotroceni Canopy Drift") -> ZenRecap:
        """
        Deterministic, production-safe fallback recap if LLM is offline.
        """
        return ZenRecap(
            vibe_title=f"The Serene Archive: {vibe_title}",
            metrics=ZenMetrics(
                zen_score=94,
                canopy_shade_pct=82,
                decibels_avoided_est_db=21.4,
                wind_stress_nullified_km=3.8,
                mindful_badge="Linden Canopy Drifter",
            ),
            story_narrative=(
                "You left behind the blare of traffic along the central avenues, choosing instead "
                "the dappled light beneath the old villa trees of Cotroceni. While the city rushed, "
                "your wheels rolled softly over shaded asphalt, shielded from both the headwind and "
                "the evening glare.\n\n"
                "A pause at the stone water fountain broke the rhythm of the city's pulse, replacing "
                "urgency with presence. By the time Carol Park opened its green arms before you, "
                "the ride had ceased to be about getting somewhere and became about simply being."
            ),
            closing_mantra="You carried the quiet of the trees all the way to your doorstep.",
        )

    def generate_recap(
        self,
        vibe_title: str,
        origin_name: str,
        destination_name: str,
        stops_visited: list[str],
        hazards_avoided: list[str],
        ride_duration_min: int = 35,
    ) -> ZenRecap:
        """
        Generates sensory post-ride recap based on journey telemetry.
        """
        if not self._client:
            logger.info("Baseten client not configured. Serving fallback recap.")
            return self.build_fallback_recap(vibe_title)

        journey_context = {
            "title": vibe_title,
            "origin": origin_name,
            "destination": destination_name,
            "stops_visited": stops_visited,
            "hazards_nullified": hazards_avoided,
            "duration_minutes": ride_duration_min,
        }

        messages = [
            {"role": "system", "content": STORYTELLER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Generate a Zen Recap for this completed ride:\n{json.dumps(journey_context, indent=2)}",
            },
        ]

        try:
            logger.info("Generating Zen Recap for '%s'...", vibe_title)
            response = self._client.chat.completions.create(
                model=self.MODEL_ID,
                messages=messages,
            )

            raw_content = response.choices[0].message.content
            if not raw_content:
                raise ValueError("Model returned empty payload.")

            cleaned = raw_content.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                cleaned = "\n".join(lines).strip()

            parsed = json.loads(cleaned)
            recap = ZenRecap.model_validate(parsed)
            logger.info("Successfully validated ZenRecap: badge='%s'", recap.metrics.mindful_badge)
            return recap

        except Exception as exc:
            underlying = getattr(exc, "__cause__", None)
            logger.error(
                "Failed to generate ZenRecap (%s: %s | Cause: %s). Activating fallback.",
                type(exc).__name__,
                exc,
                underlying,
            )
            return self.build_fallback_recap(vibe_title)


# Helper function for FastAPI / Orchestrator integration
def create_zen_recap(
    vibe_title: str,
    origin_name: str,
    destination_name: str,
    stops_visited: list[str],
    hazards_avoided: list[str],
    ride_duration_min: int = 35,
) -> ZenRecap:
    agent = StorytellerAgent()
    return agent.generate_recap(
        vibe_title=vibe_title,
        origin_name=origin_name,
        destination_name=destination_name,
        stops_visited=stops_visited,
        hazards_avoided=hazards_avoided,
        ride_duration_min=ride_duration_min,
    )


# =====================================================================
# 4. CLI LOCAL VALIDATION
# =====================================================================

if __name__ == "__main__":
    print("=== VibeRide Storyteller - Test Execution (Branch: feature/ai-agents) ===")

    agent = StorytellerAgent()

    test_recap = agent.generate_recap(
        vibe_title="Sunset Shade Glide: Regie to Carol Park",
        origin_name="UPB Regie Student Quarter",
        destination_name="Carol Park Esplanade",
        stops_visited=["Cismigiu Drinking Fountain", "Origo Specialty Coffee"],
        hazards_avoided=["sunset_west_glare", "exposed_headwind", "arterial_traffic_noise"],
        ride_duration_min=42,
    )

    print("\n[Resulting Zen Recap Payload]:")
    print(test_recap.model_dump_json(indent=2))