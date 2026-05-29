import axios from 'axios';

// Short timeout for auth/schema (fast operations)
const api = axios.create({
  baseURL: process.env.REACT_APP_API_URL || 'http://localhost:8000/api',
  timeout: 30000,
});

// For Hive queries (NLQ, custom queries) — still need a long timeout
const apiHive = axios.create({
  baseURL: process.env.REACT_APP_API_URL || 'http://localhost:8000/api',
  timeout: 600000,
});

export async function login(payload) {
  const { data } = await api.post('/auth/login', payload);
  return data;
}

export async function getSchema(token, refresh = false) {
  const { data } = await api.get('/schema', {
    params: { refresh },
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

/**
 * getOverview — async job pattern.
 *
 * 1. GET /overview  → returns data instantly if cache warm, or 202 if cold
 * 2. POST /overview/start  → { job_id }
 * 3. Poll GET /overview/status/:id every 3 s
 * 4. Resolve when status === "done", reject on "error"
 *
 * NOTE: axios treats ALL 2xx (including 202) as success — so we must
 * explicitly check response.status, not rely on catch blocks.
 *
 * onProgress(secondsElapsed) is called every 3 s while waiting.
 */
export async function getOverview(token, refresh = false, onProgress = null) {
  const headers = { Authorization: `Bearer ${token}` };

  // Step 0 — try the cached sync endpoint first (returns instantly if warm)
  // axios does NOT throw on 202, so we check the status explicitly
  try {
    const res = await api.get('/overview', {
      params: { refresh },
      headers,
      // Tell axios to resolve for ALL status codes so we can inspect the status
      validateStatus: () => true,
    });

    // Cache hit — 200 with real data
    if (res.status === 200) {
      return res.data;
    }

    // 202 or detail === ASYNC_REQUIRED → fall through to async flow below
    // Any other error (401, 500…) → throw
    if (res.status !== 202 && res.data?.detail !== 'ASYNC_REQUIRED') {
      const err = new Error(`Erreur ${res.status}: ${res.data?.detail || 'Erreur serveur'}`);
      err.response = res;
      throw err;
    }
  } catch (err) {
    // Re-throw real errors (network failures, etc.)
    if (err.response !== undefined && err.response?.status !== 202) {
      throw err;
    }
    // If it's a network error without response, rethrow
    if (!err.response) throw err;
  }

  // Step 1 — start background job
  const startRes = await api.post('/overview/start', null, {
    params: { refresh },
    headers,
  });
  const { job_id } = startRes.data;

  // Step 2 — poll every 3 s
  const POLL_MS     = 3000;
  const MAX_WAIT_MS = 10 * 60 * 1000; // 10 min absolute ceiling
  const deadline    = Date.now() + MAX_WAIT_MS;
  let   elapsed     = 0;

  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, POLL_MS));
    elapsed += POLL_MS;
    if (onProgress) onProgress(Math.floor(elapsed / 1000));

    const { data } = await api.get(`/overview/status/${job_id}`, { headers });

    if (data.status === 'done')  return data.result;
    if (data.status === 'error') throw new Error(data.error || 'Erreur serveur overview');
    // pending / running → keep polling
  }

  throw new Error("Timeout: le dashboard n\u2019a pas r\u00e9pondu en 10 minutes");
}

export async function runQuery(token, payload) {
  const { data } = await apiHive.post('/query', payload, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

export async function runNlq(token, payload) {
  const { data } = await apiHive.post('/nlq', payload, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}
