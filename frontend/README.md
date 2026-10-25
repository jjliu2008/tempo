# Tempo heat map frontend

Run from this folder:

```sh
pnpm install
pnpm dev
pnpm test
pnpm build
```

The main route renders the Tempo calendar UI from `src/features/heat-map/HeatMapPage.jsx`. It includes weekly and monthly heat maps, calendar filters, editable event priorities and hover messages, lifestyle remixes, and original/remixed comparisons. Preferences are saved on the current device.

On load, the page asks the backend to analyze the demo semester (`POST /api/v1/analysis`) and opens on its hell week; "Your calendars" imports an `.ics` file or secret iCal link, and the "Find my hell weeks" button on `/calendars` hands parsed Google/iCloud events over. `live-data.mjs` maps the analysis onto this page's event shape, and each day's prep hours appear as "Prep: …" study blocks, so they count toward the heat. The banner shows the hell week forecast (written by Gemma when the backend has a key). If the backend is offline, the deterministic college demo week is shown instead. Daily heat measures occupied time against a six-hour reference: green below 60%, yellow from 60% to 99%, and red at 100% or above. Three or more red days make a Hell week. Lifestyle remixes change the sample schedule; the original remains available.

Run the backend (`make dev-backend`) alongside `pnpm dev`; Vite proxies `/api` to port 8000.

Model tests cover load calculations, social advice, and calendar remixes. JavaScript feature files are included through TypeScript `allowJs`; the existing TypeScript scaffold retains strict checking.
