# Setup

## Windows on D:

Keep the repository, virtual environment, database, Docker data, and market archives on `D:`. The application itself only writes to the configured database path.

```powershell
New-Item -ItemType Directory -Force D:\Projects
Set-Location D:\Projects
git clone https://github.com/HIZUFU/crypto-orderflow.git
Set-Location crypto-orderflow
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
New-Item -ItemType Directory -Force data
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The default is SQLite and public market data. No exchange credentials are needed. If PowerShell blocks activation, run the project with `D:\Projects\crypto-orderflow\.venv\Scripts\python.exe` directly instead of changing execution policy globally.

## Docker

Configure Docker Desktop's disk image and file sharing to use `D:` before starting it. Then:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Only bind the web port to `127.0.0.1` until authentication and HTTPS are implemented.

## Configuration

The important values are in `.env.example`. Keep `TRADING_MODE=paper` and `LIVE_TRADING_ENABLED=false`. The current code has no live order route, but these flags make the deployment intent explicit and provide a guard for future work.
