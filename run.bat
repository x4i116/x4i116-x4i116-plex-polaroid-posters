@echo off
setlocal
cd /d "%~dp0"
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
set "LIBS=--library "%PLEX_LIBRARY%""
set "SHOWING=%PLEX_LIBRARY%"
if /i not "%PLEX_TV_LIBRARY%"=="none" set "LIBS=%LIBS% --library "%PLEX_TV_LIBRARY%""
if /i not "%PLEX_TV_LIBRARY%"=="none" set "SHOWING=%PLEX_LIBRARY% + %PLEX_TV_LIBRARY%"
set "EPS="
if /i "%PLEX_EPISODES%"=="yes" set "EPS=--episodes"
if /i "%PLEX_EPISODES%"=="yes" set "SHOWING=%SHOWING% (with episodes)"
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
echo.
set "choice="
set /p "choice=Pick a number: "

if "%choice%"=="1" goto preview
if "%choice%"=="2" goto apply
if "%choice%"=="3" goto redo
if "%choice%"=="4" goto restore
if "%choice%"=="5" goto settings
if "%choice%"=="6" exit /b
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
set "sure="
set /p "sure=This redoes EVERYTHING, even finished ones. Type Y to continue: "
if /i not "%sure%"=="Y" goto menu
py plex_polaroid.py %LIBS% %EPS% --force
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
