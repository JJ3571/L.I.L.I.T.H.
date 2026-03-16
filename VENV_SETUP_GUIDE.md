# Virtual Environment Setup Guide

## Common Issues and Solutions

### Issue 1: Missing Package Versions
**Problem:** Packages without version pins can cause compatibility issues.

**Solution:** All packages in `requirements.txt` now have specific versions pinned. This ensures consistent installations across different environments.

### Issue 2: nextcord Version Errors
**Problem:** `nextcord` version depends on your Python version:
- **Python 3.12+:** Can use `nextcord==3.1.1` or later
- **Python 3.8-3.11:** Must use `nextcord==2.6.0` or earlier (2.x series)

**Solution:** `nextcord==2.6.0` is now pinned for Python 3.11 compatibility.

**If you still get errors:**
```bash
# Uninstall any existing nextcord
pip uninstall nextcord -y

# Reinstall the specific version
pip install nextcord==2.6.0
```

**To upgrade to nextcord 3.x (requires Python 3.12+):**
1. Upgrade Python to 3.12 or later
2. Update requirements.txt to `nextcord==3.1.1`
3. Reinstall: `pip install -r requirements.txt`

### Issue 3: PyNaCl Installation Issues (Windows)
**Problem:** PyNaCl may fail to install on Windows without proper build tools.

**Solution:**
```bash
# Option 1: Install pre-built wheel
pip install PyNaCl==1.5.0

# Option 2: If that fails, install Visual C++ Build Tools
# Download from: https://visualstudio.microsoft.com/visual-cpp-build-tools/
# Then retry: pip install PyNaCl==1.5.0
```

### Issue 4: yt-dlp Updates
**Problem:** yt-dlp updates frequently and old versions may stop working.

**Solution:** If YouTube/SoundCloud extraction fails, update yt-dlp:
```bash
pip install --upgrade yt-dlp
```

## Step-by-Step Setup

### 1. Create Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python -m venv venv
source venv/bin/activate
```

### 2. Upgrade pip (Important!)
```bash
python -m pip install --upgrade pip
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Verify Installation
```bash
# Check installed packages
pip list

# Verify critical packages
python -c "import nextcord; print(f'nextcord version: {nextcord.__version__}')"
python -c "import aiosqlite; print('aiosqlite: OK')"
python -c "import yt_dlp; print('yt-dlp: OK')"
python -c "import nacl; print('PyNaCl: OK')"
```

### 5. System Dependencies (Not in requirements.txt)

**FFmpeg** (Required for music bot):
- **Windows:** Download from https://ffmpeg.org/download.html and add to PATH
- **macOS:** `brew install ffmpeg`
- **Linux:** `sudo apt install ffmpeg` or `sudo yum install ffmpeg`

Verify FFmpeg:
```bash
ffmpeg -version
```

## Troubleshooting

### "ModuleNotFoundError" After Installation
1. Ensure virtual environment is activated (you should see `(venv)` in terminal)
2. Verify package is in requirements.txt
3. Reinstall: `pip install -r requirements.txt --force-reinstall`

### "nextcord.errors" or Import Errors
1. Check Python version: `python --version` (should be 3.8+)
2. Reinstall nextcord: `pip uninstall nextcord && pip install nextcord==3.1.1`
3. Clear pip cache: `pip cache purge`

### Voice Features Not Working
1. Verify PyNaCl is installed: `pip show PyNaCl`
2. Verify FFmpeg is installed: `ffmpeg -version`
3. Check voice intents are enabled in `main.py`

### Database Errors
1. Ensure `databases/` folder exists (auto-created on first run)
2. Check file permissions
3. Verify aiosqlite is installed: `pip show aiosqlite`

## Package Versions Summary

| Package | Version | Purpose |
|---------|---------|---------|
| nextcord | 2.6.0 | Discord API wrapper (Python 3.8-3.11 compatible) |
| aiosqlite | 0.21.0 | Async SQLite |
| aiohttp | 3.11.11 | Async HTTP client |
| requests | 2.32.3 | HTTP library |
| pytz | 2024.2 | Timezone support |
| discord-webhook | 1.4.1 | Webhook support |
| google-genai | 1.10.0 | Gemini AI |
| Pillow | 11.1.0 | Image processing |
| yt-dlp | 2024.8.6 | Audio extraction |
| PyNaCl | 1.5.0 | Voice encryption |

## Quick Fix Commands

```bash
# Complete reinstall
pip uninstall -r requirements.txt -y
pip install -r requirements.txt

# Update pip and reinstall
python -m pip install --upgrade pip
pip install -r requirements.txt --upgrade

# Check for conflicts
pip check
```

