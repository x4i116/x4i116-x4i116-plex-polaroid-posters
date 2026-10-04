@echo off
setlocal
cd /d "%~dp0"
set "TASKNAME=Plex Polaroid Posters"
if /i "%~1"=="auto" goto auto
title Plex Polaroid Posters

:start
set "PLEX_URL="
set "PLEX_TOKEN="
set "PLEX_LIBRARY="
set "PLEX_TV_LIBRARY="
set "PLEX_EPISODES="
if exist settings.bat call settings.bat
if "%PLEX_TOKEN%"=="" goto setup
if "%PLEX_TV_LIBRARY%"=="" goto asktv
if "%PLEX_EPISODES%"=="" goto askeps
goto menu

:setup
echo.
echo ===== First-time setup =====
echo (see README.md for how to find your Plex token)
echo.
set "PLEX_URL=http://localhost:32400"
set /p "PLEX_URL=Plex server address [press Enter for http://localhost:32400]: "
set /p "PLEX_TOKEN=Plex token: "
if "%PLEX_TOKEN%"=="" (
  echo You need to enter a token.
  goto setup
)
set "PLEX_LIBRARY=Movies"
set /p "PLEX_LIBRARY=Movie library name [press Enter for Movies]: "

:asktv
set "PLEX_TV_LIBRARY=TV Shows"
set /p "PLEX_TV_LIBRARY=TV library name [press Enter for TV Shows, or type none]: "

:askeps
set "PLEX_EPISODES=no"
if /i "%PLEX_TV_LIBRARY%"=="none" goto save
echo.
echo Episodes can get wide polaroid thumbnails too. The first run can take
echo hours on a big TV library (it resumes if interrupted).
set "ans="
set /p "ans=Do episodes as well? Type Y for yes, or press Enter for no: "
if /i "%ans%"=="Y" set "PLEX_EPISODES=yes"

:save
> settings.bat echo set "PLEX_URL=%PLEX_URL%"
>> settings.bat echo set "PLEX_TOKEN=%PLEX_TOKEN%"
>> settings.bat echo set "PLEX_LIBRARY=%PLEX_LIBRARY%"
>> settings.bat echo set "PLEX_TV_LIBRARY=%PLEX_TV_LIBRARY%"
>> settings.bat echo set "PLEX_EPISODES=%PLEX_EPISODES%"
echo Saved to settings.bat

:menu
call :buildargs
set "SCHED=off"
schtasks /Query /TN "%TASKNAME%" >nul 2>&1 && set "SCHED=on"
echo.
echo ==============================================
echo   Plex Polaroid Posters
echo   Libraries: %SHOWING%
echo ==============================================
echo   1  Preview 10 posters per library (doesn't change Plex)
echo   2  Apply to library (skips anything already done)
echo   3  Redo everything
echo   4  Restore original posters
echo   5  Change settings
echo   6  Quit
if exist "poster_backups\_redo_progress.txt" echo   7  Continue unfinished redo
echo   8  Nightly automatic run  [currently %SCHED%]
echo.
set "choice="
set /p "choice=Pick a number: "

if "%choice%"=="1" goto preview
if "%choice%"=="2" goto apply
if "%choice%"=="3" goto redo
if "%choice%"=="4" goto restore
if "%choice%"=="5" goto settings
if "%choice%"=="6" exit /b
if "%choice%"=="7" if exist "poster_backups\_redo_progress.txt" goto continue
if "%choice%"=="8" goto schedule
goto menu

:preview
py plex_polaroid.py %LIBS% %EPS% --dry-run --limit 10 --force
echo.
echo Opening the preview folder...
if exist polaroid_preview start "" "polaroid_preview"
pause
goto menu

:apply
py plex_polaroid.py %LIBS% %EPS%
pause
goto menu

:redo
if exist "poster_backups\_redo_progress.txt" goto redo_unfinished
set "sure="
set /p "sure=This redoes EVERYTHING, even finished ones. Type Y to continue: "
if /i not "%sure%"=="Y" goto menu
py plex_polaroid.py %LIBS% %EPS% --force
pause
goto menu

:redo_unfinished
echo.
echo There's an unfinished redo from before.
set "sure="
set /p "sure=Type C to continue it, N to start a new redo from scratch, or Enter to cancel: "
if /i "%sure%"=="C" goto continue
if /i not "%sure%"=="N" goto menu
py plex_polaroid.py %LIBS% %EPS% --force --fresh
pause
goto menu

:continue
py plex_polaroid.py --continue
pause
goto menu

:restore
set "sure="
set /p "sure=Put the original posters back on everything? Type Y to continue: "
if /i not "%sure%"=="Y" goto menu
py plex_polaroid.py %LIBS% --restore
pause
goto menu

:settings
if exist settings.bat del settings.bat
goto start

:schedule
if /i "%SCHED%"=="on" goto schedule_manage
echo.
echo This runs option 2 automatically every night, so anything new you add
echo to Plex gets its poster without you doing anything. Your PC needs to be
echo on (if it was off or asleep at that time, it runs as soon as it can).
goto schedule_time

:schedule_manage
echo.
echo The nightly automatic run is ON.
set "sure="
set /p "sure=Type T to change the time, R to remove it, L to see the last run's log, or Enter to go back: "
if /i "%sure%"=="T" goto schedule_time
if /i "%sure%"=="L" goto schedule_log
if /i not "%sure%"=="R" goto menu
schtasks /Delete /TN "%TASKNAME%" /F >nul
echo Nightly automatic run removed.
pause
goto menu

:schedule_log
if exist last_scheduled_run.log (start "" notepad "last_scheduled_run.log") else (echo It hasn't run yet.& pause)
goto menu

:schedule_time
set "RUNAT=03:00"
set /p "RUNAT=What time each night? 24-hour, like 03:00 or 23:30 [press Enter for 03:00]: "
schtasks /Create /TN "%TASKNAME%" /TR "\"%~dp0run.bat\" auto" /SC DAILY /ST %RUNAT% /F >nul
if errorlevel 1 (
  echo Couldn't set that up - make sure the time looks like 03:00.
  pause
  goto menu
)
rem Run as soon as possible if the PC was off/asleep, and don't stop on battery
powershell -NoProfile -Command "$t = Get-ScheduledTask -TaskName '%TASKNAME%'; $t.Settings.StartWhenAvailable = $true; $t.Settings.DisallowStartIfOnBatteries = $false; $t.Settings.StopIfGoingOnBatteries = $false; Set-ScheduledTask -InputObject $t | Out-Null" >nul 2>&1
echo.
echo Done - it will run every night at %RUNAT%.
echo Each run's output is saved to last_scheduled_run.log in this folder.
pause
goto menu

rem ---------------------------------------------------------------------
rem  Scheduled (unattended) run: "run.bat auto"
rem ---------------------------------------------------------------------
:auto
if not exist settings.bat (
  echo No settings.bat - run run.bat normally once first. > last_scheduled_run.log
  exit /b 1
)
call settings.bat
call :buildargs
set "PYTHONIOENCODING=utf-8"
> last_scheduled_run.log echo ===== Scheduled run %date% %time% =====
py plex_polaroid.py %LIBS% %EPS% >> last_scheduled_run.log 2>&1
>> last_scheduled_run.log echo ===== Finished %date% %time% =====
exit /b

rem ---------------------------------------------------------------------
:buildargs
set "LIBS=--library "%PLEX_LIBRARY%""
set "SHOWING=%PLEX_LIBRARY%"
if /i not "%PLEX_TV_LIBRARY%"=="none" set "LIBS=%LIBS% --library "%PLEX_TV_LIBRARY%""
if /i not "%PLEX_TV_LIBRARY%"=="none" set "SHOWING=%PLEX_LIBRARY% + %PLEX_TV_LIBRARY%"
set "EPS="
if /i "%PLEX_EPISODES%"=="yes" set "EPS=--episodes"
if /i "%PLEX_EPISODES%"=="yes" set "SHOWING=%SHOWING% (with episodes)"
exit /b
