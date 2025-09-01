# Discord Bot Setup Guide

## Quick Setup (Recommended - Virtual Environment)

### 1. Clone the repository
```bash
git clone https://github.com/JJ3571/Discord-Bot-Sandbox.git
cd Discord-Bot-Sandbox
```

### 2. Create virtual environment
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS/Linux
python -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure the bot
- Copy `server_configs/config_template.py` to `server_configs/config.py`
- Copy `server_configs/cogs_config_template.py` to `server_configs/cogs_config.py`
- Fill in your Discord bot token and server configuration

### 5. Run the bot
```bash
python main.py
```

## Alternative Setup (System Python)

If you prefer not to use virtual environments:

```bash
pip install nextcord==2.6.0 aiosqlite==0.21.0
python main.py
```

## Deactivating Virtual Environment

When you're done working:
```bash
deactivate
```

## Updating Dependencies

To update to newer versions:
```bash
pip install --upgrade nextcord aiosqlite
pip freeze > requirements.txt  # Update requirements file
```

## Troubleshooting

- **Permission errors**: Run terminal as administrator (Windows) or use `sudo` (macOS/Linux)
- **Python not found**: Ensure Python is in your PATH
- **Module not found**: Make sure virtual environment is activated or packages are installed
