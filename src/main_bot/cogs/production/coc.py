import nextcord
from nextcord.ext import commands
import re

from main_bot.boot_log import boot_print
from main_bot.server_configs.config import GUILD_ID
from main_bot.server_configs.config import admin_user_ids

_SC = "coc"


class COC(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.create_tables())

    async def create_tables(self):
        return

    async def add_coc_username(self, discord_user_id, coc_username, town_hall_level=None, nickname=None, account_label=None):
        async with self.bot.pg_pool.acquire() as conn:
            await conn.execute(
                f'''
                INSERT INTO "{_SC}".coc_usernames (discord_user_id, coc_username, town_hall_level, nickname, account_label)
                VALUES ($1, $2, $3, $4, $5)
                ''',
                discord_user_id,
                coc_username,
                town_hall_level,
                nickname,
                account_label,
            )

    async def update_coc_account(self, account_id, coc_username, town_hall_level=None, nickname=None, account_label=None):
        async with self.bot.pg_pool.acquire() as conn:
            await conn.execute(
                f'''
                UPDATE "{_SC}".coc_usernames
                SET coc_username = $1, town_hall_level = $2, nickname = $3, account_label = $4
                WHERE account_id = $5
                ''',
                coc_username,
                town_hall_level,
                nickname,
                account_label,
                account_id,
            )

    async def get_coc_records(self, discord_user_id):
        async with self.bot.pg_pool.acquire() as conn:
            rows = await conn.fetch(
                f'''
                SELECT account_id, coc_username, town_hall_level, nickname, account_label
                FROM "{_SC}".coc_usernames
                WHERE discord_user_id = $1
                ORDER BY account_label, coc_username
                ''',
                discord_user_id,
            )
            return [
                {
                    "account_id": r["account_id"],
                    "coc_username": r["coc_username"],
                    "town_hall_level": r["town_hall_level"],
                    "nickname": r["nickname"],
                    "account_label": r["account_label"],
                }
                for r in rows
            ]

    async def get_coc_record(self, discord_user_id):
        """Legacy method for backward compatibility - returns first record or None"""
        records = await self.get_coc_records(discord_user_id)
        return records[0] if records else None

    async def get_all_coc_usernames(self):
        async with self.bot.pg_pool.acquire() as conn:
            return await conn.fetch(
                f'''
                SELECT account_id, discord_user_id, coc_username, town_hall_level, nickname, account_label
                FROM "{_SC}".coc_usernames
                ORDER BY discord_user_id,
                    CASE WHEN account_label = 'Main' THEN 1
                         WHEN account_label = 'Alt' THEN 2
                         ELSE 3 END,
                    coc_username
                '''
            )

    async def remove_coc_account(self, account_id):
        async with self.bot.pg_pool.acquire() as conn:
            await conn.execute(f'DELETE FROM "{_SC}".coc_usernames WHERE account_id = $1', account_id)

    async def remove_coc_username(self, discord_user_id):
        """Legacy method - removes all accounts for a user"""
        async with self.bot.pg_pool.acquire() as conn:
            await conn.execute(f'DELETE FROM "{_SC}".coc_usernames WHERE discord_user_id = $1', discord_user_id)

    @nextcord.slash_command(name="coc", description="Clash of Clans username management", guild_ids=[GUILD_ID])
    async def coc(self, interaction: nextcord.Interaction, username: nextcord.Member = nextcord.SlashOption(required=False, description='@Username.')):
        
        if username:
            # User provided a discord mention
            user_id = username.id
            member = interaction.guild.get_member(user_id)
            if member is None:
                member = username

            if member:
                coc_records = await self.get_coc_records(user_id)
                
                if coc_records:
                    # User has coc records, display all of them ephemerally with edit option if allowed
                    can_edit = interaction.user.id in admin_user_ids or interaction.user.id == user_id
                    is_admin = interaction.user.id in admin_user_ids
                    
                    embed = nextcord.Embed(
                        title=f"{member.display_name}'s Clash of Clans Accounts",
                        color=0x00ff00
                    )
                    
                    # Display each account as a separate field
                    for record in coc_records:
                        field_name = f"{record['coc_username']}"
                        if record.get('town_hall_level'):
                            field_name += f" [TH{record['town_hall_level']}]"
                        if record.get('account_label'):
                            field_name += f" ({record['account_label']})"
                        
                        field_value = ""
                        if record.get('nickname'):
                            field_value = f"Nickname: {record['nickname']}"
                        
                        embed.add_field(
                            name=field_name,
                            value=field_value if field_value else "\u200B",
                            inline=False
                        )
                    
                    if can_edit:
                        view = EditCOCView(self, member.display_name, str(user_id), coc_records, is_admin)
                        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
                    else:
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                else:
                    # No coc record found
                    # Check if the user calling matches the discord mention OR is an admin
                    can_add = interaction.user.id in admin_user_ids or interaction.user.id == user_id
                    
                    if can_add:
                        view = AccountLabelSelectView(self, member.display_name, str(user_id))
                        await interaction.response.send_message(
                            "Select account type:",
                            view=view,
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message(
                            f"I don't know {member.display_name}'s Clash of Clans username.",
                            ephemeral=True
                        )
            else:
                await interaction.response.send_message(f"User {username} not found.", ephemeral=True)
        else:
            # No username provided, show full list
            all_coc_records = await self.get_all_coc_usernames()
            
            if all_coc_records:
                embed = nextcord.Embed(
                    title="Whose COC is that? :eyes:",
                    color=0x00ff00,
                    description="\u200B"
                )
                
                # Group accounts by discord_user_id
                accounts_by_user = {}
                for account_id, discord_user_id, coc_username, town_hall_level, nickname, account_label in all_coc_records:
                    if discord_user_id not in accounts_by_user:
                        accounts_by_user[discord_user_id] = []
                    accounts_by_user[discord_user_id].append({
                        'account_id': account_id,
                        'coc_username': coc_username,
                        'town_hall_level': town_hall_level,
                        'nickname': nickname,
                        'account_label': account_label
                    })
                
                # Each person gets their own field with all their accounts
                for discord_user_id, accounts in accounts_by_user.items():
                    member = interaction.guild.get_member(int(discord_user_id))
                    if member:
                        member_mention = member.mention
                        member_nickname = accounts[0].get('nickname') if accounts else None
                    else:
                        member_mention = f'<@{discord_user_id}>'
                        member_nickname = None
                    
                    # Field title: All accounts with their labels
                    account_titles = []
                    for account in accounts:
                        account_title = f":crossed_swords: {account['coc_username']}"
                        if account.get('town_hall_level'):
                            if account.get('account_label'):
                                account_title += f" [TH{account['town_hall_level']} - {account['account_label']}]"
                            else:
                                account_title += f" [TH{account['town_hall_level']}]"
                        elif account.get('account_label'):
                            account_title += f" [{account['account_label']}]"
                        account_titles.append(account_title)
                    
                    # Try using newline in field title (Discord may not support this)
                    field_name = "\n".join(account_titles)
                    
                    # Field value: Just the user mention and nickname
                    field_value = member_mention
                    if member_nickname:
                        field_value += f" aka {member_nickname}\n\u200B"
                    else:
                        field_value += "\n\u200B"
                    
                    embed.add_field(
                        name=field_name,
                        value=field_value,
                        inline=False
                    )
                
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message("No Clash of Clans usernames registered yet.", ephemeral=True)


class AccountLabelSelectView(nextcord.ui.View):
    def __init__(self, coc_cog, username, user_id, existing_record=None, account_id=None):
        super().__init__(timeout=300)  # 5 minute timeout
        self.coc_cog = coc_cog
        self.username = username
        self.user_id = user_id
        self.existing_record = existing_record
        self.account_id = account_id

    @nextcord.ui.button(label="Main", style=nextcord.ButtonStyle.primary)
    async def main_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        modal = AddCOCUsernameModal(self.coc_cog, self.username, self.user_id, self.existing_record, "Main", self.account_id)
        await interaction.response.send_modal(modal)

    @nextcord.ui.button(label="Alt", style=nextcord.ButtonStyle.secondary)
    async def alt_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        modal = AddCOCUsernameModal(self.coc_cog, self.username, self.user_id, self.existing_record, "Alt", self.account_id)
        await interaction.response.send_modal(modal)
    
    async def on_timeout(self):
        # Disable buttons when view times out
        for item in self.children:
            item.disabled = True


def validate_alphanumeric(value, field_name):
    """Validate that a value contains only alphanumeric characters and spaces"""
    if not value:
        return None, None
    value = value.strip()
    if not value:
        return None, None
    if not re.match(r'^[a-zA-Z0-9 ]+$', value):
        return None, f"{field_name} must contain only letters, numbers, and spaces."
    return value, None

def validate_town_hall_level(value):
    """Validate that town hall level is 1-2 digits"""
    if not value:
        return None, None
    value = value.strip()
    if not value:
        return None, None
    if not re.match(r'^\d{1,2}$', value):
        return None, "Town Hall Level must be 1-2 digits (e.g., 1, 5, 12)."
    return value, None


class AddCOCUsernameModal(nextcord.ui.Modal):
    def __init__(self, coc_cog, username, user_id, existing_record=None, account_label=None, account_id=None):
        super().__init__("Add Your COC", timeout=5 * 60)
        self.coc_cog = coc_cog
        self.username = username
        self.user_id = user_id
        self.existing_record = existing_record
        self.account_label = account_label or "Main"
        self.account_id = account_id

        self.coc_username = nextcord.ui.TextInput(
            label="What's your Clash of Clans Username?",
            custom_id="coc_username_input",
            style=nextcord.TextInputStyle.short,
            placeholder="JJ3572",
            required=True,
            max_length=50,
            default_value=existing_record.get('coc_username') if existing_record else None
        )

        self.town_hall_level = nextcord.ui.TextInput(
            label="Town Hall Level (optional)",
            custom_id="town_hall_level_input",
            style=nextcord.TextInputStyle.short,
            placeholder="12",
            required=False,
            max_length=2,
            default_value=existing_record.get('town_hall_level') if existing_record else None
        )

        self.nickname = nextcord.ui.TextInput(
            label="Nickname (optional)",
            custom_id="nickname_input",
            style=nextcord.TextInputStyle.short,
            placeholder="Your nickname",
            required=False,
            max_length=50,
            default_value=existing_record.get('nickname') if existing_record else None
        )

        self.add_item(self.coc_username)
        self.add_item(self.town_hall_level)
        self.add_item(self.nickname)

    async def callback(self, interaction: nextcord.Interaction):
        # Validate and sanitize inputs
        coc_username, error = validate_alphanumeric(self.coc_username.value, "Clash of Clans Username")
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        
        if not coc_username:
            await interaction.response.send_message("Clash of Clans username cannot be empty.", ephemeral=True)
            return

        town_hall_level, error = validate_town_hall_level(self.town_hall_level.value)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        nickname, error = validate_alphanumeric(self.nickname.value, "Nickname")
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        # Get the COC cog instance to use its methods
        coc_cog = interaction.client.get_cog('COC')
        if not coc_cog:
            await interaction.response.send_message("COC cog not found.", ephemeral=True)
            return

        try:
            if self.account_id:
                # Updating existing account
                await coc_cog.update_coc_account(
                    self.account_id, coc_username, town_hall_level, nickname, self.account_label
                )
                action = "updated"
            else:
                # Adding new account
                await coc_cog.add_coc_username(
                    self.user_id, coc_username, town_hall_level, nickname, self.account_label
                )
                action = "added"
            
            # Check if user is adding for themselves or as admin
            if interaction.user.id == int(self.user_id):
                await interaction.response.send_message(
                    f"Your Clash of Clans account ({self.account_label}) has been {action}.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"{self.username}'s Clash of Clans account ({self.account_label}) has been {action}.",
                    ephemeral=True
                )
        except Exception as e:
            await interaction.response.send_message(
                f"An error occurred while saving: {str(e)}",
                ephemeral=True
            )


class EditCOCView(nextcord.ui.View):
    def __init__(self, coc_cog, username, user_id, coc_records, is_admin):
        super().__init__(timeout=300)  # 5 minute timeout
        self.coc_cog = coc_cog
        self.username = username
        self.user_id = user_id
        self.coc_records = coc_records  # List of account records
        self.is_admin = is_admin
        
        # Add buttons for each account
        for record in coc_records:
            account_id = record['account_id']
            account_label = record.get('account_label', 'Main')
            coc_username = record['coc_username']
            
            # Edit button for this account
            edit_button = nextcord.ui.Button(
                label=f"Edit {coc_username} ({account_label})",
                style=nextcord.ButtonStyle.primary,
                emoji="✏️",
                custom_id=f"edit_{account_id}"
            )
            edit_button.callback = self.create_edit_callback(record)
            self.add_item(edit_button)
            
            # Delete button for this account (only if admin or if more than one account)
            if is_admin or len(coc_records) > 1:
                delete_button = nextcord.ui.Button(
                    label=f"Delete {coc_username}",
                    style=nextcord.ButtonStyle.danger,
                    emoji="🗑️",
                    custom_id=f"delete_{account_id}"
                )
                delete_button.callback = self.create_delete_callback(account_id, coc_username)
                self.add_item(delete_button)
        
        # Add Account button
        add_button = nextcord.ui.Button(label="Add Account", style=nextcord.ButtonStyle.success, emoji="➕")
        add_button.callback = self.add_account_callback
        self.add_item(add_button)
    
    def create_edit_callback(self, record):
        async def edit_callback(interaction: nextcord.Interaction):
            view = AccountLabelSelectView(
                self.coc_cog, self.username, self.user_id, record, record['account_id']
            )
            await interaction.response.send_message(
                f"Select account type for {record['coc_username']}:",
                view=view,
                ephemeral=True
            )
        return edit_callback
    
    def create_delete_callback(self, account_id, coc_username):
        async def delete_callback(interaction: nextcord.Interaction):
            # Prevent deleting last account
            if len(self.coc_records) <= 1:
                await interaction.response.send_message(
                    "Cannot delete the last account. Add another account first.",
                    ephemeral=True
                )
                return
            
            # Get the COC cog instance to use its methods
            coc_cog = interaction.client.get_cog('COC')
            if not coc_cog:
                await interaction.response.send_message("COC cog not found.", ephemeral=True)
                return
            
            await coc_cog.remove_coc_account(account_id)
            
            await interaction.response.send_message(
                f"Account {coc_username} has been deleted.",
                ephemeral=True
            )
        return delete_callback
    
    async def add_account_callback(self, interaction: nextcord.Interaction):
        view = AccountLabelSelectView(self.coc_cog, self.username, self.user_id)
        await interaction.response.send_message(
            "Select account type:",
            view=view,
            ephemeral=True
        )
    
    async def on_timeout(self):
        # Disable buttons when view times out
        for item in self.children:
            item.disabled = True


def setup(bot):
    bot.add_cog(COC(bot))
    boot_print("COC cog loaded")