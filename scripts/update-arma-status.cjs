/*
  Queries an Arma Reforger server via UDP (A2S/Valve) using GameDig
  and writes a GitHub Pages-friendly JSON file at repo root: arma-status.json

  Required env:
    ARMA_HOST
  Optional env:
    ARMA_QUERY_PORT
    ARMA_GIVEN_PORT_ONLY (default: true)
*/

const fs = require('fs');
const path = require('path');
const { GameDig } = require('gamedig');

function asBool(value, defaultValue) {
  if (value === undefined || value === null || String(value).trim() === '') return defaultValue;
  return String(value).toLowerCase() === 'true';
}

async function main() {
  const host = process.env.ARMA_HOST;
  const port = process.env.ARMA_QUERY_PORT ? Number(process.env.ARMA_QUERY_PORT) : undefined;
  const givenPortOnly = asBool(process.env.ARMA_GIVEN_PORT_ONLY, true);

  const outFile = path.resolve(__dirname, '..', 'arma-status.json');

  if (!host) {
    const payload = { ok: false, timestamp: Date.now(), error: 'Missing ARMA_HOST' };
    fs.writeFileSync(outFile, JSON.stringify(payload, null, 2) + '\n');
    process.exit(0);
  }

  try {
    const state = await GameDig.query({
      type: 'armareforger',
      host,
      port,
      givenPortOnly,
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

    const payload = { ok: true, timestamp: Date.now(), state: safeState };
    fs.writeFileSync(outFile, JSON.stringify(payload, null, 2) + '\n');
  } catch (err) {
    const payload = {
      ok: false,
      timestamp: Date.now(),
      error: String(err && err.message ? err.message : err)
    };
    fs.writeFileSync(outFile, JSON.stringify(payload, null, 2) + '\n');
  }
}

main();
