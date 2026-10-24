# Vitals

Read-only Linux server status dashboard: 1-second live metrics, 90-day SQLite history, an incident journal and login protection. Python standard library backend, Vue 3 + ECharts frontend.

> 只读的 Linux 服务器状态面板。1 秒实时指标、90 天历史、异常记录和登录保护；后端零第三方依赖，前端为 Vue 3 + Vite + ECharts。

## Features

- **Live metrics**: CPU (per core + frequency), memory, load, uptime, network throughput, physical disk I/O — every second.
- **Slow collectors**: temperatures (5s), top processes (5s), containers and service checks (15s), filesystem usage and link info (30s), Docker stats (30s), SMART / Docker images / host health (60s), Docker space (5min), system/hardware inventory (1h).
- **Host health**: file descriptors, zombie processes, failed systemd units, established TCP connections, CPU iowait/steal time, NIC errors/drops, inode usage and OOM kills.
- **Sensors**: temperatures, plus fan speeds (RPM) and voltages (V) when the hardware exposes them.
- **Certificates**: HTTPS service checks report days until the certificate expires.
- **Bounded archive**: SQLite with WAL, zlib-compressed payloads, 90-day retention (configurable) and hourly rollup for 30/90-day charts.
- **Incident journal**: threshold + hysteresis, restart-safe pending state, no fabricated recoveries.
- **Authentication**: scrypt password hashes, SHA-256 session digests, `HttpOnly` cookie plus Bearer fallback for browsers that block cookies, per-client login throttling.
- **UI**: per-chart time range (10 minutes – 90 days), zoom modal, detail drawers (every process in a virtualized list, full temperature, storage, network, containers with live CPU/memory and an image inventory, services), light/dark theme, responsive layout.

## Architecture

```text
backend/src/vitals/
├── core.py       HTTP server, samplers, collector loops, event loop, main()
├── store.py      SQLite archive, compression, hourly rollup, pruning
├── features.py   optional collectors, incident engine, config validation
├── auth.py       users/sessions, scrypt hashing
├── cli.py        account management CLI
├── __main__.py   python -m vitals
└── __init__.py

web/              Vue 3 + Vite + ECharts source
config/           runtime configuration (example checked in)
deploy/           systemd unit and nginx example
legacy/index.html previous single-file implementation, kept for reference
```

## Quick start

### Backend

```sh
git clone https://github.com/gloryhui/vitals-monitor.git
cd vitals-monitor
cp config/vitals-config.example.json config/vitals-config.json

# The default database lives in /var/lib/server-info, which needs root.
# For a quick local run, point it somewhere writable:
VITALS_DB=/tmp/vitals.sqlite3 \
PYTHONPATH=backend/src \
python3 -m vitals
```

The first start creates `auth.admin_user` (default `admin`). When no password is supplied through `VITALS_ADMIN_PASSWORD` or `auth.admin_password`, one is generated and written to the database directory as `initial-admin-password` (mode 0600) and logged.

### Frontend

```sh
cd web
npm install
npm run dev      # http://localhost:5180, proxies /api to 127.0.0.1:8790
```

Production build (written to the project root as `index.html` + `assets/`):

```sh
make build-web
```

## Configuration

`config/vitals-config.json` (or `VITALS_CONFIG`):

| Key | Default | Description |
| --- | --- | --- |
| `retention_days` | `90` | Samples, collector archives and events older than this are pruned hourly |
| `auth.session_hours` | `12` | Sliding session lifetime |
| `auth.admin_user` | `admin` | Account created on first start |
| `auth.admin_password` | `null` | Initial password; `null` generates one |
| `auth.secure_cookie` | `false` | Set `true` behind HTTPS |
| `auth.max_failures` | `8` | Failed logins before throttling |
| `auth.failure_window_seconds` | `600` | Throttling window |
| `services` | `[]` | systemd / HTTP / TCP checks, max 20 |
| `alerts` | see example | Thresholds and hold times |

Environment overrides: `VITALS_DB`, `VITALS_CONFIG`, `VITALS_ADMIN_PASSWORD`.

## API

| Endpoint | Auth | Description |
| --- | --- | --- |
| `GET /api/health` | public | Liveness, sample age, storage status |
| `GET /api/session` | public | Current login state |
| `POST /api/login` | — | `{"username","password"}`, returns a session cookie and Bearer token |
| `POST /api/logout` | — | Revokes the current session |
| `GET /api/status` | required | Latest 1-second snapshot |
| `GET /api/overview` | required | Collector groups, alert policy, retention info |
| `GET /api/history?minutes=1440` | required | Aggregated trend; >7 days uses the hourly rollup |
| `GET /api/events?limit=30` | required | Incident journal, `before` cursor for paging |
| `GET /api/processes` | required | Full process snapshot (cmdline, exe, cwd, user, threads, memory); optional `limit` |

## Deployment

```sh
sudo mkdir -p /opt/vitals
sudo cp -r . /opt/vitals
sudo cp deploy/vitals.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vitals
```

Serve the project root with the provided `deploy/nginx.conf.example` (it proxies `/api/` and denies access to `backend/`, `web/`, `config/`). The Vite `base` in `web/vite.config.js` must match the public URL path, for example `base: "/tools/vitals/"`.

Account management (no restart required):

```sh
PYTHONPATH=backend/src sudo -E python3 -m vitals.cli list
PYTHONPATH=backend/src sudo -E python3 -m vitals.cli add alice
PYTHONPATH=backend/src sudo -E python3 -m vitals.cli passwd alice
PYTHONPATH=backend/src sudo -E python3 -m vitals.cli delete alice
```

## Development

```sh
make test      # backend tests (unittest, no external services)
make lint      # ruff check
make format    # ruff format
make run       # run the backend from source
```

The test suite uses temporary databases and local HTTP/TCP ports; it never stops a business service.

## Security notes

- Set `auth.secure_cookie` to `true` once the page is served over HTTPS.
- Do not expose the project root without the nginx deny rules: it contains backend sources and configuration.
- The service runs as root because `smartctl`, `dmidecode` and `sensors` need privileged access. Keep the HTTP listener behind a reverse proxy and restrict it to loopback or a container network.
- The IP allowlist in `core.py` (`127.0.0.0/8`, `172.16.0.0/12`) is a defence-in-depth measure, not a substitute for authentication.
- The process drawer reads `/proc/<pid>/cmdline`, `exe` and `cwd`, which may contain credentials passed on a command line. It is only served to authenticated users; keep that in mind before screenshots or exports.

## License

MIT
