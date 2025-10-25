@echo off

REM Check if 'venv' folder exists
if exist venv (
    echo [INFO] Virtual environment 'venv' already exists.
    call venv\Scripts\activate
) else (
    REM Create virtual environment named "venv"
    python -m venv venv

    REM Activate the virtual environment
    call venv\Scripts\activate

    REM Install dependencies from requirements.txt
    pip install -r requirements.txt

    echo.
    echo [INFO] Setup complete. Virtual environment 'venv' is ready and requirements are installed.
)

echo To activate later, run:
echo   venv\Scripts\activate
echo.

echo Running main.py...
python main.py

