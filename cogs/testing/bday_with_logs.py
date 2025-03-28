import nextcord
from nextcord.ext import commands, tasks
import sqlite3
from datetime import datetime, timedelta
import pytz
import logging
import asyncio

from server_configs.cogs_config import admin_user_ids, birthday_announcement_channel_id, birthday_reaction_channel_id, birthday_role_id, birthday_emoji_id

class Birthday(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "birthday.db"
        self.create_tables()
        self.check_birthdays.start()
        self.cleanup_birthdays.start()
        self.lock = asyncio.Lock()  # Initialize lock
        self.log_channel = None # place holder, set in setup
        self.logger = logging.getLogger('nextcord')

    async def setup_logging(self):
        self.log_channel = self.bot.get_channel(123456789) #replace with your log channel ID
        if self.log_channel:
            handler = DiscordLogHandler(self.log_channel)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
            self.logger.info("Birthday Cog logging initialized.")
        else:
             self.logger.error("Log channel not found.")

    def create_tables(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS birthdays (
                                        user_id TEXT PRIMARY KEY,
                                        username TEXT NOT NULL,
                                        birthday TEXT NOT NULL
                                    )''')
        c.execute('''CREATE TABLE IF NOT EXISTS birthday_messages (
                                        message_id TEXT PRIMARY KEY,
                                        user_id TEXT NOT NULL,
                                        birthday TEXT NOT NULL
                                    )''')
        conn.commit()
        conn.close()

    @tasks.loop(seconds=10)
    async def check_birthdays(self):
        async with self.lock:
            await self.bot.wait_until_ready()
            now = datetime.now(pytz.timezone('US/Pacific'))
            self.logger.info(f"Checking birthdays at {now}")
            if now.hour >= 8:
                conn = sqlite3.connect(self.db_path)
                c = conn.cursor()
                today = now.strftime("%m-%d")
                c.execute("SELECT user_id FROM birthdays WHERE strftime('%m-%d', birthday) = ?", (today,))
                users = c.fetchall()
                channel = self.bot.get_channel(birthday_announcement_channel_id)
                if channel is None:
                    self.logger.error("Birthday channel not found.")
                    return

                for user in users:
                    user_id = user[0]
                    c.execute("SELECT message_id FROM birthday_messages WHERE user_id = ? AND strftime('%m-%d', birthday) = ?", (user_id, today))
                    message_exists = c.fetchone()
                    if not message_exists:
                        member = channel.guild.get_member(int(user_id))
                        if member:
                            embed = nextcord.Embed(title="🎂 **BIRTH!**", description=f"Happy Birthday {member.mention}!", color=0xFF5733)
                            embed.add_field(name='\u200B', value=f"Send {member.mention} some dabloons:", inline=False)
                            view = BirthdayButtonView(self.bot, birthday_user_id=member.id)
                            message = await channel.send(embed=embed, view=view)
                            role = channel.guild.get_role(birthday_role_id)
                            await member.add_roles(role)
                            self.store_birthday_message(message.id, user_id)
                            self.logger.info(f"Birthday message sent for user {user_id}")
                        else:
                            self.logger.error(f"Member not found for user ID {user_id}")
                conn.close()
            else:
                self.logger.info("Hour is before 8 AM, skipping birthday check.")

    @tasks.loop(seconds=10)
    async def cleanup_birthdays(self):
        async with self.lock:
            await self.bot.wait_until_ready()
            now = datetime.now(pytz.timezone('US/Pacific'))
            today = now.date()
            self.logger.info(f"Cleaning up birthdays at {today}")
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("SELECT user_id, message_id, birthday FROM birthday_messages")
            messages = c.fetchall()
            channel = self.bot.get_channel(birthday_announcement_channel_id)
            if channel is None:
                self.logger.error("Birthday channel not found.")
                conn.close()
                return

            for message in messages:
                user_id, message_id, birthday = message
                birthday_date = datetime.strptime(birthday, "%Y-%m-%d").date()
                if today > birthday_date:
                    try:
                        msg = await channel.fetch_message(message_id)
                        await msg.delete()
                        self.logger.info(f"Deleted message ID {message_id} for user ID {user_id}")
                    except nextcord.NotFound:
                        self.logger.error(f"Message ID {message_id} not found in channel.")

                    member = channel.guild.get_member(int(user_id))
                    if member:
                        role = channel.guild.get_role(birthday_role_id)
                        await member.remove_roles(role)
                        self.logger.info(f"Removed birthday role from user ID {user_id}")
                    else:
                        self.logger.error(f"Member not found for user ID {user_id}")
                    c.execute("DELETE FROM birthday_messages WHERE message_id = ?", (message_id,))
                    self.logger.info(f"Deleted entry from database for message ID {message_id}")

            conn.commit()
            conn.close()

    def store_birthday_message(self, message_id, user_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("INSERT INTO birthday_messages (message_id, user_id, birthday) VALUES (?, ?, ?)", (message_id, user_id, datetime.now().strftime("%Y-%m-%d")))
        conn.commit()
        conn.close()
    #rest of cog code.
async def setup(bot):
    cog = Birthday(bot)
    await cog.setup_logging()
    bot.add_cog(cog)
    print("BirthdayCog has been added to the bot.")

class DiscordLogHandler(logging.Handler):
    pass