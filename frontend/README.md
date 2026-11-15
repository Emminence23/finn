# FINN web app

A mobile-first Next.js app with three tabs:

- **Today** (Push): the ranked digest for a time window, unusual moves, and reconnect suggestions. Routine filings are folded away.
- **Ask** (Pull): one search box for any NSE ticker, person or theme. A company opens its research view, which leads with the promised-vs-delivered scorecard.
- **People** (Network): the expertise map, people worth calling, and profiles with paths from you to them.

```bash
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev   # backend: `make api` from the repo root
```

All data comes from the FINN API (`src/lib/api.ts`). When the API has a demo passcode set, the app asks for it once and stores it on the device.
