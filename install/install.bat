@echo off
REM Baize Agent - Windows one-click installer (wraps bootstrap.py)
setlocal enabledelayedexpansion
set "ROOT=%~dp0.."
cd /d "%ROOT%"

set "PY=%PYTHON%"
if "%PY%"=="" set "PY=py"
where %PY% >nul 2>nul
if errorlevel 1 (
    set "PY=python"
    where python >nul 2>nul || (
        echo ERROR: Python not found. Install Python 3.10+ and retry.
        exit /b 1
    )
)

echo Running Baize Agent installer...
"%PY%" install\bootstrap.py %*
endlocal
