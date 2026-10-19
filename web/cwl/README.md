# Warriors United CWL web

React and TypeScript member signup and staff management UI. The site uses the same-origin `/api/cwl` service; it does not store signups in the browser.

```bash
npm ci
npm test
npm run build
```

For frontend development, run `npm run dev`. Vite binds to `127.0.0.1` and proxies `/api/cwl` to the local backend at `127.0.0.1:8767`. The backend serves the built `dist/` directory for integrated local use. Build again after frontend changes.

Production requires configured Discord OAuth and the backend's real account provider. The local fixture entry is shown only when both the hostname is loopback and `/api/cwl/config` reports `dev_fixture: true`; it calls `/api/cwl/dev/login`. Fixture data is labeled in the UI. The frontend never grants access based on its own state: the server checks Discord identity, linked-account ownership, pool exclusivity, signup windows, staff grants, and CSRF.

The read-only family-clan list from the bot provides staff context and does not restrict signup. Active hosting clans in the directory are available in every season's staff roster; archived clans retain existing assignments but cannot receive new ones. Signup saves selected accounts additively; withdrawing a saved account uses the explicit withdrawal action.
