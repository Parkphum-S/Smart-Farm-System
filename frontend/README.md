# Smart Farm System V.1 — Frontend workspace

Frontend-only scaffold. It does not modify the Python backend, database, migrations,
`.env`, firmware, or existing tests.

## Included
- `apps/web`: React + TypeScript + Vite starter
- `packages/shared`: initial design-token scaffold for future Web/Mobile reuse
- Strict TypeScript checks
- Vite development server bound to `127.0.0.1:5173`

## Requirements
- Node.js 20.19+ or 22.12+
- npm 10+

## Start Web App
Run from this `frontend/` directory:

```sh
npm install
npm run dev:web
```

Open `http://127.0.0.1:5173`.

## Verify
```sh
npm run typecheck:web
npm run build:web
```

## Project boundaries
- The visible page is a scaffold indicator, not the final UI design.
- No mock farm, device, or telemetry data is included.
- API integration, authentication UI, and production screens are not implemented yet.
- Import the approved existing design's actual colors, typography, spacing, assets, and
  component rules before production screen work.
- Mobile app creation is deferred until the Web scaffold is accepted.
- Never place secrets in frontend files; browser-exposed variables are public.
