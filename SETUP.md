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

**What gets installed:**
- `nextcord` - Modern Discord API wrapper
- `aiosqlite` - Async SQLite database operations
- `aiohttp` - Async HTTP client for API calls
- `requests` - HTTP library for synchronous requests  
- `pytz` - Timezone calculations
- `discord-webhook` - Webhook support for bot messages
- `google-genai` & `google-generativeai` - Google AI/Gemini integration

### 4. Configure the bot
- Copy `server_configs/config_template.py` to `server_configs/config.py`
- Copy `server_configs/cogs_config_template.py` to `server_configs/cogs_config.py`
- Fill in your Discord bot token and server configuration

**Note:** Database files are automatically created in the `databases/` folder when the bot runs.

### 5. Verify setup (optional)
```bash
python verify_databases.py  # Check database paths
python check_dependencies.py  # Check all dependencies
```

### 6. Run the bot
```bash
python main.py
```

## Project Structure

```
Discord-Bot-Sandbox/
├── databases/           # Database files (auto-created)
│   ├── birthday.db
│   ├── economy.db
│   ├── waterboard.db
│   └── ...
├── cogs/               # Bot command modules
│   ├── production/     # Live bot features
│   └── testing/        # Development features
├── server_configs/     # Configuration files
└── requirements.txt    # Python dependencies
```

## Bot Features

This Discord bot includes the following cogs/modules:

**Production Cogs:**
- `8ball` - Magic 8-ball responses
- `birthday` - Birthday tracking and announcements
- `botstatus` - Bot status management
- `buzzer` - Buzzer/alert system
- `counter` - Various counting mechanisms
- `economy` - Virtual economy system with coins
- `event2` - Event management
- `gambling` - Casino-style games
- `greek_god` - Greek mythology game/system
- `movie` - Movie information lookup (OMDB API)
- `pokemon` - Pokemon-related features
- `powerups` - Power-up system
- `requests` - Request management system
- `roulette` - Roulette gambling game
- `say` - Text-to-speech and AI chat features (Gemini AI)
- `tcg` - Trading card game integration
- `voice` - Voice channel management
- `wager` - Betting system
- `watchparty` - Watch party coordination

**Testing Cogs:**
- `waterboard2` - Voice channel "waterboarding" (moving users between channels)
- `economy_copy` - Economy system testing
- `voice_copy` - Voice features testing

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
