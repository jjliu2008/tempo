# Tempo heat map frontend

Run from this folder:

```sh
pnpm install
pnpm dev
pnpm test
pnpm build
```

The main route renders the Tempo calendar UI from `src/features/heat-map/HeatMapPage.jsx`. It includes weekly and monthly heat maps, calendar filters, editable event priorities and hover messages, lifestyle remixes, and original/remixed comparisons. Preferences are saved on the current device.

The calendar uses deterministic college demo events, not live Google Calendar data. Daily heat measures occupied time against a six-hour reference: green below 60%, yellow from 60% to 99%, and red at 100% or above. Three or more red days make a Hell week. Lifestyle remixes change the sample schedule; the original remains available.

The existing router, API client, Vite API proxy, and Python backend remain available for future live calendar integration. Replace the demo event source in `src/features/heat-map/college-data.mjs` with normalized calendar data when connecting the backend.

Model tests cover load calculations, social advice, and calendar remixes. JavaScript feature files are included through TypeScript `allowJs`; the existing TypeScript scaffold retains strict checking.
