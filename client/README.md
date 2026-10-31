# CX Sentinel AI — web client

React 19 + TypeScript + Vite + Tailwind CSS 4. See the [root README](../README.md) for the full setup.

```bash
npm install
npm run dev        # http://localhost:5173 (proxies /api and the WebSocket to http://127.0.0.1:8000)
npm run typecheck
npm run build
```

Set `VITE_PROXY_TARGET` to point the dev proxy at a different backend.

`src/pages` holds the ten modules (Executive Overview, Signal Explorer, Issue Intelligence, Root Cause, Customer Impact,
Intervention Center, Approval Center, Recovery Monitoring, Jury Simulator, AI Evaluation) plus the execution history.
