@echo off
rem Find Python 3.12 even when the Windows py launcher is missing.
set "PY_CMD="
where py >nul 2>&1
if not errorlevel 1 (
    py -3.12 -c "import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3.12"
)
if not defined PY_CMD (
    where python >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY_CMD=python"
    )
)
if not defined PY_CMD (
    where python3 >nul 2>&1
    if not errorlevel 1 (
        python3 -c "import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY_CMD=python3"
    )
)
if not defined PY_CMD (
    echo Python 3.12 was not found through py, python or python3.
    echo Open Command Prompt and try: python --version
    echo Install Python 3.12 and enable Add python.exe to PATH if needed.
    exit /b 1
)
exit /b 0
