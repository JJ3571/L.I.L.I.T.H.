#!/bin/bash
echo "Setting up Discord Bot environment..."

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv .venv

# Activate virtual environment
echo "Activating virtual environment..."
source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

echo ""
echo "Setup complete!"
echo "To activate the environment in future sessions, run: source .venv/bin/activate"
echo "To run the bot: python main.py"
echo "To deactivate: deactivate"
