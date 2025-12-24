const express = require('express');
const cors = require('cors');
const { GameDig } = require('gamedig');

const app = express();

const PORT = Number(process.env.PORT || 8787);

const ARMA_HOST = process.env.ARMA_HOST;
const ARMA_QUERY_PORT = process.env.ARMA_QUERY_PORT ? Number(process.env.ARMA_QUERY_PORT) : undefined;
const ARMA_GIVEN_PORT_ONLY = String(process.env.ARMA_GIVEN_PORT_ONLY || 'true').toLowerCase() === 'true';

const CACHE_TTL_MS = Number(process.env.CACHE_TTL_MS || 15000);
const INCLUDE_RAW = String(process.env.INCLUDE_RAW || 'false').toLowerCase() === 'true';

const CORS_ORIGIN = (process.env.CORS_ORIGIN || '').trim();
const corsOptions = CORS_ORIGIN
  ? { origin: CORS_ORIGIN.split(',').map(s => s.trim()).filter(Boolean) }
  : { origin: '*' };

app.use(cors(corsOptions));

let cached = null;
let cachedAt = 0;
let inflight = null;

function isCacheValid() {
  return cached && (Date.now() - cachedAt) < CACHE_TTL_MS;
}

app.get('/health', (_req, res) => {
  res.json({ ok: true, service: 'tfb-arma-status-api', time: Date.now() });
});

app.get('/api/arma', async (_req, res) => {
  if (!ARMA_HOST) {
    res.status(500).json({ ok: false, error: 'Missing ARMA_HOST env var' });
    return;
  }

  try {
    if (isCacheValid()) {
      res.set('Cache-Control', `public, max-age=${Math.floor(CACHE_TTL_MS / 1000)}`);
      res.json(cached);
      return;
    }

    if (!inflight) {
      inflight = (async () => {
        const state = await GameDig.query({
          type: 'armareforger',
          host: ARMA_HOST,
          port: ARMA_QUERY_PORT,
          givenPortOnly: ARMA_GIVEN_PORT_ONLY,
          maxRetries: 1,
          socketTimeout: 2000,
          attemptTimeout: 6000,
          requestPlayers: false
        });

        const safeState = {
          name: state?.name || '',
          map: state?.map || '',
          password: !!state?.password,
          numplayers: Number.isFinite(state?.numplayers) ? state.numplayers : 0,
          maxplayers: Number.isFinite(state?.maxplayers) ? state.maxplayers : 0,
          ping: Number.isFinite(state?.ping) ? state.ping : 0,
          connect: state?.connect || '',
          queryPort: Number.isFinite(state?.queryPort) ? state.queryPort : 0,
          version: state?.version || ''
        };

        const payload = {
          ok: true,
          timestamp: Date.now(),
          state: INCLUDE_RAW ? { ...safeState, raw: state?.raw || {} } : safeState
        };

        cached = payload;
        cachedAt = Date.now();
        return payload;
      })().finally(() => {
        inflight = null;
      });
    }

    const payload = await inflight;
    res.set('Cache-Control', `public, max-age=${Math.floor(CACHE_TTL_MS / 1000)}`);
    res.json(payload);
  } catch (err) {
    res.status(200).json({
      ok: false,
      timestamp: Date.now(),
      error: String(err && err.message ? err.message : err)
    });
  }
});

app.listen(PORT, () => {
  // eslint-disable-next-line no-console
  console.log(`[tfb-arma-status-api] listening on :${PORT}`);
});
