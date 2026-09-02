@echo off
REM ===========================================================================
REM  PersonalOS - copy from the WSL repository to this Windows machine.
REM
REM  Double-click this from Explorer at:
REM      \\wsl$\Ubuntu\home\bsims\00_AI_Dev_Projects\PersonalOS
REM
REM  It copies the application to C:\Users\<you>\PersonalOS and starts it.
REM  Safe to run again later to pick up changes: your database, backups and
REM  notes are never overwritten.
REM ===========================================================================
setlocal

set "SOURCE=%~dp0"
set "TARGET=%USERPROFILE%\PersonalOS"

echo.
echo   Installing PersonalOS
echo   ---------------------
echo   From:  %SOURCE%
echo   To:    %TARGET%
echo.

REM SQLite must never run over the \\wsl$\ share - the 9p filesystem does not
REM honour file locking reliably and will corrupt the database. That is the
REM whole reason this copy exists.
if "%SOURCE:~0,2%"=="\\" (
    echo   Source is the WSL share, so a local copy is required. That is what
    echo   this does.
    echo.
)

if exist "%TARGET%\app\data\personalos.db" (
    echo   An existing installation was found.
    echo   Your database, backups, notes and settings will be left alone.
    echo   Only program files are updated.
    echo.
)

choice /C YN /N /M "   Continue? [Y/N] "
if errorlevel 2 goto cancelled

echo.
echo   Copying...
echo.

REM /E        include subdirectories, even empty ones
REM /XD       never touch user data, the git history, or either virtualenv
REM /NFL /NDL quiet: no per-file or per-directory lines
robocopy "%SOURCE%." "%TARGET%" /E /R:1 /W:1 /NFL /NDL /NJH ^
    /XD ".git" ".venv" "venv" "__pycache__" "node_modules" ".pytest_cache" "data" ^
    /XF "*.pyc" "*:Zone.Identifier" "*:sec.endpointdlp"

if errorlevel 8 goto copyfailed

echo.
echo   Files copied.
echo.

REM --- Desktop shortcut ------------------------------------------------------
set "SHORTCUT=%USERPROFILE%\Desktop\PersonalOS.lnk"
if not exist "%SHORTCUT%" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%SHORTCUT%');" ^
      "$s.TargetPath='%TARGET%\Start PersonalOS.bat';" ^
      "$s.WorkingDirectory='%TARGET%';" ^
      "$s.Description='PersonalOS';" ^
      "$s.Save()" >nul 2>&1
    if exist "%SHORTCUT%" echo   Shortcut added to your Desktop.
)

echo.
echo   Installed to %TARGET%
echo.
echo   The first start downloads Python packages and takes a few minutes.
echo   After that it opens in about two seconds.
echo.

choice /C YN /N /M "   Start PersonalOS now? [Y/N] "
if errorlevel 2 goto done

start "" "%TARGET%\Start PersonalOS.bat"
goto done

:copyfailed
echo.
echo   The copy failed. Robocopy returned %ERRORLEVEL%.
echo.
echo   The usual cause is that Explorer cannot reach the WSL share. Open a
echo   terminal, run:  wsl --shutdown   then try again.
echo.
pause
exit /b 1

:cancelled
echo.
echo   Cancelled. Nothing was copied.
echo.
pause
exit /b 1

:done
endlocal
