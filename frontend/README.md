# Tempo heat map frontend

Run from this folder:

```sh
pnpm install
pnpm dev
pnpm test
pnpm build
```

The main route renders the Tempo calendar UI from `src/features/heat-map/HeatMapPage.jsx`. It includes weekly and monthly heat maps, calendar filters, editable event priorities and hover messages, lifestyle remixes, and original/remixed comparisons. Preferences are saved on the current device.

On load, the page reads the primary calendar of whatever you connected on `/` (the last 2 weeks to the next 120 days) and asks the backend to analyze it (`POST /api/v1/analysis`), opening on its hell week. With nothing connected it shows an empty week and a connect prompt; the demo semester only appears when asked: `/schedule?demo` (the login page's demo account, through the real pipeline) or `/schedule?sample` (offline static copy). The remix mixes and hover advice are planned by Gemma from your real week (`plans-api.mjs`), with no canned fallback; "Your calendars" imports an `.ics` file or secret iCal link, and the "Find my hell weeks" button on `/calendars` hands parsed Google/iCloud events over. `live-data.mjs` maps the analysis onto this page's event shape, and each day's prep hours appear as "Prep: …" study blocks, so they count toward the heat. The banner shows the hell week forecast (written by Gemma when the backend has a key). If the backend is offline you get an error and an empty week. Daily heat measures occupied time against a six-hour reference: green below 60%, yellow from 60% to 99%, and red at 100% or above. Three or more red days make a Hell week. Lifestyle remixes change the sample schedule; the original remains available.

Run the backend (`make dev-backend`) alongside `pnpm dev`; Vite proxies `/api` to port 8000.

Model tests cover load calculations, social advice, and calendar remixes. JavaScript feature files are included through TypeScript `allowJs`; the existing TypeScript scaffold retains strict checking.
