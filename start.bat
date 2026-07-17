@echo off
chcp 65001 >nul 2>&1
setlocal

set "PROJECT_ROOT=d:\antigravity ide text\trad account"
set "BACKEND_DIR=%PROJECT_ROOT%\backend"
set "FRONTEND_DIR=%PROJECT_ROOT%\frontend"
set "PYTHON=%BACKEND_DIR%\venv\Scripts\python.exe"
set "BACKEND_PORT=8005"
set "FRONTEND_PORT=3001"

echo ============================================
echo   Trad Account - Development Launcher
echo ============================================
echo.

REM --- Step 0: Pre-flight checks ---
echo [0/6] Pre-flight checks...

if not exist "%BACKEND_DIR%\.env" (
    echo   [ERROR] backend\.env not found! Copy .env.example to .env and configure it.
    pause
    exit /b 1
)
echo   .env .............. OK

if not exist "%PYTHON%" (
    echo   [ERROR] Python venv not found at %PYTHON%
    echo   Run: cd backend ^&^& python -m venv venv ^&^& venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)
echo   Python venv ....... OK

if not exist "%FRONTEND_DIR%\node_modules" (
    echo   [WARN] frontend\node_modules not found. Running npm install...
    cd /d "%FRONTEND_DIR%" && call npm install
    if errorlevel 1 (
        echo   [ERROR] npm install failed.
        pause
        exit /b 1
    )
)
echo   node_modules ...... OK
echo.

REM --- Step 1: Database migration ---
echo [1/6] Running database migrations...
cd /d "%BACKEND_DIR%"
"%PYTHON%" -m alembic upgrade head
if errorlevel 1 (
    echo   [ERROR] Migration failed. Fix errors before continuing.
    pause
    exit /b 1
)
echo   Migrations applied.
echo.

REM --- Step 2: Seed users ---
echo [2/6] Seeding default users (idempotent)...
"%PYTHON%" scripts\seed_users.py
if errorlevel 1 (
    echo   [WARN] seed_users.py failed, continuing anyway...
)
echo.

REM --- Step 3: Initialize base data (ledger/accounts/period) ---
echo [3/6] Initializing base data (idempotent)...
"%PYTHON%" init_db.py
if errorlevel 1 (
    echo   [WARN] init_db.py failed, continuing anyway...
)
echo.

REM --- Step 4: Kill lingering processes and free ports ---
echo [4/6] Cleaning up lingering processes and freeing ports...
REM Kill any node.exe processes belonging to this project.
REM Turbopack compile loops spawn many child workers that do NOT listen on
REM any port, so the port-based cleanup below misses them. They accumulate
REM across repeated launches and exhaust memory. Match by command line instead.
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter ""Name='node.exe'"" | Where-Object { $_.CommandLine -like '*trad account*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
REM Kill any backend uvicorn python processes from this project
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter ""Name='python.exe'"" | Where-Object { $_.CommandLine -like '*uvicorn*app.main*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
REM Free target ports (catches anything the command-line match missed)
powershell -NoProfile -Command "foreach ($p in @(%BACKEND_PORT%,%FRONTEND_PORT%)) { $conns = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue; foreach ($c in $conns) { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue } }"
echo   Cleanup done.
echo.

REM --- Step 5: Start backend ---
echo [5/6] Starting backend on port %BACKEND_PORT%...
start "Trad-Backend" /D "%BACKEND_DIR%" cmd /k "venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port %BACKEND_PORT% --reload"

REM --- Step 6: Start frontend ---
echo [6/6] Starting frontend on port %FRONTEND_PORT%...
REM Clean the Turbopack cache before each launch. A corrupted .next cache
REM sends Turbopack into a compile loop that forks hundreds of node workers
REM and exhausts memory. Removing it costs a few extra seconds on cold start
REM but guarantees a clean compile state.
if exist "%FRONTEND_DIR%\.next" (
    echo   Cleaning .next cache...
    rmdir /s /q "%FRONTEND_DIR%\.next"
)
start "Trad-Frontend" /D "%FRONTEND_DIR%" cmd /k "npx next dev --port %FRONTEND_PORT%"

echo.
echo ============================================
echo   All services starting!
echo.
echo   Backend API:  http://localhost:%BACKEND_PORT%/docs
echo   Frontend:     http://localhost:%FRONTEND_PORT%
echo.
echo   Opening browser in 6s (give servers time to boot)...
echo ============================================
ping -n 7 127.0.0.1 >nul
start http://localhost:%FRONTEND_PORT%

endlocal
