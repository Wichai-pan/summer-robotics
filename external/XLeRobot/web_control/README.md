# Setup Instructions

## Prerequisites
- Install Python 3.11 or newer — required for the server runtime.
- Install Node.js 22 or newer with npm — required for the client build tooling.
- Install Git and make sure `pip` and `npm` are on your PATH — needed for dependency management.

## Prepare Server Environment
1. `cd web_control/server` — switch to the server workspace.
2. `python -m venv .venv` — create an isolated Python environment.
3. `source .venv/bin/activate` (Linux/macOS) or `.venv\Scripts\activate` (Windows) — activate the environment.
4. `pip install -r requirements.txt` — install server dependencies.
5. `cp .env.example .env` — create the server environment file.
6. Edit `.env` and set at minimum:
   - `UI_HOST=0.0.0.0` — choose the bind address.
   - `UI_PORT=8000` — choose the HTTP port.
   - `ROBOT_HOST=localhost` — point to the robot or simulator host.
   - `ROBOT_PORT_CMD=5555` and `ROBOT_PORT_DATA=5556` — configure ZeroMQ ports.
7. `python main.py` — start the FastAPI and Socket.IO server.

## Prepare Client Environment
1. `cd web_control/client` — switch to the client workspace.
2. `npm install` — install client dependencies.
3. `cp .env.example .env` (create if absent) — define client environment variables.
4. Edit `.env` and set at minimum:
   - `VITE_SERVER_PROTOCOL=http` — protocol used to reach the server.
   - `VITE_SERVER_HOST=localhost` — hostname or IP of the server.
   - `VITE_SERVER_PORT=8000` — port that matches the server.
5. `npm run dev` — launch the Vite dev server.
6. `npm run build` — produce a production build when needed.

## Operate the Stack
1. Ensure the server is running and reachable — required before opening the UI.
2. Ensure the client dev server or production build is served — needed for browser access.
3. Open `http://localhost:5173` (default dev URL) — verify the dashboard loads.
4. Monitor terminal logs for telemetry, errors, or reconnect issues — helps with troubleshooting.
