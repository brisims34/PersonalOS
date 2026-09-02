@echo off
REM ===========================================================================
REM  PersonalOS - start the application.
REM
REM  Double-click me. On the first run this creates a virtual environment and
REM  downloads the Python packages, which takes a few minutes. Every run after
REM  that opens the browser in about two seconds.
REM ===========================================================================
setlocal enabledelayedexpansion

cd /d "%~dp0" 2>nul

set "HERE=%~dp0"
if "!HERE:~0,2!"=="\\" goto on_share

set "VENV=.venv\Scripts\python.exe"

echo.
echo   PersonalOS
echo   ==========
echo.

REM --- 1. Find Python --------------------------------------------------------
if exist "%VENV%" goto have_venv

set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY goto no_python

echo   [1/4] Creating the virtual environment...
%PY% -m venv .venv
if errorlevel 1 goto venv_failed
echo         done.
echo.
goto install

:have_venv
echo   [1/4] Virtual environment found.

REM --- 2. Dependencies -------------------------------------------------------
"%VENV%" -c "import flask, jinja2, markdown, nh3, yaml, dateutil, openpyxl, requests" >nul 2>&1
if not errorlevel 1 (
    echo   [2/4] Packages already installed.
    goto assets
)

:install
echo   [2/4] Installing Python packages. This takes a few minutes the first
echo         time and needs an internet connection.
echo.
"%VENV%" -m pip install --disable-pip-version-check --quiet --upgrade pip
"%VENV%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto pip_failed

REM Outlook automation. Optional: every Outlook feature reports itself
REM unavailable without it, and the rest of the application is unaffected.
"%VENV%" -m pip install --disable-pip-version-check --quiet pywin32 >nul 2>&1
if errorlevel 1 echo         note: pywin32 did not install; Outlook features stay off.

echo.
echo         done.
echo.

REM --- 3. Bootstrap ----------------------------------------------------------
:assets
if exist "app\static\vendor\bootstrap\bootstrap.min.css" (
    echo   [3/4] Bootstrap already vendored.
    goto launch
)
echo   [3/4] Fetching Bootstrap...
"%VENV%" vendor_assets.py >nul 2>&1
if exist "app\static\vendor\bootstrap\bootstrap.min.css" (
    echo         done.
) else (
    echo         could not download it. PersonalOS looks correct without it -
    echo         see "python vendor_assets.py --help" to add it by hand later.
)

REM --- 4. Run ----------------------------------------------------------------
:launch
echo.
echo   [4/4] Starting. Your browser opens automatically.
echo.
echo   ---------------------------------------------------------------
echo     PersonalOS is running at  http://127.0.0.1:5000
echo     Close this window, or press Ctrl-C, to stop it.
echo   ---------------------------------------------------------------
echo.

"%VENV%" run.py %*
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" goto run_failed
goto end


REM ===========================================================================
REM  Failures. Each says what went wrong and what to do about it.
REM ===========================================================================

:on_share
echo.
echo   PersonalOS cannot run from the WSL share.
echo.
echo   You started it from:
echo       %HERE%
echo.
echo   SQLite over \\wsl$\ does not lock files reliably and will corrupt the
echo   database. Run "Install to Windows.bat" in this same folder instead -
echo   it copies everything to your local disk and starts it from there.
echo.
pause
exit /b 1

:no_python
echo.
echo   Python was not found on this machine.
echo.
echo   Install Python 3.11 or newer from python.org, or from the Microsoft
echo   Store, and tick "Add Python to PATH" during setup. Then run this again.
echo.
pause
exit /b 1

:venv_failed
echo.
echo   Could not create the virtual environment in .venv
echo.
echo   Usually this means the folder is read-only or antivirus blocked it.
echo   Check that you can write to:
echo       %CD%
echo.
pause
exit /b 1

:pip_failed
echo.
echo   Installing the Python packages failed.
echo.
echo   The most common cause on a work laptop is the proxy. Try, in this folder:
echo.
echo       .venv\Scripts\python.exe -m pip install -r requirements.txt --proxy http://YOUR-PROXY:PORT
echo.
echo   Or set HTTPS_PROXY in your environment and run this file again.
echo   The message above the line says exactly which package failed.
echo.
pause
exit /b 1

:run_failed
echo.
echo   PersonalOS stopped with an error (code %EXITCODE%).
echo   The traceback is above - the last few lines say what went wrong.
echo.
echo   To check the installation, run:
echo       .venv\Scripts\python.exe health_check.py
echo.
pause
exit /b %EXITCODE%

:end
endlocal
