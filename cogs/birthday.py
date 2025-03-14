import nextcord
from nextcord.ext import commands, tasks
import sqlite3
from datetime import datetime, timedelta
import pytz

from server_configs.cogs_config import admin_user_ids, birthday_channel_id, birthday_role_id

class Birthday(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "birthday.db"
        self.create_tables()
        self.check_birthdays.start()
        self.cleanup_birthdays.start()

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

    @tasks.loop(minutes=1)
    async def check_birthdays(self):
        now = datetime.now(pytz.timezone('US/Eastern'))
        if now.hour >= 8:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            today = now.strftime("%m-%d")
            c.execute("SELECT user_id FROM birthdays WHERE strftime('%m-%d', birthday) = ?", (today,))
            users = c.fetchall()

            for user in users:
                user_id = user[0]
                c.execute("SELECT message_id FROM birthday_messages WHERE user_id = ? AND strftime('%m-%d', birthday) = ?", (user_id, today))
                message_exists = c.fetchone()
                if not message_exists:
                    member = channel.guild.get_member(int(user_id))
                    if member:
                        embed = nextcord.Embed(title="BIRTH!", description=f"Happy Birthday {member.mention}!", color=0x00ff00)
                        view = BirthdayButtonView()
                        channel = self.bot.get_channel(birthday_channel_id)
                        message = await channel.send(embed=embed, view=view)
                        role = channel.guild.get_role(birthday_role_id)
                        await member.add_roles(role)
                        # Store the message ID and user ID for cleanup
                        self.store_birthday_message(message.id, user_id)
            conn.close()

    # Debugging function to check birthdays at a specific time
    # @tasks.loop(minutes=1)
    # async def check_birthdays_debug(self):
    #     now = datetime.now(pytz.timezone('US/Eastern'))
    #     # Specific hr:m for debug testing!
    #     debug_hour = 2
    #     debug_minute = 50
    #     if now.hour >= debug_hour and now.minute >= debug_minute:
    #         conn = sqlite3.connect(self.db_path)
    #         c = conn.cursor()
    #         today = now.strftime("%m-%d")
    #         c.execute("SELECT user_id FROM birthdays WHERE strftime('%m-%d', birthday) = ?", (today,))
    #         users = c.fetchall()
    #         conn.close()

    #         if users:
    #             channel = self.bot.get_channel(birthday_channel_id)
    #             for user in users:
    #                 member = channel.guild.get_member(int(user[0]))
    #                 if member:
    #                     embed = nextcord.Embed(title="BIRTH!", description=f"Happy Birthday {member.mention}!", color=0x00ff00)
    #                     message = await channel.send(embed=embed)
    #                     role = channel.guild.get_role(birthday_role_id)
    #                     await member.add_roles(role)
    #                     # Store the message ID and user ID for cleanup
    #                     self.store_birthday_message(message.id, user[0])


    @tasks.loop(minutes=15)
    async def cleanup_birthdays(self):
        now = datetime.now(pytz.timezone('US/Pacific'))
        if now.hour == 0 and now.minute < 15:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            yesterday = (now - timedelta(days=1)).strftime("%m-%d")
            c.execute("SELECT user_id, message_id FROM birthday_messages WHERE strftime('%m-%d', birthday) = ?", (yesterday,))
            messages = c.fetchall()
            conn.close()

            if messages:
                channel = self.bot.get_channel(birthday_channel_id)
                for user_id, message_id in messages:
                    member = channel.guild.get_member(int(user_id))
                    if member:
                        role = channel.guild.get_role(birthday_role_id)
                        await member.remove_roles(role)
                    message = await channel.fetch_message(int(message_id))
                    await message.delete()
                # Remove the entries from the database
                self.remove_birthday_messages(yesterday)

    def store_birthday_message(self, message_id, user_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("INSERT INTO birthday_messages (message_id, user_id, birthday) VALUES (?, ?, ?)", (message_id, user_id, datetime.now().strftime("%Y-%m-%d")))
        conn.commit()
        conn.close()

    def remove_birthday_messages(self, birthday):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("DELETE FROM birthday_messages WHERE strftime('%m-%d', birthday) = ?", (birthday,))
        conn.commit()
        conn.close()

    @nextcord.slash_command(name="bday", description="Show birthdays or add a birthday")
    async def bday(self, interaction: nextcord.Interaction, username: str = None):
        now = datetime.now()
        next_month = (now.month % 12) + 1
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        if username:
            # Strip the @ symbol and extract the user ID
            user_id = int(username.strip('<@!>'))
            member = interaction.guild.get_member(user_id)
            if member:
                c.execute("SELECT birthday FROM birthdays WHERE user_id = ?", (user_id,))
                result = c.fetchone()
                conn.close()

                if result:
                    display_name = member.mention
                    formatted_birthday = datetime.strptime(result[0], "%Y-%m-%d").strftime("%m/%d")
                    await interaction.response.send_message(f"{display_name}'s birthday is on {formatted_birthday}.", ephemeral=True)
                else:
                    if interaction.user.id in admin_user_ids:
                        modal = AddBirthdayModal(self.db_path, member.display_name, user_id)
                        await interaction.response.send_modal(modal)
                    else:
                        await interaction.response.send_message(f"I don't know {username}'s birthday.", ephemeral=True)
            else:
                await interaction.response.send_message(f"User {username} not found.", ephemeral=True)
        else:
            c.execute("SELECT user_id, username, birthday FROM birthdays WHERE strftime('%m', birthday) = ?", (f"{now.month:02}",))
            this_month_birthdays = c.fetchall()
            c.execute("SELECT user_id, username, birthday FROM birthdays WHERE strftime('%m', birthday) = ?", (f"{next_month:02}",))
            next_month_birthdays = c.fetchall()
            conn.close()

            embed = nextcord.Embed(title="Upcoming Birthdays", color=0x00ff00)

            if this_month_birthdays:
                this_month_value = "\n".join(
                    f"{interaction.guild.get_member(int(user_id)).mention if interaction.guild.get_member(int(user_id)) else f'<@{user_id}>'} : {datetime.strptime(birthday, '%Y-%m-%d').strftime('%m/%d')}"
                    for user_id, username, birthday in this_month_birthdays
                )
                embed.add_field(name="This Month", value=this_month_value, inline=False)

            if next_month_birthdays:
                next_month_value = "\n".join(
                    f"{interaction.guild.get_member(int(user_id)).mention if interaction.guild.get_member(int(user_id)) else f'<@{user_id}>'} : {datetime.strptime(birthday, '%Y-%m-%d').strftime('%m/%d')}"
                    for user_id, username, birthday in next_month_birthdays
                )
                embed.add_field(name="Next Month", value=next_month_value, inline=False)

            if this_month_birthdays or next_month_birthdays:
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message("No upcoming birthdays found.", ephemeral=True)

class BirthdayButtonView(nextcord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @nextcord.ui.button(label="Send Emoji", style=nextcord.ButtonStyle.primary)
    async def send_emoji(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.send_message("🎉", ephemeral=False)

class AddBirthdayModal(nextcord.ui.Modal):
    def __init__(self, db_path, username, user_id):
        super().__init__("Add Birthday", timeout=5 * 60)
        self.db_path = db_path
        self.username = username
        self.user_id = user_id

        self.birthday = nextcord.ui.TextInput(
            label="Birthday (MM/DD)",
            custom_id="birthday_input",
            style=nextcord.TextInputStyle.short
        )

        self.add_item(self.birthday)

    async def callback(self, interaction: nextcord.Interaction):
        birthday = self.birthday.value

        # Validate the birthday format
        try:
            parsed_birthday = datetime.strptime(birthday, "%m/%d")
            formatted_birthday = parsed_birthday.strftime("%Y-%m-%d")
        except ValueError:
            await interaction.response.send_message("Invalid date format. Please use MM/DD.", ephemeral=True)
            return

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO birthdays (user_id, username, birthday) VALUES (?, ?, ?)", (self.user_id, self.username, formatted_birthday))
            conn.commit()
            await interaction.response.send_message(f"Added {self.username}'s birthday on {birthday}.", ephemeral=True)
        except sqlite3.IntegrityError:
            await interaction.response.send_message(f"A birthday for {self.username} already exists.", ephemeral=True)
        finally:
            conn.close()

def setup(bot):
    bot.add_cog(Birthday(bot))
    print("BirthdayCog has been added to the bot.")