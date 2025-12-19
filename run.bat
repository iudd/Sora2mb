@echo off
setlocal
cd /d "%~dp0"

echo [INFO] Checking Python...
where python >nul 2>&1 || (
  echo [ERROR] Python not found. Install Python 3.8+ and add to PATH.
  pause
  exit /b 1
)

set PORT=8080
for /f "tokens=*" %%i in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do set PORT_IN_USE=1
if defined PORT_IN_USE (
  echo [ERROR] Port %PORT% is in use. Close it or change config/setting.toml.
  pause
  exit /b 1
)

if not exist venv\Scripts\python.exe (
  echo [INFO] Creating venv...
  python -m venv venv || (pause & exit /b 1)
)

call venv\Scripts\activate.bat || (pause & exit /b 1)

echo [INFO] Installing dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo [WARN] Mirror failed. Retrying with PyPI...
  python -m pip install -r requirements.txt -i https://pypi.org/simple || (pause & exit /b 1)
)

echo [INFO] Starting server...
python main.py
