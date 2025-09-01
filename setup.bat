@echo off
echo Setting up Discord Bot environment...

REM Create virtual environment
echo Creating virtual environment...
python -m venv .venv

REM Activate virtual environment
echo Activating virtual environment...
call .venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt

REM Verify installation
echo.
echo Verifying dependencies...
python check_dependencies.py

echo.
echo Setup complete! 
echo To activate the environment in future sessions, run: .venv\Scripts\activate.bat
echo To run the bot: python main.py
echo To deactivate: deactivate
pause
