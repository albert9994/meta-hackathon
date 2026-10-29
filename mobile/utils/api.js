/**
 * VibeRide - shared network helper.
 *
 * Phones cannot resolve "localhost", so the backend must be reached through the
 * laptop's LAN IP. Put it in mobile/.env (Expo reads EXPO_PUBLIC_* at build time):
 *
 *     EXPO_PUBLIC_API_URL=http://192.168.X.X:8000
 *
 * and start the backend with:  uvicorn backend.main:app --host 0.0.0.0 --port 8000
 */

const FALLBACK_URL = 'http://192.168.0.100:8000';

export const API_BASE_URL = (process.env.EXPO_PUBLIC_API_URL || FALLBACK_URL).replace(/\/+$/, '');

if (!process.env.EXPO_PUBLIC_API_URL) {
  // eslint-disable-next-line no-console
  console.warn(
    `[VibeRide] EXPO_PUBLIC_API_URL is not set - falling back to ${FALLBACK_URL}. ` +
      'Set it to your laptop LAN IP, e.g. http://192.168.1.23:8000'
  );
}

export class ApiError extends Error {
  constructor(message, { status = 0, kind = 'http' } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status; // 0 = no HTTP response (network / timeout)
    this.kind = kind; // 'http' | 'network' | 'timeout'
  }
}

/** FastAPI errors: {detail: "text"} or {detail: [{msg, loc}, ...]} */
function extractDetail(payload, fallback) {
  const detail = payload && payload.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((d) => (d && d.msg ? `${(d.loc || []).slice(1).join('.')}${d.loc ? ': ' : ''}${d.msg}` : String(d)))
      .join('\n');
  }
  return fallback;
}

export async function apiRequest(path, { method = 'GET', body, timeoutMs = 15000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json', Accept: 'application/json' } : { Accept: 'application/json' },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });

    let payload = null;
    try {
      payload = await response.json();
    } catch (_) {
      payload = null; // empty or non-JSON body
    }

    if (!response.ok) {
      throw new ApiError(extractDetail(payload, `Server error (${response.status}).`), {
        status: response.status,
        kind: 'http',
      });
    }
    return payload;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err && err.name === 'AbortError') {
      throw new ApiError('The server took too long to answer. Please try again.', { kind: 'timeout' });
    }
    throw new ApiError(
      `Cannot reach the VibeRide server at ${API_BASE_URL}. Check that your phone and laptop are on the same Wi-Fi.`,
      { kind: 'network' }
    );
  } finally {
    clearTimeout(timer);
  }
}

// ---- Typed helpers (paths and keys follow the blueprint's Section 4) ---------

export const planRoute = ({ user_prompt, vibe_preset, city }) =>
  apiRequest('/api/routes/plan', { method: 'POST', body: { user_prompt, vibe_preset, city }, timeoutMs: 45000 });

export const auditStreet = ({ image_base64, lat, lon }) => {
  const body = { image_base64 };
  if (typeof lat === 'number' && typeof lon === 'number') {
    body.lat = lat;
    body.lon = lon;
  }
  return apiRequest('/api/vision/audit', { method: 'POST', body, timeoutMs: 40000 });
};

export const finishRide = (ride) => apiRequest('/api/ride/finish', { method: 'POST', body: ride, timeoutMs: 30000 });

export const postToFeed = (post) => apiRequest('/api/feed', { method: 'POST', body: post, timeoutMs: 30000 });

export const getFeed = ({ crew, limit = 20, beforeId } = {}) => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (crew) params.set('crew', crew);
  if (beforeId) params.set('before_id', String(beforeId));
  return apiRequest(`/api/feed?${params.toString()}`);
};

export const getLeaderboard = ({ scope = 'weekly', crew }) =>
  apiRequest(`/api/leaderboard?${new URLSearchParams({ scope, crew }).toString()}`);

export const getHazards = (bbox = {}) => {
  const params = new URLSearchParams();
  Object.entries(bbox).forEach(([k, v]) => v !== undefined && v !== null && params.set(k, String(v)));
  const qs = params.toString();
  return apiRequest(`/api/hazards${qs ? `?${qs}` : ''}`);
};
