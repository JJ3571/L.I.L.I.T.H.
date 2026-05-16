import calendar
import nextcord
from nextcord.ext import commands, tasks
import asyncpg
from datetime import datetime, timedelta
import pytz

from main_bot.boot_log import boot_print
from main_bot.cog_log_mixin import CogLogMixin
from main_bot.server_configs.config import GUILD_ID
from main_bot.server_configs.config import admin_user_ids, birthday_announcement_channel_id, birthday_reaction_channel_id, birthday_role_id, birthday_emoji_id

_BD = "birthday"


def _dbg_print(cog, message: str) -> None:
    """Honors ``bot.full_debug_in_terminal`` (set in ``main_bot.main`` from ``FULL_DEBUG_IN_TERMINAL``)."""
    if getattr(cog.bot, "full_debug_in_terminal", False):
        cog.cog_print(message)


class Birthday(commands.Cog, CogLogMixin):
    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.create_tables())
        self.check_birthdays.start()
        self.cleanup_birthdays.start()

    async def create_tables(self):
        return

    @tasks.loop(seconds=30)
    async def check_birthdays(self):
        await self.bot.wait_until_ready()
        now_pacific = datetime.now(pytz.timezone('US/Pacific'))
        _dbg_print(self, "--------------------------------")
        _dbg_print(self, f"[DEBUG] Current time (US/Pacific): {now_pacific}")
        if now_pacific.hour >= 8: #  8 AM PST
            async with self.bot.pg_pool.acquire() as db:
                pacific_date_to_check_str = now_pacific.strftime("%Y-%m-%d")
                pacific_mm_dd_to_check = now_pacific.strftime("%m-%d")

                users = await db.fetch(
                    f'''
                    SELECT user_id FROM "{_BD}".birthdays
                    WHERE to_char(birthday::date, 'MM-DD') = $1
                    ''',
                    pacific_mm_dd_to_check,
                )

                channel = self.bot.get_channel(birthday_announcement_channel_id)
                if channel is None:
                    self.cog_print("[ERROR] Birthday channel not found.")
                    return

                for row in users:
                    user_id = row["user_id"]
                    message_exists = await db.fetchrow(
                        f'''
                        SELECT message_id FROM "{_BD}".birthday_messages
                        WHERE user_id = $1 AND birthday = $2
                        ''',
                        user_id,
                        pacific_date_to_check_str,
                    )
                    
                    _dbg_print(self, f"[DEBUG] Message exists for user {user_id} on {pacific_date_to_check_str}: {message_exists}")
                    if not message_exists:
                        member = channel.guild.get_member(int(user_id))
                        _dbg_print(self, f"[DEBUG] Member object for user {user_id}: {member}")
                        if member:
                            _dbg_print(self, f"[DEBUG] Member mention: {member.mention}")
                            embed = nextcord.Embed(title="🎂 **BIRTH!**", description=f"Happy Birthday {member.mention}!", color=0xFF5733)
                            embed.add_field(name='\u200B', value=f"Send {member.mention} some dabloons:", inline=False)
                            _dbg_print(self, f"[DEBUG] Embed created for user {user_id}")
                            view = BirthdayButtonView(self.bot, self, birthday_user_id=member.id)
                            message = await channel.send(embed=embed, view=view)
                            role = channel.guild.get_role(birthday_role_id)
                            if role:
                                await member.add_roles(role)
                            else:
                                self.cog_print(f"[ERROR] Birthday role ID {birthday_role_id} not found.")
                            
                            # Grant 20-hour executive pardon for birthday
                            await self.grant_birthday_executive_pardon(member.id)
                            _dbg_print(self, f"[DEBUG] Granted 20-hour executive pardon for birthday user {user_id}")
                            
                            await self.store_birthday_message(message.id, user_id, pacific_date_to_check_str)
                            _dbg_print(self, f"[DEBUG] Birthday message sent for user {user_id} for date {pacific_date_to_check_str}")
                        else:
                            self.cog_print(f"[ERROR] Member not found for user ID {user_id}")
        else:
            _dbg_print(self, f"[DEBUG] Hour ({now_pacific.hour} US/Pacific) is before 8 AM, skipping birthday check.")
        _dbg_print(self, "--------------------------------")

    @tasks.loop(seconds=30)
    async def cleanup_birthdays(self):
        await self.bot.wait_until_ready()
        now_pacific = datetime.now(pytz.timezone('US/Pacific'))
        today_pacific_date = now_pacific.date()
        current_pacific_mm_dd = now_pacific.strftime("%m-%d")

        async with self.bot.pg_pool.acquire() as db:
            guild = self.bot.get_guild(GUILD_ID)
            if guild is None:
                self.cog_print("[ERROR] Guild not found for cleanup.")
                return

            channel = guild.get_channel(birthday_announcement_channel_id)
            birthday_role = guild.get_role(birthday_role_id)

            # Part 1: Message-driven cleanup (and associated role removal)
            if channel:
                messages_to_cleanup = await db.fetch(
                    f'SELECT user_id, message_id, birthday FROM "{_BD}".birthday_messages'
                )

                for message_tuple in messages_to_cleanup:
                    user_id_str = message_tuple["user_id"]
                    message_id = message_tuple["message_id"]
                    birthday_str = message_tuple["birthday"]
                    
                    # Skip if birthday_str is empty or None
                    if not birthday_str or birthday_str.strip() == '':
                        _dbg_print(self, f"[DEBUG] Skipping cleanup for user {user_id_str} - empty birthday string")
                        continue
                    
                    try:
                        birthday_date_obj = datetime.strptime(birthday_str, "%Y-%m-%d").date()
                    except ValueError as e:
                        self.cog_print(f"[ERROR] Invalid date format for user {user_id_str}: '{birthday_str}' - {e}")
                        continue

                    if today_pacific_date > birthday_date_obj:
                        try:
                            msg = await channel.fetch_message(int(message_id))
                            await msg.delete()
                            _dbg_print(self, f"[DEBUG] Deleted message ID {message_id} for user ID {user_id_str}")
                        except nextcord.NotFound:
                            _dbg_print(self, f"[DEBUG] Message ID {message_id} not found in channel for deletion (already deleted or error).")
                        except nextcord.Forbidden:
                            self.cog_print(f"[ERROR] Bot lacks permissions to delete message ID {message_id}.")
                        except Exception as e:
                            self.cog_print(f"[ERROR] Unexpected error deleting message ID {message_id}: {e}")
                        finally:
                            # Always try to remove role and DB entry if message was due for cleanup
                            if birthday_role:
                                member = guild.get_member(int(user_id_str))
                                if member:
                                    if birthday_role in member.roles:
                                        try:
                                            await member.remove_roles(birthday_role)
                                            _dbg_print(self, f"[DEBUG] Removed birthday role from user ID {user_id_str} (associated with old message {message_id})")
                                        except nextcord.Forbidden:
                                            self.cog_print(f"[ERROR] Bot lacks permissions to remove role from user ID {user_id_str}.")
                                        except Exception as e:
                                            self.cog_print(f"[ERROR] Error removing role from user ID {user_id_str}: {e}")
                            
                            await db.execute(
                                f'DELETE FROM "{_BD}".birthday_messages WHERE message_id = $1',
                                str(message_id),
                            )
            elif not channel:
                self.cog_print("[ERROR] Birthday channel not found for message cleanup part.")

            # Part 2: General Role Audit
            if birthday_role:
                members_with_role = [m for m in guild.members if birthday_role in m.roles]

                for member in members_with_role:
                    birthday_record = await db.fetchrow(
                        f'''
                        SELECT to_char(birthday::date, 'MM-DD') AS mmdd FROM "{_BD}".birthdays WHERE user_id = $1
                        ''',
                        str(member.id),
                    )

                    should_have_role = False
                    if birthday_record:
                        member_birthday_mm_dd = birthday_record["mmdd"]
                        if member_birthday_mm_dd == current_pacific_mm_dd:
                            should_have_role = True

                    if not should_have_role:
                        try:
                            await member.remove_roles(birthday_role)
                            self.cog_print(
                                f"[AUDIT] Removed birthday role from {member.display_name} (ID: {member.id}). "
                                f"Reason: Not their birthday ({current_pacific_mm_dd}) or no DB record.",
                            )
                        except nextcord.Forbidden:
                            self.cog_print(
                                f"[ERROR][AUDIT] Bot lacks permissions to remove role from {member.display_name} "
                                f"(ID: {member.id}).",
                            )
                        except Exception as e:
                            self.cog_print(
                                f"[ERROR][AUDIT] Error removing role from {member.display_name} (ID: {member.id}): {e}",
                            )
            elif not birthday_role:
                self.cog_print("[ERROR] Birthday role not found, skipping general role audit.")

    async def store_birthday_message(self, message_id, user_id, pacific_date_str):
        async with self.bot.pg_pool.acquire() as db:
            await db.execute(
                f'''
                INSERT INTO "{_BD}".birthday_messages (message_id, user_id, birthday)
                VALUES ($1, $2, $3)
                ''',
                str(message_id),
                str(user_id),
                pacific_date_str,
            )

    async def remove_birthday_messages(self, birthday_mm_dd):
        async with self.bot.pg_pool.acquire() as db:
            await db.execute(
                f'''
                DELETE FROM "{_BD}".birthday_messages
                WHERE to_char(birthday::date, 'MM-DD') = $1
                ''',
                birthday_mm_dd,
            )
    
    async def grant_birthday_executive_pardon(self, user_id):
        """Grant a 20-hour executive pardon for a user's birthday"""
        try:
            # Try to get the waterboard cog to grant the pardon
            waterboard_cog = self.bot.get_cog('WaterboardCog3')
            if waterboard_cog and hasattr(waterboard_cog, 'executive_pardon'):
                await waterboard_cog.executive_pardon(user_id, 20)  # 20 hours
                _dbg_print(self, f"[DEBUG] Successfully granted 20-hour executive pardon to user {user_id} via WaterboardCog3")
            else:
                self.cog_print(
                    f"[ERROR] WaterboardCog3 or executive_pardon method not found - "
                    f"cannot grant birthday pardon to user {user_id}",
                )
        except Exception as e:
            self.cog_print(f"[ERROR] Failed to grant birthday executive pardon to user {user_id}: {e}")

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
                async with self.bot.pg_pool.acquire() as db:
                    result = await db.fetchrow(
                        f'SELECT birthday FROM "{_BD}".birthdays WHERE user_id = $1',
                        str(user_id),
                    )

                if result:
                    # Check if user can update (is admin or is themselves)
                    can_update = interaction.user.id in admin_user_ids or interaction.user.id == user_id
                    
                    display_name = member.mention
                    try:
                        formatted_birthday = datetime.strptime(result["birthday"], "%Y-%m-%d").strftime("%m/%d")
                    except ValueError:
                        formatted_birthday = "Invalid Date"
                    
                    if can_update:
                        view = UpdateBirthdayView(self, member.display_name, str(user_id), interaction.user.id == user_id)
                        await interaction.response.send_message(f"{display_name}'s birthday is on {formatted_birthday}.", view=view, ephemeral=True)
                    else:
                        await interaction.response.send_message(f"{display_name}'s birthday is on {formatted_birthday}.", ephemeral=True)
                else:
                    if interaction.user.id in admin_user_ids or interaction.user.id == user_id:
                        modal = AddBirthdayModal(self, member.display_name, str(user_id))
                        await interaction.response.send_modal(modal)
                    else:
                        await interaction.response.send_message(f"I don't know {member.display_name}'s birthday.", ephemeral=True)
            else:
                await interaction.response.send_message(f"User {username} not found.", ephemeral=True)
        else:
            async with self.bot.pg_pool.acquire() as db:
                this_month_birthdays = await db.fetch(
                    f'''
                    SELECT user_id, username, birthday FROM "{_BD}".birthdays
                    WHERE EXTRACT(MONTH FROM birthday::date) = $1
                    ''',
                    now.month,
                )
                next_month_birthdays = await db.fetch(
                    f'''
                    SELECT user_id, username, birthday FROM "{_BD}".birthdays
                    WHERE EXTRACT(MONTH FROM birthday::date) = $1
                    ''',
                    next_month,
                )

            embed = nextcord.Embed(title="Upcoming Birthdays", color=0x00ff00)

            if this_month_birthdays:
                this_month_list = []
                for row in this_month_birthdays:
                    user_id, username, birthday = row["user_id"], row["username"], row["birthday"]
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
                for row in next_month_birthdays:
                    user_id, username, birthday = row["user_id"], row["username"], row["birthday"]
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

    @staticmethod
    def _embed_field_value_for_lines(lines: list[str]) -> str:
        if not lines:
            return "—"
        out: list[str] = []
        total = 0
        for i, line in enumerate(lines):
            sep_len = 1 if out else 0
            if total + sep_len + len(line) <= 1010:
                out.append(line)
                total += sep_len + len(line)
            else:
                more = len(lines) - i
                return "\n".join(out) + f"\n… (+{more} more)"
        return "\n".join(out)

    @nextcord.slash_command(
        name="bday-all",
        description="List every month and all birthdays registered in that month.",
        guild_ids=[GUILD_ID],
    )
    async def bday_all(self, interaction: nextcord.Interaction):
        guild = interaction.guild
        async with self.bot.pg_pool.acquire() as db:
            rows = await db.fetch(
                f'''
                SELECT user_id, username, birthday FROM "{_BD}".birthdays
                ORDER BY EXTRACT(MONTH FROM birthday::date), EXTRACT(DAY FROM birthday::date)
                '''
            )

        if not rows:
            await interaction.response.send_message("No birthdays registered yet.", ephemeral=True)
            return

        by_month: dict[int, list[str]] = {m: [] for m in range(1, 13)}
        for row in rows:
            user_id, birthday = row["user_id"], row["birthday"]
            try:
                dt = datetime.strptime(birthday, "%Y-%m-%d")
            except ValueError:
                continue
            member = guild.get_member(int(user_id)) if guild else None
            mention = member.mention if member else f"<@{user_id}>"
            by_month[dt.month].append(f"{mention} : {dt.strftime('%m/%d')}")

        embed = nextcord.Embed(title="All birthdays by month", color=0x00FF00)
        for month in range(1, 13):
            value = self._embed_field_value_for_lines(by_month[month])
            embed.add_field(name=calendar.month_name[month], value=value, inline=False)

        await interaction.response.send_message(embed=embed)

class UpdateBirthdayView(nextcord.ui.View):
    def __init__(self, birthday_cog, username, user_id, is_self):
        super().__init__(timeout=300)  # 5 minute timeout
        self.birthday_cog = birthday_cog
        self.username = username
        self.user_id = user_id
        self.is_self = is_self

    @nextcord.ui.button(label="Update Birthday", style=nextcord.ButtonStyle.secondary, emoji="✏️")
    async def update_birthday(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        modal = UpdateBirthdayModal(self.birthday_cog, self.username, self.user_id, self.is_self)
        await interaction.response.send_modal(modal)

class BirthdayButtonView(nextcord.ui.View):
    def __init__(self, bot, birthday_cog, birthday_user_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.birthday_cog = birthday_cog
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
            _dbg_print(self.birthday_cog, f"[DEBUG] Emoji: {emoji}")
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
    def __init__(self, birthday_cog, username, user_id):
        super().__init__("Add Birthday", timeout=5 * 60)
        self.birthday_cog = birthday_cog
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

        async with self.birthday_cog.bot.pg_pool.acquire() as db:
            try:
                await db.execute(
                    f'''
                    INSERT INTO "{_BD}".birthdays (user_id, username, birthday)
                    VALUES ($1, $2, $3)
                    ''',
                    self.user_id,
                    self.username,
                    formatted_birthday,
                )
                await interaction.response.send_message(f"Added {self.username}'s birthday on {birthday}.", ephemeral=True)
            except asyncpg.UniqueViolationError:
                await interaction.response.send_message(f"A birthday for {self.username} already exists.", ephemeral=True)

class UpdateBirthdayModal(nextcord.ui.Modal):
    def __init__(self, birthday_cog, username, user_id, is_self):
        super().__init__("Update Birthday", timeout=5 * 60)
        self.birthday_cog = birthday_cog
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

        async with self.birthday_cog.bot.pg_pool.acquire() as db:
            await db.execute(
                f'''
                UPDATE "{_BD}".birthdays SET birthday = $1, username = $2 WHERE user_id = $3
                ''',
                formatted_birthday,
                self.username,
                self.user_id,
            )
            
            if self.is_self:
                await interaction.response.send_message(f"Your birthday has been updated to {birthday}.", ephemeral=True)
            else:
                await interaction.response.send_message(f"Updated {self.username}'s birthday to {birthday}.", ephemeral=True)

def setup(bot):
    bot.add_cog(Birthday(bot))
    boot_print("BirthdayCog has been added to the bot.")