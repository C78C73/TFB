# Task Force Black

Official website for Task Force Black - Elite milsim community with 100+ members worldwide.

🌐 **Live Site:** https://c78c73.github.io/TFB/

## About

Task Force Black is a premier military simulation community focused on tactical operations in Arma and Battlefield. We're composed primarily of active and prior U.S. service members, alongside dedicated members from around the globe.

### Key Features
- 🎯 100+ active members worldwide
- 🌍 Co-ed and inclusive
- 🎮 PC, PlayStation, and Xbox platforms
- 🤝 Real life comes first - we're here to have fun
- ⛪ Dedicated chaplain for member support

### What We Offer
- Organized tactical operations
- Structured training programs
- Active community on Arma (primary) and Battlefield
- Professional yet welcoming atmosphere

## Links

- **Website:** https://c78c73.github.io/TFB/
- **Merchandise:** [CustomInk Store](https://www.customink.com/g/dwu0-00d0-te8u)
- **Twitter:** [@TF_Black_PMC](https://x.com/TF_Black_PMC)

## Arma Reforger Server Stats (Website)

The site can display live Arma Reforger server status on the Stats page.

### GitHub Pages-only (recommended for this repo)

Because game queries are UDP and browsers only support HTTP(S), this repo uses a scheduled GitHub Action to query the server and write a static JSON file that the Stats page can fetch.

- Output file: [arma-status.json](arma-status.json)
- Workflow: [.github/workflows/arma-status.yml](.github/workflows/arma-status.yml)
- Script: [scripts/update-arma-status.cjs](scripts/update-arma-status.cjs)

To enable it:
1. In GitHub repo settings → **Secrets and variables** → **Actions** → **Secrets**, add:
	 - `ARMA_HOST` (required)
	 - `ARMA_QUERY_PORT` (recommended)
2. Make sure A2S is enabled in the Arma Reforger server config (BI wiki: `a2s`).

Notes:
- Arma Reforger does not provide player names via A2S; you’ll only get player counts.
- Some hosted environments block inbound UDP replies. If the workflow always writes `ok:false`, the fix is usually running a **self-hosted GitHub Actions runner** on a VPS (or the same network as the game server).

### Optional: separate backend API

If you prefer a traditional API, a small Express service scaffold is available in [server/README.md](server/README.md).

---

© 2025 Task Force Black. All rights reserved.
