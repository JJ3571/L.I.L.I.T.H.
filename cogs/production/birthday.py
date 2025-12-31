import nextcord
from nextcord.ext import commands, tasks
import aiosqlite
from datetime import datetime, timedelta
import pytz

from server_configs.config import GUILD_ID
from server_configs.cogs_config import admin_user_ids, birthday_announcement_channel_id, birthday_reaction_channel_id, birthday_role_id, birthday_emoji_id
from server_configs.database_config import DATABASE_PATHS

class Birthday(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = DATABASE_PATHS["birthday"]
        self.bot.loop.create_task(self.create_tables())
        self.check_birthdays.start()
        self.cleanup_birthdays.start()

    async def create_tables(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS birthdays (
                            user_id TEXT PRIMARY KEY,
                            username TEXT NOT NULL,
                            birthday TEXT NOT NULL
                        )''')
            await db.execute('''CREATE TABLE IF NOT EXISTS birthday_messages (
                            message_id TEXT PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            birthday TEXT NOT NULL
                        )''')
            await db.commit()

    @tasks.loop(seconds=30)
    async def check_birthdays(self):
        await self.bot.wait_until_ready()
        now_pacific = datetime.now(pytz.timezone('US/Pacific'))
        print(f"--------------------------------")
        print(f"[DEBUG] Current time (US/Pacific): {now_pacific}")
        if now_pacific.hour >= 8: #  8 AM PST
            async with aiosqlite.connect(self.db_path) as db:
                # Date for which we are checking birthdays, in US/Pacific
                pacific_date_to_check_str = now_pacific.strftime("%Y-%m-%d")
                pacific_mm_dd_to_check = now_pacific.strftime("%m-%d")

                # Find users whose birthday (MM-DD) matches the current US/Pacific MM-DD
                async with db.execute("SELECT user_id FROM birthdays WHERE strftime('%m-%d', birthday) = ?", (pacific_mm_dd_to_check,)) as cursor:
                    users = await cursor.fetchall()

                channel = self.bot.get_channel(birthday_announcement_channel_id)
                if channel is None:
                    print("[ERROR] Birthday channel not found.")
                    return

                for user_tuple in users:
                    user_id = user_tuple[0]
                    # Check if a message was already sent for this user for this specific US/Pacific date
                    async with db.execute("SELECT message_id FROM birthday_messages WHERE user_id = ? AND birthday = ?", 
                              (user_id, pacific_date_to_check_str)) as cursor:
                        message_exists = await cursor.fetchone()
                    
                    print(f"[DEBUG] Message exists for user {user_id} on {pacific_date_to_check_str}: {message_exists}")
                    if not message_exists:
                        member = channel.guild.get_member(int(user_id))
                        print(f"[DEBUG] Member object for user {user_id}: {member}")
                        if member:
                            print(f"[DEBUG] Member mention: {member.mention}")
                            embed = nextcord.Embed(title="🎂 **BIRTH!**", description=f"Happy Birthday {member.mention}!", color=0xFF5733)
                            embed.add_field(name='\u200B', value=f"Send {member.mention} some dabloons:", inline=False)
                            print(f"[DEBUG] Embed created for user {user_id}")
                            view = BirthdayButtonView(self.bot, birthday_user_id=member.id)
                            message = await channel.send(embed=embed, view=view)
                            role = channel.guild.get_role(birthday_role_id)
                            if role:
                                await member.add_roles(role)
                            else:
                                print(f"[ERROR] Birthday role ID {birthday_role_id} not found.")
                            
                            # Grant 20-hour executive pardon for birthday
                            await self.grant_birthday_executive_pardon(member.id)
                            print(f"[DEBUG] Granted 20-hour executive pardon for birthday user {user_id}")
                            
                            await self.store_birthday_message(message.id, user_id, pacific_date_to_check_str)
                            print(f"[DEBUG] Birthday message sent for user {user_id} for date {pacific_date_to_check_str}")
                        else:
                            print(f"[ERROR] Member not found for user ID {user_id}")
        else:
            print(f"[DEBUG] Hour ({now_pacific.hour} US/Pacific) is before 8 AM, skipping birthday check.")
        print(f"--------------------------------")

    @tasks.loop(seconds=30)
    async def cleanup_birthdays(self):
        await self.bot.wait_until_ready()
        now_pacific = datetime.now(pytz.timezone('US/Pacific'))
        today_pacific_date = now_pacific.date()
        current_pacific_mm_dd = now_pacific.strftime("%m-%d")

        async with aiosqlite.connect(self.db_path) as db:
            guild = self.bot.get_guild(GUILD_ID)
            if guild is None:
                print("[ERROR] Guild not found for cleanup.")
                return

            channel = guild.get_channel(birthday_announcement_channel_id)
            birthday_role = guild.get_role(birthday_role_id)

            # Part 1: Message-driven cleanup (and associated role removal)
            if channel:
                async with db.execute("SELECT user_id, message_id, birthday FROM birthday_messages") as cursor:
                    messages_to_cleanup = await cursor.fetchall()

                for message_tuple in messages_to_cleanup:
                    user_id_str, message_id, birthday_str = message_tuple
                    
                    # Skip if birthday_str is empty or None
                    if not birthday_str or birthday_str.strip() == '':
                        print(f"[DEBUG] Skipping cleanup for user {user_id_str} - empty birthday string")
                        continue
                    
                    try:
                        birthday_date_obj = datetime.strptime(birthday_str, "%Y-%m-%d").date()
                    except ValueError as e:
                        print(f"[ERROR] Invalid date format for user {user_id_str}: '{birthday_str}' - {e}")
                        continue

                    if today_pacific_date > birthday_date_obj:
                        try:
                            msg = await channel.fetch_message(message_id)
                            await msg.delete()
                            print(f"[DEBUG] Deleted message ID {message_id} for user ID {user_id_str}")
                        except nextcord.NotFound:
                            print(f"[DEBUG] Message ID {message_id} not found in channel for deletion (already deleted or error).")
                        except nextcord.Forbidden:
                            print(f"[ERROR] Bot lacks permissions to delete message ID {message_id}.")
                        except Exception as e:
                            print(f"[ERROR] Unexpected error deleting message ID {message_id}: {e}")
                        finally:
                            # Always try to remove role and DB entry if message was due for cleanup
                            if birthday_role:
                                member = guild.get_member(int(user_id_str))
                                if member:
                                    if birthday_role in member.roles:
                                        try:
                                            await member.remove_roles(birthday_role)
                                            print(f"[DEBUG] Removed birthday role from user ID {user_id_str} (associated with old message {message_id})")
                                        except nextcord.Forbidden:
                                            print(f"[ERROR] Bot lacks permissions to remove role from user ID {user_id_str}.")
                                        except Exception as e:
                                            print(f"[ERROR] Error removing role from user ID {user_id_str}: {e}")
                            
                            await db.execute("DELETE FROM birthday_messages WHERE message_id = ?", (message_id,))
            elif not channel:
                print("[ERROR] Birthday channel not found for message cleanup part.")

            # Part 2: General Role Audit
            if birthday_role:
                members_with_role = [m for m in guild.members if birthday_role in m.roles]

                for member in members_with_role:
                    async with db.execute("SELECT strftime('%m-%d', birthday) FROM birthdays WHERE user_id = ?", (str(member.id),)) as cursor:
                        birthday_record = await cursor.fetchone()
                    
                    should_have_role = False
                    if birthday_record:
                        member_birthday_mm_dd = birthday_record[0]
                        if member_birthday_mm_dd == current_pacific_mm_dd:
                            should_have_role = True

                    if not should_have_role:
                        try:
                            await member.remove_roles(birthday_role)
                            print(f"[AUDIT] Removed birthday role from {member.display_name} (ID: {member.id}). Reason: Not their birthday ({current_pacific_mm_dd}) or no DB record.")
                        except nextcord.Forbidden:
                            print(f"[ERROR][AUDIT] Bot lacks permissions to remove role from {member.display_name} (ID: {member.id}).")
                        except Exception as e:
                            print(f"[ERROR][AUDIT] Error removing role from {member.display_name} (ID: {member.id}): {e}")
            elif not birthday_role:
                print("[ERROR] Birthday role not found, skipping general role audit.")

            await db.commit()

    async def store_birthday_message(self, message_id, user_id, pacific_date_str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("INSERT INTO birthday_messages (message_id, user_id, birthday) VALUES (?, ?, ?)", 
                      (message_id, user_id, pacific_date_str))
            await db.commit()

    async def remove_birthday_messages(self, birthday_mm_dd):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM birthday_messages WHERE strftime('%m-%d', birthday) = ?", (birthday_mm_dd,))
            await db.commit()
    
    async def grant_birthday_executive_pardon(self, user_id):
        """Grant a 20-hour executive pardon for a user's birthday"""
        try:
            # Try to get the waterboard cog to grant the pardon
            waterboard_cog = self.bot.get_cog('WaterboardCog')
            if waterboard_cog and hasattr(waterboard_cog, 'executive_pardon'):
                await waterboard_cog.executive_pardon(user_id, 20)  # 20 hours
                print(f"[DEBUG] Successfully granted 20-hour executive pardon to user {user_id} via WaterboardCog")
            else:
                print(f"[ERROR] WaterboardCog or executive_pardon method not found - cannot grant birthday pardon to user {user_id}")
        except Exception as e:
            print(f"[ERROR] Failed to grant birthday executive pardon to user {user_id}: {e}")

    @nextcord.slash_command(name="bday", description="Shows upcoming birthdays, or can be used with an @ to see specific birthdays.", guild_ids=[GUILD_ID])
    async def bday(self, interaction: nextcord.Interaction, username: nextcord.Member = nextcord.SlashOption(required=False, description='@Username.')):

        now = datetime.now()
        next_month = (now.month % 12) + 1

        if username:
            user_id = username.id
            member = interaction.guild.get_member(user_id)
            if member is None:
                member = username

            if member:
                async with aiosqlite.connect(self.db_path) as db:
                    async with db.execute("SELECT birthday FROM birthdays WHERE user_id = ?", (str(user_id),)) as cursor:
                        result = await cursor.fetchone()

                if result:
                    # Check if user can update (is admin or is themselves)
                    can_update = interaction.user.id in admin_user_ids or interaction.user.id == user_id
                    
                    display_name = member.mention
                    try:
                        formatted_birthday = datetime.strptime(result[0], "%Y-%m-%d").strftime("%m/%d")
                    except ValueError:
                        formatted_birthday = "Invalid Date"
                    
                    if can_update:
                        view = UpdateBirthdayView(self.db_path, member.display_name, str(user_id), interaction.user.id == user_id)
                        await interaction.response.send_message(f"{display_name}'s birthday is on {formatted_birthday}.", view=view, ephemeral=True)
                    else:
                        await interaction.response.send_message(f"{display_name}'s birthday is on {formatted_birthday}.", ephemeral=True)
                else:
                    if interaction.user.id in admin_user_ids or interaction.user.id == user_id:
                        modal = AddBirthdayModal(self.db_path, member.display_name, str(user_id))
                        await interaction.response.send_modal(modal)
                    else:
                        await interaction.response.send_message(f"I don't know {member.display_name}'s birthday.", ephemeral=True)
            else:
                await interaction.response.send_message(f"User {username} not found.", ephemeral=True)
        else:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute("SELECT user_id, username, birthday FROM birthdays WHERE strftime('%m', birthday) = ?", (f"{now.month:02}",)) as cursor:
                    this_month_birthdays = await cursor.fetchall()
                async with db.execute("SELECT user_id, username, birthday FROM birthdays WHERE strftime('%m', birthday) = ?", (f"{next_month:02}",)) as cursor:
                    next_month_birthdays = await cursor.fetchall()

            embed = nextcord.Embed(title="Upcoming Birthdays", color=0x00ff00)

            if this_month_birthdays:
                this_month_list = []
                for user_id, username, birthday in this_month_birthdays:
                    try:
                        formatted_date = datetime.strptime(birthday, '%Y-%m-%d').strftime('%m/%d')
                    except ValueError:
                        formatted_date = "Invalid Date"
                    member_mention = interaction.guild.get_member(int(user_id)).mention if interaction.guild.get_member(int(user_id)) else f'<@{user_id}>'
                    this_month_list.append(f"{member_mention} : {formatted_date}")
                this_month_value = "\n".join(this_month_list)
                embed.add_field(name="This Month", value=this_month_value, inline=False)

            if next_month_birthdays:
                next_month_list = []
                for user_id, username, birthday in next_month_birthdays:
                    try:
                        formatted_date = datetime.strptime(birthday, '%Y-%m-%d').strftime('%m/%d')
                    except ValueError:
                        formatted_date = "Invalid Date"
                    member_mention = interaction.guild.get_member(int(user_id)).mention if interaction.guild.get_member(int(user_id)) else f'<@{user_id}>'
                    next_month_list.append(f"{member_mention} : {formatted_date}")
                next_month_value = "\n".join(next_month_list)
                embed.add_field(name="Next Month", value=next_month_value, inline=False)

            if this_month_birthdays or next_month_birthdays:
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message("No upcoming birthdays found.", ephemeral=True)

class UpdateBirthdayView(nextcord.ui.View):
    def __init__(self, db_path, username, user_id, is_self):
        super().__init__(timeout=300)  # 5 minute timeout
        self.db_path = db_path
        self.username = username
        self.user_id = user_id
        self.is_self = is_self

    @nextcord.ui.button(label="Update Birthday", style=nextcord.ButtonStyle.secondary, emoji="✏️")
    async def update_birthday(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        modal = UpdateBirthdayModal(self.db_path, self.username, self.user_id, self.is_self)
        await interaction.response.send_modal(modal)

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
                embed.set_image(url="https://media.discordapp.net/attachments/1350599554818375811/1350794770842390528/tumblr_ncy1ybsF0f1qbye1fo2_1280-299919097.jpg?ex=67daac29&is=67d95aa9&hm=96b6c0e9927970df5fb9a64a256f58d8235c7c1ff5ca9f8222e602071e53d3b5&=&format=webp&width=836&height=836")
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

        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute("INSERT INTO birthdays (user_id, username, birthday) VALUES (?, ?, ?)", 
                               (self.user_id, self.username, formatted_birthday))
                await db.commit()
                await interaction.response.send_message(f"Added {self.username}'s birthday on {birthday}.", ephemeral=True)
            except aiosqlite.IntegrityError:
                await interaction.response.send_message(f"A birthday for {self.username} already exists.", ephemeral=True)

class UpdateBirthdayModal(nextcord.ui.Modal):
    def __init__(self, db_path, username, user_id, is_self):
        super().__init__("Update Birthday", timeout=5 * 60)
        self.db_path = db_path
        self.username = username
        self.user_id = user_id
        self.is_self = is_self

        self.birthday = nextcord.ui.TextInput(
            label="New Birthday (MM/DD)",
            custom_id="birthday_update_input",
            style=nextcord.TextInputStyle.short,
            placeholder="Enter new birthday in MM/DD format"
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

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE birthdays SET birthday = ?, username = ? WHERE user_id = ?", 
                           (formatted_birthday, self.username, self.user_id))
            await db.commit()
            
            if self.is_self:
                await interaction.response.send_message(f"Your birthday has been updated to {birthday}.", ephemeral=True)
            else:
                await interaction.response.send_message(f"Updated {self.username}'s birthday to {birthday}.", ephemeral=True)

def setup(bot):
    bot.add_cog(Birthday(bot))
    print("BirthdayCog has been added to the bot.")