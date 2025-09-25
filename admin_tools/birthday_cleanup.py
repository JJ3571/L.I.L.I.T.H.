#!/usr/bin/env python3
"""
Birthday Database Cleanup Utility
Fixes empty or invalid date entries in the birthday database
"""

import aiosqlite
import asyncio
import os
import sys

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server_configs.database_config import DATABASE_PATHS

async def cleanup_birthday_database():
    """Clean up invalid date entries in birthday database"""
    db_path = DATABASE_PATHS["birthday"]
    
    if not os.path.exists(db_path):
        print(f"Birthday database not found at: {db_path}")
        return
    
    print(f"Cleaning up birthday database: {db_path}")
    
    async with aiosqlite.connect(db_path) as db:
        # Find empty or invalid birthday entries
        print("\n=== Checking for invalid birthday entries ===")
        
        # Check birthday_messages table
        async with db.execute("SELECT user_id, message_id, birthday FROM birthday_messages WHERE birthday = '' OR birthday IS NULL") as cursor:
            invalid_messages = await cursor.fetchall()
        
        if invalid_messages:
            print(f"Found {len(invalid_messages)} invalid entries in birthday_messages:")
            for user_id, message_id, birthday in invalid_messages:
                print(f"  User ID: {user_id}, Message ID: {message_id}, Birthday: '{birthday}'")
            
            # Option to delete these entries
            response = input("\nDelete these invalid entries? (y/N): ").strip().lower()
            if response == 'y':
                await db.execute("DELETE FROM birthday_messages WHERE birthday = '' OR birthday IS NULL")
                await db.commit()
                print(f"Deleted {len(invalid_messages)} invalid entries from birthday_messages")
        else:
            print("No invalid entries found in birthday_messages")
        
        # Check main birthdays table (if it exists)
        try:
            async with db.execute("SELECT user_id, birthday FROM birthdays WHERE birthday = '' OR birthday IS NULL") as cursor:
                invalid_birthdays = await cursor.fetchall()
            
            if invalid_birthdays:
                print(f"\nFound {len(invalid_birthdays)} invalid entries in birthdays:")
                for user_id, birthday in invalid_birthdays:
                    print(f"  User ID: {user_id}, Birthday: '{birthday}'")
                
                # Option to delete these entries
                response = input("\nDelete these invalid entries? (y/N): ").strip().lower()
                if response == 'y':
                    await db.execute("DELETE FROM birthdays WHERE birthday = '' OR birthday IS NULL")
                    await db.commit()
                    print(f"Deleted {len(invalid_birthdays)} invalid entries from birthdays")
            else:
                print("No invalid entries found in birthdays table")
                
        except aiosqlite.OperationalError:
            print("No 'birthdays' table found (this is normal if only using birthday_messages)")
        
        # Show remaining valid entries
        print("\n=== Valid birthday entries ===")
        try:
            async with db.execute("SELECT user_id, birthday FROM birthday_messages WHERE birthday != '' AND birthday IS NOT NULL") as cursor:
                valid_entries = await cursor.fetchall()
            
            if valid_entries:
                print(f"Found {len(valid_entries)} valid entries:")
                for user_id, birthday in valid_entries[:10]:  # Show first 10
                    print(f"  User ID: {user_id}, Birthday: {birthday}")
                if len(valid_entries) > 10:
                    print(f"  ... and {len(valid_entries) - 10} more")
            else:
                print("No valid entries found")
                
        except Exception as e:
            print(f"Error checking valid entries: {e}")

if __name__ == "__main__":
    print("Birthday Database Cleanup Utility")
    print("=" * 40)
    asyncio.run(cleanup_birthday_database())
    print("\nCleanup complete!")