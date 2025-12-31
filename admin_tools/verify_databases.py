#!/usr/bin/env python3
"""
Database Verification Utility
Verifies the integrity and structure of all bot databases
"""

import aiosqlite
import asyncio
import os
import sys
from datetime import datetime

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server_configs.database_config import DATABASE_PATHS

class DatabaseVerifier:
    def __init__(self):
        self.issues_found = []
        self.databases_checked = 0
        self.tables_verified = 0
    
    def log_issue(self, severity: str, database: str, message: str):
        """Log an issue found during verification"""
        self.issues_found.append({
            'severity': severity,
            'database': database,
            'message': message,
            'timestamp': datetime.now()
        })
        print(f"[{severity.upper()}] {database}: {message}")
    
    async def verify_database_exists(self, db_name: str, db_path: str) -> bool:
        """Verify that database file exists and is accessible"""
        if not os.path.exists(db_path):
            self.log_issue('ERROR', db_name, f"Database file not found: {db_path}")
            return False
        
        if not os.access(db_path, os.R_OK):
            self.log_issue('ERROR', db_name, f"Database file not readable: {db_path}")
            return False
        
        if not os.access(db_path, os.W_OK):
            self.log_issue('WARNING', db_name, f"Database file not writable: {db_path}")
        
        return True
    
    async def verify_database_connection(self, db_name: str, db_path: str) -> bool:
        """Test database connection"""
        try:
            async with aiosqlite.connect(db_path) as db:
                await db.execute("SELECT 1")
            return True
        except Exception as e:
            self.log_issue('ERROR', db_name, f"Cannot connect to database: {e}")
            return False
    
    async def get_table_info(self, db_path: str) -> list:
        """Get table information from database"""
        try:
            async with aiosqlite.connect(db_path) as db:
                async with db.execute("SELECT name FROM sqlite_master WHERE type='table'") as cursor:
                    tables = await cursor.fetchall()
                return [table[0] for table in tables]
        except Exception as e:
            return []
    
    async def verify_table_structure(self, db_name: str, db_path: str, table_name: str) -> dict:
        """Verify table structure and get basic stats"""
        try:
            async with aiosqlite.connect(db_path) as db:
                # Get table info
                async with db.execute(f"PRAGMA table_info({table_name})") as cursor:
                    columns = await cursor.fetchall()
                
                # Get row count
                async with db.execute(f"SELECT COUNT(*) FROM {table_name}") as cursor:
                    row_count = (await cursor.fetchone())[0]
                
                return {
                    'columns': len(columns),
                    'column_info': columns,
                    'row_count': row_count
                }
        except Exception as e:
            self.log_issue('ERROR', db_name, f"Error verifying table {table_name}: {e}")
            return {}
    
    async def verify_economy_database(self, db_path: str):
        """Specific verification for economy database"""
        tables = await self.get_table_info(db_path)
        
        if 'users' not in tables:
            self.log_issue('ERROR', 'economy', "Missing required 'users' table")
            return
        
        # Check for negative balances
        try:
            async with aiosqlite.connect(db_path) as db:
                async with db.execute("SELECT COUNT(*) FROM users WHERE balance < 0") as cursor:
                    negative_count = (await cursor.fetchone())[0]
                
                if negative_count > 0:
                    self.log_issue('WARNING', 'economy', f"{negative_count} users have negative balances")
                
                # Check for extremely high balances (potential issues)
                async with db.execute("SELECT COUNT(*) FROM users WHERE balance > 1000000") as cursor:
                    high_balance_count = (await cursor.fetchone())[0]
                
                if high_balance_count > 0:
                    self.log_issue('INFO', 'economy', f"{high_balance_count} users have balances over 1,000,000")
        
        except Exception as e:
            self.log_issue('ERROR', 'economy', f"Error checking economy data: {e}")
    
    async def verify_birthday_database(self, db_path: str):
        """Specific verification for birthday database"""
        tables = await self.get_table_info(db_path)
        
        expected_tables = ['birthday_messages']
        for table in expected_tables:
            if table not in tables:
                self.log_issue('WARNING', 'birthday', f"Missing table: {table}")
        
        # Check for invalid dates
        if 'birthday_messages' in tables:
            try:
                async with aiosqlite.connect(db_path) as db:
                    async with db.execute("SELECT COUNT(*) FROM birthday_messages WHERE birthday = '' OR birthday IS NULL") as cursor:
                        invalid_count = (await cursor.fetchone())[0]
                    
                    if invalid_count > 0:
                        self.log_issue('WARNING', 'birthday', f"{invalid_count} entries have invalid/empty birthday dates")
            
            except Exception as e:
                self.log_issue('ERROR', 'birthday', f"Error checking birthday data: {e}")
    
    async def verify_powerups_database(self, db_path: str):
        """Specific verification for powerups database"""
        tables = await self.get_table_info(db_path)
        
        expected_tables = ['powerup_inventory', 'active_powerups']
        for table in expected_tables:
            if table not in tables:
                self.log_issue('ERROR', 'powerups', f"Missing required table: {table}")
        
        # Check for expired active powerups
        if 'active_powerups' in tables:
            try:
                import time
                current_time = int(time.time())
                
                async with aiosqlite.connect(db_path) as db:
                    async with db.execute("SELECT COUNT(*) FROM active_powerups WHERE end_time < ?", (current_time,)) as cursor:
                        expired_count = (await cursor.fetchone())[0]
                    
                    if expired_count > 0:
                        self.log_issue('INFO', 'powerups', f"{expired_count} powerups have expired and should be cleaned up")
            
            except Exception as e:
                self.log_issue('ERROR', 'powerups', f"Error checking powerups data: {e}")
    
    async def verify_all_databases(self):
        """Main verification function"""
        print("🔍 Database Verification Utility")
        print("=" * 50)
        print(f"Checking {len(DATABASE_PATHS)} databases...")
        print()
        
        for db_name, db_path in DATABASE_PATHS.items():
            print(f"📊 Verifying {db_name} database...")
            self.databases_checked += 1
            
            # Check if database exists and is accessible
            if not await self.verify_database_exists(db_name, db_path):
                continue
            
            # Test connection
            if not await self.verify_database_connection(db_name, db_path):
                continue
            
            # Get and display table information
            tables = await self.get_table_info(db_path)
            print(f"  📋 Found {len(tables)} tables: {', '.join(tables) if tables else 'None'}")
            
            # Verify each table
            for table in tables:
                table_info = await self.verify_table_structure(db_name, db_path, table)
                if table_info:
                    print(f"    🔧 {table}: {table_info['columns']} columns, {table_info['row_count']} rows")
                    self.tables_verified += 1
            
            # Run specific verifications
            if db_name == 'economy':
                await self.verify_economy_database(db_path)
            elif db_name == 'birthday':
                await self.verify_birthday_database(db_path)
            elif db_name == 'powerups':
                await self.verify_powerups_database(db_path)
            
            print()
        
        # Summary report
        print("📈 Verification Summary")
        print("=" * 30)
        print(f"Databases checked: {self.databases_checked}")
        print(f"Tables verified: {self.tables_verified}")
        print(f"Issues found: {len(self.issues_found)}")
        
        if self.issues_found:
            print("\n🚨 Issues Found:")
            print("-" * 20)
            
            # Group by severity
            errors = [i for i in self.issues_found if i['severity'] == 'ERROR']
            warnings = [i for i in self.issues_found if i['severity'] == 'WARNING']
            info = [i for i in self.issues_found if i['severity'] == 'INFO']
            
            if errors:
                print(f"❌ {len(errors)} ERRORS:")
                for issue in errors:
                    print(f"  • {issue['database']}: {issue['message']}")
            
            if warnings:
                print(f"⚠️  {len(warnings)} WARNINGS:")
                for issue in warnings:
                    print(f"  • {issue['database']}: {issue['message']}")
            
            if info:
                print(f"ℹ️  {len(info)} INFO:")
                for issue in info:
                    print(f"  • {issue['database']}: {issue['message']}")
        else:
            print("✅ No issues found! All databases are healthy.")
        
        return len(errors) == 0  # Return True if no errors

async def main():
    """Main function"""
    verifier = DatabaseVerifier()
    success = await verifier.verify_all_databases()
    
    print(f"\n{'✅ Verification completed successfully!' if success else '❌ Verification completed with errors!'}")
    return 0 if success else 1

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⏹️  Verification cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        sys.exit(1)