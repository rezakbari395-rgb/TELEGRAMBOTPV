@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv (
    echo [1/3] ساخت محیط مجازی...
    python -m venv venv
)
call venv\Scripts\activate.bat
echo [2/3] نصب کتابخانه‌ها...
pip install -q -r requirements.txt
echo [3/3] اجرای ربات... (برای توقف: Ctrl+C)
python main.py
pause
