# Web And Desktop Apps

## SolWeb

`SolWeb` is the main browser interface. It is a React 18 and Vite app with Tailwind CSS, TypeScript, Vitest, and a typed API client.

SolWeb uses the Vite 8 toolchain and requires Node.js 20.19+ on Node 20, or Node.js 22.12+ or newer.

Common commands:

```bash
cd SolWeb
npm install
npm run dev
npm run build
npm run test
npm run typecheck
npm run preview
```

The production installer builds `SolWeb/dist` and serves it through the managed web service.

## SolWeb Runtime Config

`SolWeb/public/solweb.config.js` controls the API base URL without rebuilding:

```js
window.__SOLWEB_CONFIG__ = {
  apiBase: "http://127.0.0.1:8420",
  showInspector: undefined
};
```

Use cases:

| Config | Use |
| --- | --- |
| `apiBase: "http://127.0.0.1:8420"` | Direct local API |
| `apiBase: "/api"` | Same-origin reverse proxy |
| `showInspector: true` | Force-enable inspector |
| `showInspector: false` | Force-hide inspector |

## Web UI Features

The web client includes:

- Chat threads and message rendering.
- Provider/model status display.
- Settings for provider, model, Ollama URL, timeouts, names, theme, appearance, density, and layout.
- Inspector panel and audit/runtime data.
- Code canvas and active artifact context.
- Unsafe-mode controls for destructive per-thread actions.
- Web policy controls for allowed domains and session allowlists.

## API Client

The typed client lives at:

```text
SolWeb/src/api/client.ts
```

It handles:

- Bearer auth from `localStorage`.
- Automatic auth reset on HTTP 401.
- Provider error normalization.
- Calls for status, settings, chat, threads, unsafe mode, capabilities, audit, memory, tools, web policy, and ingest manifests.

## Desktop Client

`apps/desktop` is a Tauri 2 desktop shell using React and Vite.

The desktop frontend uses the Vite 8 toolchain and requires Node.js 20.19+ on Node 20, or Node.js 22.12+ or newer.

Common commands:

```bash
cd apps/desktop
npm install
npm run dev
npm run build
npm run tauri:dev
npm run tauri:build
```

Tauri config:

```text
apps/desktop/src-tauri/tauri.conf.json
```

Important defaults:

| Setting | Value |
| --- | --- |
| Product name | `Sol` |
| Identifier | `com.sol.desktop` |
| Dev URL | `http://localhost:1420` |
| Window size | `1200x800` |

The desktop app is separate from the main managed web install path and should be treated as active client work rather than the primary deployment path.
