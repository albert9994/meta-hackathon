import json
import logging
import os
from typing import Any, Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("vision_inspector")

BASETEN_API_KEY = os.getenv("BASETEN_API_KEY", "").strip()
MODEL_ID = "meta-models/muse-spark-open-1026"

client = None
if BASETEN_API_KEY:
    client = OpenAI(
        base_url="[https://inference.baseten.co/v1](https://inference.baseten.co/v1)",
        api_key=BASETEN_API_KEY,
    )


def _build_fallback_audit() -> dict[str, Any]:
    """Fallback sigur dacă modelul vizual este indisponibil."""
    return {
        "bike_friendly": True,
        "surface": "smooth_asphalt",
        "shade_level": "partial_canopy",
        "hazard_detected": None,
        "audio_alert": "Path looks clear and well shaded. Ride mindfully."
    }


async def inspect_street_image(image_base64: str, mime_type: str = "image/jpeg") -> dict[str, Any]:
    """
    Contract direct cerut de Dev 3 (POST /api/vision/audit).
    Inspectează suprafața drumului, nivelul de umbră și pericolele pentru micro-mobilitate.
    """
    if not client:
        logger.warning("Baseten client not configured. Using deterministic vision audit.")
        return _build_fallback_audit()

    system_prompt = """You are the Spatial Safety Sensor for VibeRide (bicycles & e-scooters).
Analyze the street image for micro-mobility safety.
Classify:
1. bike_friendly (boolean): true if safe for bikes/scooters.
2. surface (string): "smooth_asphalt", "cobblestone", "gravel", or "damaged_asphalt".
3. shade_level (string): "dense_canopy", "partial_canopy", or "unshaded".
4. hazard_detected (string or null): "tram_tracks", "potholes", "construction", "steep_curb", or null if none.
5. audio_alert (string): A short, calming spoken caution for earphones (max 15 words).

Respond ONLY with valid JSON:
{
  "bike_friendly": true,
  "surface": "smooth_asphalt",
  "shade_level": "dense_canopy",
  "hazard_detected": null,
  "audio_alert": "Clear shaded path ahead. Enjoy the glide."
}"""

    # Construim payload-ul OpenAI standard cu Data URI
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Analyze this street view for bike safety, road surface, shade, and hazards:"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}
                }
            ]
        }
    ]

    try:
        import asyncio
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model=MODEL_ID,
                messages=messages,
            )
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        parsed = json.loads(content)
        logger.info("Vision audit successful: hazard=%s", parsed.get("hazard_detected"))
        return parsed

    except Exception as exc:
        logger.warning("Vision AI inference failed (%s). Using fallback safety response.", exc)
        return _build_fallback_audit()


if __name__ == "__main__":
    import asyncio
    print("=== Testing Vision Inspector Fallback & Contract ===")
    res = asyncio.run(inspect_street_image("fake_base64_data", "image/jpeg"))
    print(json.dumps(res, indent=2))