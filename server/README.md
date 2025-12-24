# TFB Arma Reforger Status API

This is a tiny companion service for the TFB static site. It queries the Arma Reforger server via UDP (A2S / Valve query) and exposes an HTTPS-friendly JSON endpoint for the Stats page.

## Why this exists
Browsers cannot query game servers directly because most game server query protocols are UDP. Also, never expose RCON/SFTP credentials in client-side JavaScript.

## Endpoints
- `GET /health`
- `GET /api/arma` → returns `{ ok, timestamp, state }`

## Setup
1. Install deps:
   - `cd server`
   - `npm install`
2. Configure env:
   - copy `.env.example` → `.env` and edit values
3. Run:
   - `npm start`

## Hook it to the website
In [stats.html](../stats.html), set the meta tag:

- `meta[name="tfb-arma-status-api"]` → `https://YOUR_BACKEND_HOST/api/arma`

Then the stats page will render:
- status
- server name
- players (count)
- map
- ping
- password flag
- connect string

Notes:
- Arma Reforger queries require A2S to be enabled in the server config.
- Reforger does not provide player names through A2S; you’ll only get counts.
