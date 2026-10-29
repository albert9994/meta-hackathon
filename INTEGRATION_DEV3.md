# Dev 3 integration notes (`feature/community-ui`)

## 1. Backend wiring

Add to `backend/requirements.txt` (skip what is already there):

```
fastapi
uvicorn[standard]
pydantic>=2
httpx
python-multipart   # needed for multipart uploads on /api/vision/audit
openai
```

In `backend/main.py`:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

from backend.core import database
from backend.routes.community_routes import router as community_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()          # creates tables, purges expired hazards
    yield


app = FastAPI(title="VibeRide", lifespan=lifespan)   # keep your existing app/lifespan if you have one
app.include_router(community_router)
```

Run from the **repo root** (the imports are `backend.…`):

```
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Add `backend/viberide.db*` to `.gitignore`. Override the path with `VIBERIDE_DB_PATH`.

## 2. What I need from Dev 1 (agents)

Sync or async, returning a dict or a JSON string. Names are two constants at the top of
`community_routes.py` if you want different ones.

```python
# backend/agents/vision_inspector.py
async def inspect_street_image(image_base64: str, mime_type: str) -> dict
#   -> {"bike_friendly", "surface", "shade_level", "hazard_detected", "audio_alert"}
#   image_base64 has no "data:" prefix; mime_type is image/jpeg | image/png | image/webp

# backend/agents/storyteller.py
async def generate_ride_story(route_title: str, distance_km: float,
                              duration_min: float, vibe_preset: str) -> dict
#   -> {"recap_text", "quiz": {question, options[3], correct_index, fun_fact}, "badge": {title, lore}}
```

* `/api/ride/finish` never fails because of the AI: invalid or missing parts are replaced by built-in
  fallbacks (recap, quiz, badge). Stats are always computed server-side.
* `/api/vision/audit` returns 503/504/502 if the scanner is unavailable, slow or invalid, because a fake
  safety verdict would be worse than none.

## 3. Endpoints (Section 4 contract + two additive ones)

| Method | Path | Notes |
|---|---|---|
| POST | `/api/vision/audit` | multipart `file` **or** JSON `{image_base64}`; optional `lat`/`lon` (opt-in, stored rounded to ~11 m, anonymous, expires after 30 days) |
| POST | `/api/ride/finish` | `crew_code` optional; without it nothing is stored. Retried identical submissions within 60 s are not double counted |
| GET | `/api/feed` | `?crew=&limit=&before_id=`; without `crew` only public posts |
| **POST** | `/api/feed` | *new*: `{user_name, caption?, image_base64?, badge_title?, stats?, crew_code?}` → `{id}` |
| GET | `/api/leaderboard` | `?scope=weekly\|all_time&crew=CODE` (crew required, rankings are private) → array of `{rank, user_name, total_km, ride_count, badge_title, badge_lore}` |
| **GET** | `/api/hazards` | *new*: anonymous hazard pins for the map layer, optional bbox `min_lat,max_lat,min_lon,max_lon` |

## 4. Mobile

```
mobile/.env          EXPO_PUBLIC_API_URL=http://192.168.X.X:8000   (laptop LAN IP; restart Expo after editing)
npx expo install expo-image-picker expo-location expo-speech react-native-maps
```

New shared files: `mobile/utils/api.js` (fetch + timeout + typed helpers incl. `planRoute` for Dev 2's flow)
and `mobile/utils/theme.js`.

```jsx
<SearchHUD city="Bucharest" onRoutePlanned={(data) => setRoute(data)} />

<VisionAuditModal visible={scanOpen} onClose={() => setScanOpen(false)}
                  coords={coords}                       // optional, only uploaded if the rider opts in
                  onResult={(r) => speak(r.audio_alert)} />   // speak = Dev 2's utils/audio.js

<EndRideModal visible={!!finishedRide} ride={finishedRide}      // exact /api/ride/finish request body
              onClose={() => setFinishedRide(null)} />

<Leaderboard crewCode={crew} currentUser={name} refreshKey={rideCount} />
```

Android emulators/phones can't use `localhost`; HEIC photos are not accepted (JPEG/PNG/WebP only), which
is what `expo-image-picker` returns by default.
