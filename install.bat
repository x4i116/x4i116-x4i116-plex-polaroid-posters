@echo off
cd /d "%~dp0"
echo Installing the libraries this tool needs...
echo.
where py >nul 2>nul
if errorlevel 1 (
  echo Python wasn't found.
  echo Install it from https://www.python.org/downloads/ and tick
  echo "Add python.exe to PATH" on the first screen, then run this again.
  echo.
  pause
  exit /b 1
)
py -m pip install -r requirements.txt
echo.
if errorlevel 1 (
  echo Something went wrong - see the messages above.
) else (
  echo All set. Now double-click run.bat
)
echo.
pause
