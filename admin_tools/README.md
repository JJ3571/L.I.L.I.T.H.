# Admin Tools

This folder contains administrative utilities for maintaining and troubleshooting the Discord Bot.

## Available Tools

### 🔍 `verify_databases.py`
**Database Integrity Checker**

Verifies the integrity and structure of all bot databases.

**Usage:**
```bash
python admin_tools/verify_databases.py
```

**Features:**
- Checks database file existence and accessibility
- Verifies database connections
- Analyzes table structures and row counts
- Specific validation for economy, birthday, and powerups databases
- Identifies common data issues (negative balances, invalid dates, etc.)
- Provides detailed summary reports

**Exit Codes:**
- `0`: All databases healthy
- `1`: Critical errors found

---

### 📦 `check_dependencies.py`
**Dependency Verification Tool**

Checks that all required Python packages are installed and compatible.

**Usage:**
```bash
python admin_tools/check_dependencies.py
```

**Features:**
- Python version compatibility check
- Virtual environment detection
- Critical import verification
- Requirements.txt parsing and validation
- Version compatibility checking
- Optional feature availability
- System requirements (disk space, etc.)
- Automated fix suggestions

**Exit Codes:**
- `0`: All critical dependencies satisfied
- `1`: Critical dependencies missing or incompatible

---

### 🎂 `birthday_cleanup.py`
**Birthday Database Cleanup**

Removes invalid or empty birthday entries from the database.

**Usage:**
```bash
python admin_tools/birthday_cleanup.py
```

**Features:**
- Interactive cleanup process
- Identifies empty/invalid birthday dates
- Safe deletion with user confirmation
- Shows remaining valid entries
- Prevents database corruption issues

---

### 🗂️ `db_helper.py`
**General Database Helper**

General database maintenance utilities.

---

### 📁 `file_renamer.py`
**File Management Tool**

Utility for batch file operations.

## Usage Guidelines

### Before Running the Bot
1. **Check Dependencies**: Run `check_dependencies.py` to ensure all packages are installed
2. **Verify Databases**: Run `verify_databases.py` to check database integrity
3. **Clean Data**: Use `birthday_cleanup.py` if birthday-related errors occur

### Regular Maintenance
- Run `verify_databases.py` weekly to catch data issues early
- Use `check_dependencies.py` after updating packages
- Run `birthday_cleanup.py` if seeing date parsing errors

### Troubleshooting

**Common Issues:**

1. **"Package not installed" errors**
   - Run `check_dependencies.py` for specific fix commands
   - Usually resolved with `pip install <package>`

2. **Database corruption warnings**
   - Run `verify_databases.py` for detailed analysis
   - Check specific database files for issues

3. **Birthday date parsing errors**
   - Run `birthday_cleanup.py` to remove invalid entries
   - Check bot logs for specific error patterns

4. **Permission errors**
   - Ensure bot has read/write access to databases folder
   - Check file permissions: `ls -la databases/`

### Environment Setup

The tools automatically detect your Python environment but work best when:
- Running in a virtual environment
- All dependencies from `requirements.txt` are installed
- Database files are accessible and not corrupted

### Exit Codes

All tools follow standard Unix exit code conventions:
- `0`: Success, no issues found
- `1`: Errors found that need attention
- `2`: Tool execution failed (usually permissions or missing files)

## Contributing

When adding new admin tools:
1. Follow the existing code structure and error handling patterns
2. Include comprehensive help text and status messages
3. Use appropriate exit codes
4. Add documentation to this README
5. Test with various edge cases and error conditions