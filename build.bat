@echo off
rem ساخت نسخه قابل اجرا و بررسی سلامت آن.
setlocal
cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"
set "APP=dist\AI Desktop Assistant\AI Desktop Assistant.exe"

if not exist "%PYTHON%" (
    echo [build] محیط مجازی پیدا نشد. اول این دستورها را اجرا کنید:
    echo [build]   python -m venv .venv
    echo [build]   .venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)

echo [build] تست‌ها...
"%PYTHON%" -m pytest tests -q || exit /b 1

echo [build] بسته‌بندی برنامه...
"%PYTHON%" -m PyInstaller --noconfirm --clean "ai_desktop_assistant.spec" || exit /b 1

echo [build] بررسی سلامت نسخه ساخته‌شده...
"%APP%" --self-check || exit /b 1

where ISCC.exe >nul 2>nul
if %errorlevel% equ 0 (
    echo [build] ساخت نصاب ویندوز...
    ISCC.exe "installer.iss" || exit /b 1
    echo [build] نصاب آماده است: installer\AI-Desktop-Assistant-Setup.exe
) else (
    echo [build] Inno Setup پیدا نشد؛ نسخه قابل حمل آماده است: %APP%
)

echo [build] آماده است: %APP%
exit /b 0
