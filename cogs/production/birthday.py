import nextcord
from nextcord.ext import commands, tasks
import sqlite3
from datetime import datetime, timedelta
import pytz

from server_configs.config import GUILD_ID
from server_configs.cogs_config import admin_user_ids, birthday_announcement_channel_id, birthday_reaction_channel_id, birthday_role_id, birthday_emoji_id

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

    @tasks.loop(seconds=30)
    async def check_birthdays(self):
        await self.bot.wait_until_ready()
        now_pacific = datetime.now(pytz.timezone('US/Pacific'))
        print(f"--------------------------------")
        print(f"[DEBUG] Current time (US/Pacific): {now_pacific}")
        # Consider adjusting the hour check if it's meant to be US/Pacific hour
        if now_pacific.hour >= 8: # Assuming this is 8 AM US/Pacific
            # print("[DEBUG] Hour is past 8 AM (US/Pacific), checking birthdays.")
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            # Date for which we are checking birthdays, in US/Pacific
            pacific_date_to_check_str = now_pacific.strftime("%Y-%m-%d")
            pacific_mm_dd_to_check = now_pacific.strftime("%m-%d")

            # print(f"[DEBUG] Today's date (US/Pacific YYYY-MM-DD): {pacific_date_to_check_str}")
            # print(f"[DEBUG] Today's date (US/Pacific MM-DD): {pacific_mm_dd_to_check}")

            # Find users whose birthday (MM-DD) matches the current US/Pacific MM-DD
            c.execute("SELECT user_id FROM birthdays WHERE strftime('%m-%d', birthday) = ?", (pacific_mm_dd_to_check,))
            users = c.fetchall()
            # print(f"[DEBUG] Users with birthdays today (US/Pacific MM-DD {pacific_mm_dd_to_check}): {users}")

            channel = self.bot.get_channel(birthday_announcement_channel_id)
            if channel is None:
                print("[ERROR] Birthday channel not found.")
                conn.close() # Close connection if returning early
                return

            for user_tuple in users: # Renamed 'user' to 'user_tuple' to avoid conflict
                user_id = user_tuple[0]
                # Check if a message was already sent for this user for this specific US/Pacific date
                c.execute("SELECT message_id FROM birthday_messages WHERE user_id = ? AND birthday = ?", 
                          (user_id, pacific_date_to_check_str))
                message_exists = c.fetchone()
                print(f"[DEBUG] Message exists for user {user_id} on {pacific_date_to_check_str}: {message_exists}")
                if not message_exists:
                    member = channel.guild.get_member(int(user_id))
                    print(f"[DEBUG] Member object for user {user_id}: {member}")
                    if member: # Check if member is not None
                        print(f"[DEBUG] Member mention: {member.mention}")
                        print(f"[DEBUG] Member found: {member}")
                        embed = nextcord.Embed(title="🎂 **BIRTH!**", description=f"Happy Birthday {member.mention}!", color=0xFF5733)
                        embed.add_field(name='\u200B', value=f"Send {member.mention} some dabloons:", inline=False)
                        print(f"[DEBUG] Embed created for user {user_id}")
                        view = BirthdayButtonView(self.bot, birthday_user_id=member.id)
                        message = await channel.send(embed=embed, view=view)
                        role = channel.guild.get_role(birthday_role_id)
                        if role: # Check if role is not None
                            await member.add_roles(role)
                        else:
                            print(f"[ERROR] Birthday role ID {birthday_role_id} not found.")
                        # Store the message ID and user ID, using the US/Pacific date for which the message was sent
                        self.store_birthday_message(message.id, user_id, pacific_date_to_check_str)
                        print(f"[DEBUG] Birthday message sent for user {user_id} for date {pacific_date_to_check_str}")
                    else:
                        print(f"[ERROR] Member not found for user ID {user_id}")
            conn.close()
        else:
            # Corrected the hour check message for clarity
            print(f"[DEBUG] Hour ({now_pacific.hour} US/Pacific) is before 8 AM, skipping birthday check.")
        print(f"--------------------------------")

    @tasks.loop(seconds=30)
    async def cleanup_birthdays(self):
        await self.bot.wait_until_ready()
        now_pacific = datetime.now(pytz.timezone('US/Pacific'))  # Use US/Pacific timezone
        today_pacific_date = now_pacific.date()  # Get only the date part (this is a date object)
        # print(f"--------------------------------")
        # print(f"[DEBUG] Current date (US/Pacific for cleanup): {today_pacific_date}")

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("SELECT user_id, message_id, birthday FROM birthday_messages")
        messages = c.fetchall()
        # print(f"[DEBUG] Messages to check for cleanup: {messages}")

        channel = self.bot.get_channel(birthday_announcement_channel_id)
        if channel is None:
            print("[ERROR] Birthday channel not found for cleanup.")
            conn.close()
            return

        for message_tuple in messages: # Renamed 'message' to 'message_tuple'
            user_id, message_id, birthday_str = message_tuple # 'birthday_str' is now a YYYY-MM-DD string for US/Pacific
            
            # Parse the stored US/Pacific birthday date string
            birthday_date_obj = datetime.strptime(birthday_str, "%Y-%m-%d").date()

            print(f"[DEBUG] Checking message ID {message_id} for user ID {user_id}")
            print(f"[DEBUG] Stored Message Date (US/Pacific): {birthday_date_obj}, Current Date (US/Pacific): {today_pacific_date}")

            # Check if the current US/Pacific date is past the US/Pacific date of the message
            if today_pacific_date > birthday_date_obj:
                try:
                    msg = await channel.fetch_message(message_id)
                    await msg.delete()
                    print(f"[DEBUG] Deleted message ID {message_id} for user ID {user_id}")
                except nextcord.NotFound:
                    print(f"[ERROR] Message ID {message_id} not found in channel for deletion.")

        conn.commit()
        conn.close()
        print(f"--------------------------------")
        

    def store_birthday_message(self, message_id, user_id, pacific_date_str): # Changed last parameter
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # Store the US/Pacific date string (YYYY-MM-DD) for which the message was sent
        c.execute("INSERT INTO birthday_messages (message_id, user_id, birthday) VALUES (?, ?, ?)", 
                  (message_id, user_id, pacific_date_str))
        conn.commit()
        conn.close()

    def remove_birthday_messages(self, birthday_mm_dd): # Parameter is MM-DD
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # This will remove messages if their stored US/Pacific YYYY-MM-DD matches the given MM-DD
        c.execute("DELETE FROM birthday_messages WHERE strftime('%m-%d', birthday) = ?", (birthday_mm_dd,))
        conn.commit()
        conn.close()

    @nextcord.slash_command(name="bday", description="Shows upcoming birthdays", guild_ids=[GUILD_ID])
    async def bday(self, interaction: nextcord.Interaction, username: nextcord.Member = nextcord.SlashOption(required=False, description='@Username.')):

        now = datetime.now()
        next_month = (now.month % 12) + 1
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        if username:
            # Directly use the id attribute of the Member object
            user_id = username.id
            member = interaction.guild.get_member(user_id) # This line is somewhat redundant if username is already a Member object from the current guild
            if member is None: # It's good practice to ensure the member object is valid
                member = username # Use the passed username object

            if member:
                c.execute("SELECT birthday FROM birthdays WHERE user_id = ?", (str(user_id),)) # Ensure user_id is string for DB
                result = c.fetchone()
                conn.close()

                if result:
                    display_name = member.mention
                    formatted_birthday = datetime.strptime(result[0], "%Y-%m-%d").strftime("%m/%d")
                    await interaction.response.send_message(f"{display_name}'s birthday is on {formatted_birthday}.", ephemeral=True)
                else:
                    if interaction.user.id in admin_user_ids:
                        modal = AddBirthdayModal(self.db_path, member.display_name, str(user_id)) # Ensure user_id is string for modal
                        await interaction.response.send_modal(modal)
                    else:
                        await interaction.response.send_message(f"I don't know {member.display_name}'s birthday.", ephemeral=True)
            else:
                # This case should ideally not be reached if 'username' is a valid Member object from the interaction
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
    def __init__(self, bot, birthday_user_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.birthday_user_id = birthday_user_id

    @nextcord.ui.button(label="🪙 100", style=nextcord.ButtonStyle.primary)
    async def send_emoji(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.handle_reaction(interaction, "emoji", 100)

    @nextcord.ui.button(label="🪙 200", style=nextcord.ButtonStyle.primary)
    async def send_sticker(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.handle_reaction(interaction, "sticker", 200)

    @nextcord.ui.button(label="🪙 500", style=nextcord.ButtonStyle.primary)
    async def send_embed(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.handle_reaction(interaction, "embed", 500)

    async def handle_reaction(self, interaction: nextcord.Interaction, reaction_type: str, cost: int):
        user_id = interaction.user.id
        economy_cog = self.bot.get_cog('Economy')
        if not economy_cog:
            await interaction.response.send_message("Economy system is not available.", ephemeral=True)
            return

        # Check user's balance
        balance = await economy_cog.get_user_balance(user_id)
        if balance < cost:
            await interaction.response.send_message(f"You do not have enough currency. You need {cost} currency.", ephemeral=True)
            return

        # Deduct the currency
        await economy_cog.deduct_user_balance(user_id, cost)
        await economy_cog.update_balance(self.birthday_user_id, cost)


        reaction_channel = self.bot.get_channel(birthday_reaction_channel_id)
        if reaction_channel:
            emoji = self.bot.get_emoji(birthday_emoji_id)
            print(f"[DEBUG] Emoji: {emoji}")
            if reaction_type == "emoji":
                embed = nextcord.Embed(description=f"{emoji}{emoji}{emoji}", color=0x574BCD)
                embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
                embed.set_footer(text=f"{interaction.user.display_name} gifted {cost} 🪙")
                await reaction_channel.send(embed=embed)
            elif reaction_type == "sticker":
                embed = nextcord.Embed(color=0x2999AD)
                embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
                embed.set_thumbnail(url="https://media.discordapp.net/attachments/1350599554818375811/1350794770842390528/tumblr_ncy1ybsF0f1qbye1fo2_1280-299919097.jpg?ex=67daac29&is=67d95aa9&hm=96b6c0e9927970df5fb9a64a256f58d8235c7c1ff5ca9f8222e602071e53d3b5&=&format=webp&width=836&height=836")
                embed.set_footer(text=f"({interaction.user.display_name} gifted {cost}🪙)")
                await reaction_channel.send(embed=embed)
            elif reaction_type == "embed":
                embed = nextcord.Embed(color=0x41E975)
                embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
                embed.set_image(url="https://media.discordapp.net/attachments/1350599554818375811/1350794770842390528/tumblr_ncy1ybsF0f1qbye1fo2_1280-299919097.jpg?ex=67daac29&is=67d95aa9&hm=96b6c0e9927970df5fb9a64a256f58d8235c7c1ff5ca9f8222e602071e53d3b5&=&format=webp&width=836&height=836")  # Replace with actual image URL
                embed.set_footer(text=f"{interaction.user.display_name} gifted {cost} 🪙")
                await reaction_channel.send(embed=embed)
            await interaction.response.send_message(f"You gifted {cost} 🪙!", ephemeral=True)
        else:
            await interaction.response.send_message("Reaction channel not found.", ephemeral=True)

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