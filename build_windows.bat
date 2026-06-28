@echo off
:: ============================================================
:: Swimming Results Scraper — Windows EXE Builder
:: Run this script once on any Windows machine that has Python.
:: The finished exe will appear in the dist\ folder.
:: ============================================================

setlocal enabledelayedexpansion

echo ============================================================
echo  Swimming Results Scraper — Windows Build Script
echo ============================================================
echo.

:: ── 1. Check Python ──────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo Found: %%v

:: ── 2. Install / upgrade dependencies ────────────────────────
echo.
echo [1/3] Installing dependencies...
python -m pip install --upgrade pip --quiet
python -m pip install pyinstaller customtkinter requests --quiet
if errorlevel 1 (
    echo [ERROR] pip install failed. Check your internet connection.
    pause
    exit /b 1
)
echo       Done.

:: ── 3. Copy icon if not already present ──────────────────────
if not exist icon.ico (
    echo.
    echo [INFO] No icon.ico found — looking for CustomTkinter bundled icon...
    for /f "delims=" %%i in ('python -c "import customtkinter, os; print(os.path.join(os.path.dirname(customtkinter.__file__), 'assets', 'icons', 'CustomTkinter_icon_Windows.ico'))"') do (
        if exist "%%i" (
            copy /y "%%i" icon.ico >nul
            echo       Copied %%i
        )
    )
)

:: ── 4. Run PyInstaller ────────────────────────────────────────
echo.
echo [2/3] Building executable (this may take a minute)...
python -m PyInstaller timescraper.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller failed. See output above for details.
    pause
    exit /b 1
)

:: ── 5. Copy config.json next to the exe ──────────────────────
echo.
echo [3/3] Copying config.json to dist\...
if exist config.json (
    copy /y config.json dist\config.json >nul
    echo       config.json copied.
) else (
    echo       No config.json found — the app will use built-in defaults.
)

:: ── Done ─────────────────────────────────────────────────────
echo.
echo ============================================================
echo  Build complete!
echo  Executable: dist\SwimmingResultsScraper.exe
echo ============================================================
echo.
echo You can distribute dist\SwimmingResultsScraper.exe (and
echo optionally dist\config.json) to users — no Python needed.
echo.
pause
