# VibeRide

**A calm, privacy-first navigation co-pilot for cyclists and e-scooter riders.**

Mapping apps optimise for the fastest route, which for someone on two wheels often means noisy multi-lane boulevards, exhaust and heavy traffic just to save a minute. VibeRide optimises for how a ride *feels*: tree-shaded streets, quiet alleys, historic neighbourhoods and green loops, with traffic avoided wherever possible.

Distance is framed as **Mindful Miles / Traffic Avoided**. VibeRide is not a fitness tracker or a racing app.

---

## What it does

### Plan a route in your own words
Type a sentence such as *"From UPB Regie to Carol Park through shady streets, stop for specialty coffee"* and pick a vibe preset (**Green & Shady**, **Historic & Chill**, **Pitstop Edition**). An AI planner turns the request into an origin, a destination, optional stops (coffee, parks, viewpoints) and routing preferences. The route is then calculated on a cycling profile that avoids highways, and drawn on the map.

It works in any city covered by OpenStreetMap. The interface and the AI prompts are in English by default.

### Street Scan
Tap **Audit Road** and photograph the path ahead. A multimodal vision model checks the surface (smooth asphalt, cobblestone, cracked pavement, gravel), the shade level and hazards such as tram tracks, potholes, blocked lanes or construction, then returns a short warning that can be read aloud into the rider's earphones.

If the rider opts in, a detected hazard is added to an **anonymous community hazard map**. The photo is never stored.

### Ride recap, quiz and badges
When a ride ends, the rider gets distance, time and average speed, a short AI-written recap, a three-option urban trivia question and a creative **badge** with a line of lore (for example *The Shade Cartographer*, *The Cortado Commuter*, *Zen Drifter*). Badges celebrate ride style and calm, never performance.

### Friend crews and feed
Riders can join a private **crew** with a shared code, rank by mindful kilometres (weekly or all-time) with their latest badge shown next to their name, and share a ride photo to a community feed.

---

## Privacy by design

| What | How it is handled |
|---|---|
| Location history | Never stored. A route exists only in memory while it is used. |
| Finished rides | Only the aggregate distance is added to the rider's crew totals, and only if a crew code was entered. Solo rides store nothing. |
| Street Scan photos | Sent to the vision model and discarded. Never written to the database. |
| Hazard reports | Anonymous: no name, no photo. Coordinates are rounded to about 11 m. Reports expire after 30 days. Sharing is opt-in. |
| Feed posts | Stored only when the rider chooses to post. A post with a crew code is visible to that crew only. |
| Profiles | No advertising profiles, no tracking, no analytics identifiers. |

Known limitation: there is no authentication. Names are self-declared and a crew code works as a shared secret, so treat crew codes like a private invite link.

---

## How it works

```
 ┌────────────────────────────┐            ┌─────────────────────────────────────────┐
 │  Mobile app (Expo / RN)    │   HTTP     │  Backend (FastAPI)                       │
 │  search, map, street scan, │ ─────────► │  routes/   navigation + community        │
 │  end-ride, leaderboard,    │            │  agents/   planner, vision, storyteller  │
 │  feed                      │ ◄───────── │  core/     routing + SQLite              │
 └────────────────────────────┘            └──────────┬──────────────────┬───────────┘
                                                      │                  │
                                      Muse Spark (Baseten API)    OpenRouteService
                                      OpenAI-compatible SDK       (fallback: OSM bike routing)
```

- **Semantic planner** – natural language in, structured JSON out (origin, destination, stops, avoid tags, a one-line audio intro).
- **Routing** – OpenRouteService with a cycling profile and `avoid_features: ["highways"]`, falling back automatically to the public OpenStreetMap bike routing service.
- **Vision inspector** – multimodal analysis of a street photo into a fixed JSON safety report.
- **Storyteller** – recap, quiz and badge for a finished ride. If the model is unavailable the backend falls back to built-in text, so a ride can always be finished.
- **Coordinates** – GeoJSON and ORS use `[longitude, latitude]`; the map library uses `{ latitude, longitude }`. The conversion happens at the backend boundary.

### Tech stack

| Layer | Technology |
|---|---|
| AI model | Meta Muse Spark (`meta-models/muse-spark-open-1026`) through the Baseten OpenAI-compatible API |
| Backend | Python 3.11+, FastAPI, Uvicorn, Pydantic v2, HTTPX, SQLite |
| Mobile | React Native with Expo, `react-native-maps`, `expo-speech`, `expo-image-picker`, `expo-location`, `expo-image-manipulator` |
| Routing | OpenRouteService, OpenStreetMap |

---

## Repository layout

```
.
├── backend/
│   ├── main.py                     # FastAPI application
│   ├── requirements.txt
│   ├── agents/
│   │   ├── vibe_planner.py         # natural language -> route plan
│   │   ├── vision_inspector.py     # street photo -> safety report
│   │   └── storyteller.py          # recap, quiz, badge
│   ├── core/
│   │   ├── routing.py              # OpenRouteService / OSM routing
│   │   └── database.py             # SQLite: feed_posts, hazard_reports, crew_members
│   └── routes/
│       ├── navigation_routes.py    # /api/routes/plan
│       └── community_routes.py     # vision audit, ride finish, feed, leaderboard, hazards
└── mobile/
    ├── components/
    │   ├── SearchHUD.js            # search box + vibe presets
    │   ├── MapView.js              # route drawing with a glow polyline
    │   ├── HazardMarkers.js        # community hazard pins
    │   ├── VisionAuditModal.js     # camera capture + safety result
    │   ├── EndRideModal.js         # stats, badge, quiz, share to feed
    │   ├── Leaderboard.js          # private crew ranking
    │   └── Feed.js                 # community feed
    └── utils/
        ├── api.js                  # network helper with timeouts
        ├── audio.js                # speech for turn cues and safety alerts
        ├── image.js                # photo resizing before upload
        └── theme.js
```

---

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/routes/plan` | Natural-language request → plan + GeoJSON route |
| POST | `/api/vision/audit` | Street photo (multipart `file` or JSON `image_base64`) → safety report |
| POST | `/api/ride/finish` | Ride stats → recap, quiz, badge; adds distance to the crew total |
| GET | `/api/feed` | Community feed (`crew`, `limit`, `before_id`) |
| POST | `/api/feed` | Share a ride photo and caption |
| GET | `/api/leaderboard` | Crew ranking (`crew` required, `scope=weekly\|all_time`) |
| GET | `/api/hazards` | Anonymous hazards, optionally inside a bounding box |

Interactive documentation is available at `/docs` while the server runs.

Example: finish a ride

```bash
curl -X POST http://localhost:8000/api/ride/finish \
  -H "Content-Type: application/json" \
  -d '{"user_name":"Alex","crew_code":"COTROCENI-GANG","route_title":"Shaded Historic Cotroceni Escape","distance_km":6.4,"duration_min":24,"vibe_preset":"green_shady"}'
```

---

## Getting started

### Backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

Create a `.env` file in the repository root:

```
BASETEN_API_KEY=your_key_here
ORS_API_KEY=your_openrouteservice_key
```

Run from the repository root, bound to all interfaces so a phone on the same network can reach it:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

The database file (`backend/viberide.db`) is created on first start. Set `VIBERIDE_DB_PATH` to put it elsewhere.

### Mobile

```bash
cd mobile
npm install
npx expo install expo-image-picker expo-location expo-speech expo-image-manipulator react-native-maps
```

A phone cannot reach `localhost`, so point the app at your computer's LAN IP. Create `mobile/.env`:

```
EXPO_PUBLIC_API_URL=http://192.168.X.X:8000
```

Find the IP with `ipconfig getifaddr en0` (macOS). Then start Expo and open the app with Expo Go:

```bash
npx expo start -c
```

The phone and the computer must be on the same Wi-Fi network. If you change networks, update `mobile/.env` and restart Expo with `-c`.

---

## Configuration

| Variable | Where | Meaning |
|---|---|---|
| `BASETEN_API_KEY` | backend `.env` | Access to the Muse Spark model |
| `ORS_API_KEY` | backend `.env` | OpenRouteService routing |
| `VIBERIDE_DB_PATH` | backend | Location of the SQLite file |
| `VIBERIDE_DEMO_FALLBACK` | backend, local testing only | `1` (default in the test app) returns a canned Street Scan result if the vision model is unavailable. Set `0` to disable. |
| `EXPO_PUBLIC_API_URL` | `mobile/.env` | Backend address used by the app |

---

## Design principles

- **Calm over fast.** Routes are judged by shade, quiet and safety, not by minutes saved.
- **Not a fitness tracker.** No performance coaching, no speed contests. Stats are framed as mindful kilometres and traffic avoided.
- **Safety through sensing.** The camera is a hazard sensor that feeds spoken warnings and an anonymous open hazard map, not a photo gallery.
- **Fail soft.** Timeouts, fallbacks and validation everywhere: a model outage must never stop a ride from finishing.
- **Privacy first.** Collect the least possible and keep nothing that is not needed.
