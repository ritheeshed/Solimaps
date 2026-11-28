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


## Pages

- `index.html`: homepage (marketing, Google sign-in). After sign-in visitors go to the map.
- `map.html`: the job map. With sign-in switched on, signed-out visitors are sent to the homepage first. Visitors can set where they start from (GPS, area search via Photon, or a tap on the map); every job then shows distance and morning/evening rush-hour travel time, and picking a company draws the road route (OSRM). Travel time = road km ÷ Chennai's average rush-hour speed (TomTom Traffic Index 2025: 17.7 km/h mornings, 14.6 km/h evenings). The home spot stays in the visitor's browser only.
- `privacy.html`: privacy notice.
- `auth/config.js`: paste the Google OAuth client ID and the Apps Script URL here to switch sign-in on (both pages read it).
- `auth/apps-script.gs`: the Google Sheet script that stores sign-ins and company requests.
