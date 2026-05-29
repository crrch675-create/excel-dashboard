@echo off
cd /d "%~dp0"
echo ==========================================
echo  Keiei Dashboard - Kido Chu...
echo  Browser ga jido de hirakimasu.
echo  Shuryo suru ni wa Ctrl+C wo oshite kudasai.
echo ==========================================
echo.
"C:\Users\crrch\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m streamlit run app.py --browser.gatherUsageStats false
pause
