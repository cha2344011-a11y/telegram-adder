@echo off
echo ========================================
echo  Telegram Migration Tool - Starting...
echo ========================================
echo.
echo Dashboard will open at: http://127.0.0.1:5000
echo Press CTRL+C to stop the server.
echo.
start "" http://127.0.0.1:5000
python app.py
pause
