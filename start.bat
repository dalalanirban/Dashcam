@echo off
echo =========================================
echo    Dashcam Smart Editor - Launcher
echo =========================================
echo.

echo [1/3] Starting Python FastAPI Backend...
start "Dashcam Backend (FastAPI)" cmd /c "cd /d D:\Dashcam\backend && D:\Dashcam\.venv\Scripts\python.exe -m uvicorn app:app --reload --port 8000"

echo [2/3] Starting React Frontend...
start "Dashcam Frontend (Vite)" cmd /c "cd /d D:\Dashcam\frontend && npm run dev"

echo.
echo Waiting for servers to initialize...
timeout /t 4 /nobreak >nul

echo [3/3] Opening browser...
start http://localhost:5173/

echo.
echo Success! The application should now be open in your browser.
echo To stop the application, close this window and the two newly opened server windows.
echo.
pause
