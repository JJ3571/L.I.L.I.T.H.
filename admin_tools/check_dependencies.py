#!/usr/bin/env python3
"""
Dependency Checker Utility
Verifies all required dependencies are installed and checks for version compatibility
"""

import sys
import subprocess
import importlib
import os

# Try to import optional dependencies for enhanced functionality
try:
    import pkg_resources
    HAS_PKG_RESOURCES = True
except ImportError:
    HAS_PKG_RESOURCES = False

try:
    from packaging import version
    HAS_PACKAGING = True
except ImportError:
    HAS_PACKAGING = False

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class DependencyChecker:
    def __init__(self):
        self.issues_found = []
        self.packages_checked = 0
        self.python_version = sys.version_info
    
    def log_issue(self, severity: str, package: str, message: str):
        """Log a dependency issue"""
        self.issues_found.append({
            'severity': severity,
            'package': package,
            'message': message
        })
        print(f"[{severity.upper()}] {package}: {message}")
    
    def check_python_version(self):
        """Check if Python version is compatible"""
        print(f"🐍 Python Version: {sys.version}")
        
        min_version = (3, 8)
        recommended_version = (3, 9)
        
        if self.python_version < min_version:
            self.log_issue('ERROR', 'Python', f"Python {min_version[0]}.{min_version[1]}+ required, but {self.python_version[0]}.{self.python_version[1]} found")
        elif self.python_version < recommended_version:
            self.log_issue('WARNING', 'Python', f"Python {recommended_version[0]}.{recommended_version[1]}+ recommended for optimal performance")
        else:
            print("✅ Python version is compatible")
        print()
    
    def get_installed_packages(self):
        """Get list of installed packages"""
        if not HAS_PKG_RESOURCES:
            print("⚠️  pkg_resources not available, using basic package detection")
            return {}
        
        try:
            installed_packages = {pkg.project_name.lower(): pkg.version for pkg in pkg_resources.working_set}
            return installed_packages
        except Exception as e:
            self.log_issue('ERROR', 'System', f"Could not get installed packages: {e}")
            return {}
    
    def parse_requirements_file(self, file_path: str):
        """Parse requirements.txt file"""
        requirements = []
        
        if not os.path.exists(file_path):
            self.log_issue('WARNING', 'Requirements', f"Requirements file not found: {file_path}")
            return []
        
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # Handle different requirement formats
                        if '==' in line:
                            name, ver = line.split('==', 1)
                            requirements.append({'name': name.strip(), 'version': ver.strip(), 'operator': '=='})
                        elif '>=' in line:
                            name, ver = line.split('>=', 1)
                            requirements.append({'name': name.strip(), 'version': ver.strip(), 'operator': '>='})
                        elif '>' in line:
                            name, ver = line.split('>', 1)
                            requirements.append({'name': name.strip(), 'version': ver.strip(), 'operator': '>'})
                        else:
                            # No version specified
                            requirements.append({'name': line.strip(), 'version': None, 'operator': None})
            
        except Exception as e:
            self.log_issue('ERROR', 'Requirements', f"Error reading requirements file: {e}")
        
        return requirements
    
    def check_package_installation(self, package_name: str, required_version: str = None, operator: str = None):
        """Check if a package is installed and meets version requirements"""
        self.packages_checked += 1
        
        try:
            # Try to import the package
            if package_name.lower() == 'nextcord':
                import nextcord
                installed_version = nextcord.__version__
            elif package_name.lower() == 'aiosqlite':
                import aiosqlite
                installed_version = aiosqlite.__version__
            elif package_name.lower() == 'discord-webhook':
                import discord_webhook
                installed_version = getattr(discord_webhook, '__version__', 'unknown')
            elif package_name.lower() == 'google-genai':
                import google.genai
                installed_version = getattr(google.genai, '__version__', 'unknown')
            elif package_name.lower() == 'pillow':
                import PIL
                installed_version = PIL.__version__
            else:
                # Generic import attempt
                module = importlib.import_module(package_name.replace('-', '_'))
                installed_version = getattr(module, '__version__', 'unknown')
            
            print(f"✅ {package_name}: {installed_version} installed")
            
            # Check version compatibility if specified
            if required_version and operator and installed_version != 'unknown':
                if HAS_PACKAGING:
                    try:
                        installed_ver = version.parse(installed_version)
                        required_ver = version.parse(required_version)
                        
                        if operator == '==':
                            if installed_ver != required_ver:
                                self.log_issue('WARNING', package_name, f"Version mismatch: {installed_version} installed, {required_version} required")
                        elif operator == '>=':
                            if installed_ver < required_ver:
                                self.log_issue('ERROR', package_name, f"Version too old: {installed_version} installed, >={required_version} required")
                        elif operator == '>':
                            if installed_ver <= required_ver:
                                self.log_issue('ERROR', package_name, f"Version too old: {installed_version} installed, >{required_version} required")
                    except Exception as e:
                        self.log_issue('WARNING', package_name, f"Could not compare versions: {e}")
                else:
                    # Basic string comparison fallback
                    if operator == '==' and installed_version != required_version:
                        self.log_issue('WARNING', package_name, f"Version mismatch: {installed_version} installed, {required_version} required")
                    elif operator in ['>=', '>']:
                        self.log_issue('INFO', package_name, f"Version comparison requires 'packaging' library (installed: {installed_version}, required: {operator}{required_version})")
            
        except ImportError:
            self.log_issue('ERROR', package_name, "Package not installed")
        except Exception as e:
            self.log_issue('ERROR', package_name, f"Error checking package: {e}")
    
    def check_critical_imports(self):
        """Check critical imports that the bot needs"""
        print("🔍 Checking Critical Imports...")
        
        critical_packages = [
            'nextcord',
            'aiosqlite', 
            'asyncio',
            'time',
            'datetime',
            'os',
            're',
            'random'
        ]
        
        for package in critical_packages:
            try:
                importlib.import_module(package)
                print(f"✅ {package}: Available")
            except ImportError:
                self.log_issue('ERROR', package, "Critical import failed")
        print()
    
    def check_optional_features(self):
        """Check optional feature dependencies"""
        print("🔧 Checking Optional Features...")
        
        # Google Gemini AI
        try:
            import google.genai
            print("✅ Google Gemini AI: Available")
        except ImportError:
            self.log_issue('WARNING', 'google-genai', "Gemini AI features will be disabled")
        
        # PIL for image processing
        try:
            import PIL
            print("✅ PIL (Pillow): Available for image processing")
        except ImportError:
            self.log_issue('WARNING', 'Pillow', "Image processing features will be disabled")
        
        # Discord webhooks
        try:
            import discord_webhook
            print("✅ Discord Webhook: Available")
        except ImportError:
            self.log_issue('WARNING', 'discord-webhook', "Webhook features will be disabled")
        
        print()
    
    def check_system_requirements(self):
        """Check system-level requirements"""
        print("💻 System Requirements Check...")
        
        # Check if running in virtual environment
        if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
            print("✅ Running in virtual environment")
        else:
            self.log_issue('WARNING', 'Environment', "Not running in virtual environment (recommended)")
        
        # Check available disk space
        try:
            import shutil
            total, used, free = shutil.disk_usage('.')
            free_gb = free / (1024**3)
            
            if free_gb < 0.1:  # Less than 100MB
                self.log_issue('ERROR', 'Disk Space', f"Very low disk space: {free_gb:.2f}GB free")
            elif free_gb < 1:  # Less than 1GB
                self.log_issue('WARNING', 'Disk Space', f"Low disk space: {free_gb:.2f}GB free")
            else:
                print(f"✅ Disk Space: {free_gb:.2f}GB available")
        except Exception as e:
            self.log_issue('WARNING', 'Disk Space', f"Could not check disk space: {e}")
        
        print()
    
    def suggest_fixes(self):
        """Suggest fixes for found issues"""
        if not self.issues_found:
            return
        
        print("🔧 Suggested Fixes:")
        print("-" * 20)
        
        missing_packages = [i for i in self.issues_found if 'not installed' in i['message']]
        if missing_packages:
            print("To install missing packages:")
            for issue in missing_packages:
                print(f"  pip install {issue['package']}")
            print()
        
        version_issues = [i for i in self.issues_found if 'version' in i['message'].lower()]
        if version_issues:
            print("To fix version issues:")
            for issue in version_issues:
                print(f"  pip install --upgrade {issue['package']}")
            print()
        
        if any('virtual environment' in i['message'] for i in self.issues_found):
            print("To create a virtual environment:")
            print("  python -m venv .venv")
            print("  source .venv/bin/activate  # On Linux/Mac")
            print("  .venv\\Scripts\\activate     # On Windows")
            print()
    
    def run_full_check(self):
        """Run complete dependency check"""
        print("🔍 Discord Bot Dependency Checker")
        print("=" * 50)
        
        # Check Python version
        self.check_python_version()
        
        # Check system requirements
        self.check_system_requirements()
        
        # Check critical imports
        self.check_critical_imports()
        
        # Check requirements.txt
        print("📋 Checking requirements.txt...")
        requirements = self.parse_requirements_file('requirements.txt')
        
        if requirements:
            for req in requirements:
                self.check_package_installation(req['name'], req['version'], req['operator'])
        else:
            print("No requirements.txt found, checking known dependencies...")
            # Fallback to known dependencies
            known_deps = [
                {'name': 'nextcord', 'version': '3.1.1', 'operator': '=='},
                {'name': 'aiosqlite', 'version': '0.21.0', 'operator': '=='},
                {'name': 'aiohttp', 'version': '3.11.11', 'operator': '=='},
                {'name': 'requests', 'version': '2.32.3', 'operator': '=='},
                {'name': 'pytz', 'version': '2024.2', 'operator': '=='},
                {'name': 'discord-webhook', 'version': '1.4.1', 'operator': '=='},
                {'name': 'google-genai', 'version': '1.10.0', 'operator': '=='},
                {'name': 'Pillow', 'version': '11.1.0', 'operator': '=='}
            ]
            for dep in known_deps:
                self.check_package_installation(dep['name'], dep['version'], dep['operator'])
        
        print()
        
        # Check optional features
        self.check_optional_features()
        
        # Summary
        print("📊 Summary:")
        print(f"  Packages checked: {self.packages_checked}")
        print(f"  Issues found: {len(self.issues_found)}")
        
        # Group issues by severity
        errors = [i for i in self.issues_found if i['severity'] == 'ERROR']
        warnings = [i for i in self.issues_found if i['severity'] == 'WARNING']
        
        if errors:
            print(f"  ❌ Critical errors: {len(errors)}")
        if warnings:
            print(f"  ⚠️  Warnings: {len(warnings)}")
        
        if not self.issues_found:
            print("  ✅ All dependencies satisfied!")
        
        print()
        
        # Suggest fixes
        self.suggest_fixes()
        
        return len(errors) == 0

def main():
    """Main function"""
    checker = DependencyChecker()
    success = checker.run_full_check()
    
    if success:
        print("🎉 All critical dependencies are satisfied!")
        return 0
    else:
        print("⚠️  Some issues need attention before running the bot.")
        return 1

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⏹️  Dependency check cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error during dependency check: {e}")
        sys.exit(1)