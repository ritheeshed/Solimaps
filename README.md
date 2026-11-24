# Soli Maps

Chennai job openings pinned on a 3D map of the city. Live at https://www.solimaps.com

- `index.html` — the whole site (MapLibre GL + OpenFreeMap tiles, styled as a white scale model; English/Tamil).
- `jobs.json` — the job data. Refreshed every morning from Indeed by a scheduled Claude task, which commits a new `jobs.json` here; Cloudflare Pages redeploys automatically.
- `_headers` — stops browsers caching `jobs.json`.

Map data © OpenStreetMap contributors, tiles by OpenFreeMap / OpenMapTiles. Jobs link to their Indeed listings.

## Deploy (Cloudflare Pages)
1. Cloudflare dashboard → Workers & Pages → Create → Pages → Connect to Git → pick this repo.
2. Framework preset: None. Build command: (leave empty). Output directory: `/`.
3. After the first deploy: the project → Custom domains → add `solimaps.com` and `www.solimaps.com`.
