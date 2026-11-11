

@echo off
setlocal EnableExtensions
title EduShieldAI - Startup Manager

cd /d "%~dp0"

echo.
echo ==================================================
echo             EDUSHIELD AI STARTUP
echo ==================================================
echo.

REM ==================================================
REM 1. CHECK PYTHON
REM ==================================================

echo [1/7] Checking Python...

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    goto :FAILED
)

echo [OK] Python found.

REM ==================================================
REM 2. CHECK VIRTUAL ENVIRONMENT
REM ==================================================

echo.
echo [2/7] Checking virtual environment...

if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Creating virtual environment...

    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        goto :FAILED
    )
)

echo [OK] Virtual environment ready.

REM ==================================================
REM 3. CHECK DEPENDENCIES
REM ==================================================

echo.
echo [3/7] Checking Python dependencies...

".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r backend\requirements.txt
if errorlevel 1 (
    echo [ERROR] Backend dependencies could not be installed.
    goto :FAILED
)

".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r frontend-flask\requirements.txt
if errorlevel 1 (
    echo [ERROR] Frontend dependencies could not be installed.
    goto :FAILED
)

echo [OK] Dependencies checked.

REM ==================================================
REM 4. CHECK MYSQL
REM ==================================================

echo.
echo [4/7] Checking MySQL...

powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient; try {$c.Connect('127.0.0.1',3306); $c.Close(); exit 0} catch {exit 1}"

if errorlevel 1 (
    echo [ERROR] MySQL is not running on port 3306.
    echo Please start MySQL and try again.
    goto :FAILED
)

echo [OK] MySQL is running.

REM ==================================================
REM 5. START BACKEND
REM ==================================================

echo.
echo [5/7] Starting backend...

start "EduShieldAI Backend" cmd /k "cd /d ""%~dp0backend"" && ""%~dp0.venv\Scripts\python.exe"" app.py"

echo [INFO] Waiting for backend on port 5000...

call :WAIT_FOR_PORT 5000
if errorlevel 1 (
    echo [ERROR] Backend did not become available on port 5000.
    echo Check the EduShieldAI Backend window.
    goto :FAILED
)

echo [OK] Backend is responding.

REM ==================================================
REM 6. START FRONTEND
REM ==================================================

echo.
echo [6/7] Starting frontend...

start "EduShieldAI Frontend" cmd /k "cd /d ""%~dp0frontend-flask"" && ""%~dp0.venv\Scripts\python.exe"" app.py"

echo [INFO] Waiting for frontend on port 5002...

call :WAIT_FOR_PORT 5002
if errorlevel 1 (
    echo [ERROR] Frontend did not become available on port 5002.
    echo Check the EduShieldAI Frontend window.
    goto :FAILED
)

echo [OK] Frontend is responding.

REM Open local frontend
start "" "http://127.0.0.1:5002"

REM ==================================================
REM 7. CLOUDFLARE CONFIGURATION AND STARTUP
REM ==================================================

echo.
echo [7/7] Preparing Cloudflare tunnel...

if not exist "%~dp0start-cloudflare-tunnel.ps1" (
    echo [ERROR] start-cloudflare-tunnel.ps1 was not found.
    goto :FAILED
)

REM Load persistent Windows User Environment Variables.
REM This also works if the current terminal was opened
REM before the variables were configured.

for /f "usebackq delims=" %%A in (`powershell.exe -NoProfile -Command "[Environment]::GetEnvironmentVariable('CLOUDFLARE_WORKER_URL','User')"`) do set "CLOUDFLARE_WORKER_URL=%%A"

for /f "usebackq delims=" %%A in (`powershell.exe -NoProfile -Command "[Environment]::GetEnvironmentVariable('TUNNEL_UPDATE_SECRET','User')"`) do set "TUNNEL_UPDATE_SECRET=%%A"

REM Use the known permanent Worker URL if not configured.
if not defined CLOUDFLARE_WORKER_URL (
    set "CLOUDFLARE_WORKER_URL=https://edushield-parent-verify.b-saisuryakarthik.workers.dev"
)

REM Check required configuration without displaying secrets.

if not defined TUNNEL_UPDATE_SECRET (
    echo [ERROR] TUNNEL_UPDATE_SECRET is missing.
    echo Configure it once in Windows User Environment Variables.
    goto :FAILED
)

if not defined CLOUDFLARE_WORKER_URL (
    echo [ERROR] CLOUDFLARE_WORKER_URL is missing.
    goto :FAILED
)

echo [OK] Cloudflare configuration loaded.
echo [OK] Permanent Worker URL configured.
echo [INFO] Starting Cloudflare registration process...

REM Launch tunnel in its own PowerShell window.
REM The environment variables are inherited by this process.

start "EduShieldAI Cloudflare Tunnel" powershell.exe -NoExit -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-cloudflare-tunnel.ps1"

REM ==================================================
REM STARTUP SUMMARY
REM ==================================================

echo.
echo ==================================================
echo             EDUSHIELD AI STARTED
echo ==================================================
echo.
echo Backend:
echo http://127.0.0.1:5000
echo.
echo Frontend:
echo http://127.0.0.1:5002
echo.
echo Parent Verification Worker:
echo %CLOUDFLARE_WORKER_URL%
echo.
echo Cloudflare:
echo Startup process launched.
echo.
echo IMPORTANT:
echo Check the Cloudflare window for successful tunnel
echo registration before testing remote verification.
echo.
echo Keep all service windows running.
echo ==================================================
echo.

pause
exit /b 0


REM ==================================================
REM WAIT FOR A TCP PORT TO BECOME AVAILABLE
REM ==================================================

:WAIT_FOR_PORT

powershell.exe -NoProfile -Command "$port=%~1; $ready=$false; for($i=0;$i -lt 30;$i++){ $c=New-Object Net.Sockets.TcpClient; try{$c.Connect('127.0.0.1',$port);$c.Close();$ready=$true;break}catch{};Start-Sleep -Seconds 1 }; if($ready){exit 0}else{exit 1}"

if errorlevel 1 exit /b 1

exit /b 0


REM ==================================================
REM ERROR HANDLER
REM ==================================================

:FAILED

echo.
echo ==================================================
echo               STARTUP FAILED
echo ==================================================
echo.
echo Please check the error above.
echo Fix the issue and run START.bat again.
echo.
pause
exit /b 1
