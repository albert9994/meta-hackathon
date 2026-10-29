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
logger = logging.getLogger("voice_copilot")


# =====================================================================
# 1. PYDANTIC V2 DATA CONTRACTS
# =====================================================================

class CopilotAction(BaseModel):
    action_type: str = Field(
        default="none",
        description="Type of action: report_hazard, reroute_calm, find_amenity, mindfulness_cue, or general_query",
    )
    reroute_needed: bool = Field(
        default=False,
        description="True if route recalculation is necessary",
    )
    avoid_tag: Optional[str] = Field(
        default=None,
        description="GIS avoidance tag if hazard reported (e.g. exposed_wind, rough_surface, traffic_surge, sun_glare)",
    )
    target_amenity: Optional[str] = Field(
        default=None,
        description="Requested pitstop if applicable (fountain, coffee, shade, bench, park)",
    )


class VoiceCopilotResponse(BaseModel):
    intent: str = Field(..., description="Detected user intent in 2-3 words")
    action: CopilotAction = Field(..., description="Action payload for navigation engine")
    spoken_response: str = Field(
        ...,
        description="Concise, soothing spoken feedback (1-2 sentences, max 30 words) crafted for earphones",
    )


# =====================================================================
# 2. SYSTEM PROMPT
# =====================================================================

COPILOT_SYSTEM_PROMPT = """You are the real-time Voice Copilot for VibeRide, a mindful urban micro-mobility companion for bicycle and e-scooter riders.
The rider speaks to you hands-free via earphones while moving through the city.

### YOUR RULES OF ENGAGEMENT:
1. **Safety & Brevity First**:
   - The rider is in traffic. Spoken responses MUST be concise, calm, and reassuring (1 to 2 short sentences, maximum 25-30 words).
   - Never output bullet points, markdown formatting, or verbose instructions in `spoken_response`.

2. **Intent Classification & Tag Mapping**:
   - If the rider reports a stressor (wind, road glare, heavy cars, cobblestones, steep hill):
     - Set `action.reroute_needed = true`
     - Set `action.action_type = "report_hazard"`
     - Map to a standard tag in `action.avoid_tag` (e.g., "exposed_wind", "rough_surface", "traffic_surge", "sunset_west_glare").
   - If the rider needs a rest stop (water, coffee, shade):
     - Set `action.reroute_needed = true`
     - Set `action.action_type = "find_amenity"`
     - Set `action.target_amenity` to "fountain", "coffee", "shade", or "bench".
   - If the rider feels anxious or stressed:
     - Set `action.action_type = "mindfulness_cue"`
     - Provide a short calming grounding phrase (drop shoulders, steady breath).

3. **Language Matching**:
   - Output `spoken_response` in the same language the rider used (English, Romanian, etc.).

### OUTPUT CONTRACT:
Respond strictly with a JSON object matching this schema:
{
  "intent": "string",
  "action": {
    "action_type": "report_hazard | reroute_calm | find_amenity | mindfulness_cue | general_query",
    "reroute_needed": true,
    "avoid_tag": "string or null",
    "target_amenity": "string or null"
  },
  "spoken_response": "string"
}
"""


# =====================================================================
# 3. AGENT IMPLEMENTATION
# =====================================================================

class VoiceCopilotAgent:
    """
    Handles hands-free voice interactions, hazard tagging, and rapid spoken feedback
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
            logger.warning(
                "BASETEN_API_KEY is not set. Falling back to deterministic copilot responses."
            )

    @staticmethod
    def build_fallback_response(user_utterance: str) -> VoiceCopilotResponse:
        """
        Deterministic, safety-first fallback if Baseten is unreachable.
        """
        lower = user_utterance.lower()
        if any(w in lower for w in ["water", "sete", "apa", "cișmea", "fountain"]):
            return VoiceCopilotResponse(
                intent="find_drinking_water",
                action=CopilotAction(
                    action_type="find_amenity",
                    reroute_needed=True,
                    target_amenity="fountain",
                ),
                spoken_response="Locating the nearest public drinking fountain on a shaded side street. Hang tight.",
            )
        if any(w in lower for w in ["wind", "vant", "vânt", "glare", "soare", "gropi", "cobblestone"]):
            return VoiceCopilotResponse(
                intent="report_route_hazard",
                action=CopilotAction(
                    action_type="report_hazard",
                    reroute_needed=True,
                    avoid_tag="rough_surface_or_wind",
                ),
                spoken_response="Noted the rough conditions. Rerouting onto a sheltered residential lane ahead.",
            )
        return VoiceCopilotResponse(
            intent="mindful_guidance",
            action=CopilotAction(action_type="mindfulness_cue", reroute_needed=False),
            spoken_response="Keep your shoulders relaxed and stay present. I am keeping watch on your route.",
        )

    def process_voice_input(
        self,
        user_utterance: str,
        current_street: Optional[str] = None,
    ) -> VoiceCopilotResponse:
        """
        Interprets rider utterance and returns structured actions and spoken audio text.
        """
        if not self._client:
            logger.info("Baseten client not initialized. Using fallback copilot logic.")
            return self.build_fallback_response(user_utterance)

        context_info = f"Current rider street: {current_street or 'moving on route'}"
        messages = [
            {"role": "system", "content": COPILOT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"[{context_info}]\nRider said: \"{user_utterance}\"",
            },
        ]

        try:
            logger.info("Processing voice input: '%s'", user_utterance)
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

            parsed = json.loads(cleaned)
            copilot_res = VoiceCopilotResponse.model_validate(parsed)
            logger.info("VoiceCopilot classified intent: '%s'", copilot_res.intent)
            return copilot_res

        except Exception as exc:
            underlying = getattr(exc, "__cause__", None)
            logger.error(
                "Failed to process voice input (%s: %s | Cause: %s). Using fallback.",
                type(exc).__name__,
                exc,
                underlying,
            )
            return self.build_fallback_response(user_utterance)


# Helper function for FastAPI / Orchestrator integration
def handle_rider_voice(user_utterance: str, current_street: Optional[str] = None) -> VoiceCopilotResponse:
    copilot = VoiceCopilotAgent()
    return copilot.process_voice_input(user_utterance=user_utterance, current_street=current_street)


# =====================================================================
# 4. CLI LOCAL VALIDATION
# =====================================================================

if __name__ == "__main__":
    print("=== VibeRide Voice Copilot - Test Execution (Branch: feature/ai-agents) ===")

    agent = VoiceCopilotAgent()

    # Scenario 1: Hazard reporting (wind and blinding glare)
    hazard_query = "There's intense headwind and heavy traffic here, find me a quiet alley."
    print(f"\n[Test 1 - Hazard Report] Utterance: \"{hazard_query}\"")
    res1 = agent.process_voice_input(hazard_query, current_street="Bulevardul Eroilor")
    print(res1.model_dump_json(indent=2))

    # Scenario 2: Spontaneous hydration pitstop
    amenity_query = "I'm exhausted and need water, is there a public fountain nearby?"
    print(f"\n[Test 2 - Amenity Search] Utterance: \"{amenity_query}\"")
    res2 = agent.process_voice_input(amenity_query, current_street="Strada Doctor Lister")
    print(res2.model_dump_json(indent=2))

    # Scenario 3: Grounding / Stress Check
    stress_query = "This intersection was chaotic, I feel pretty tense right now."
    print(f"\n[Test 3 - Mindful Grounding] Utterance: \"{stress_query}\"")
    res3 = agent.process_voice_input(stress_query)
    print(res3.model_dump_json(indent=2))
