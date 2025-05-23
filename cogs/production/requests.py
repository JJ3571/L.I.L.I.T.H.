import nextcord
from nextcord.ext import commands
import sqlite3
from nextcord import Interaction, SlashOption, ChannelType, Embed, Color
from nextcord.ui import Button, View, Modal, TextInput
from datetime import datetime
import math
import pytz

from server_configs.config import GUILD_ID
from server_configs.cogs_config import admin_user_ids

DB_PATH = "request.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL, -- 'feature' or 'bugfix'
            description TEXT NOT NULL,
            status TEXT NOT NULL, -- 'active' or 'resolved'
            requester_id INTEGER NOT NULL,
            requester_name TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

class RequestModal(Modal):
    def __init__(self, request_type: str, cog_instance): 
        super().__init__(f"Submit {request_type.capitalize()} Request")
        self.request_type = request_type
        # self.cog_instance = cog_instance # Not strictly necessary for this modal's operation

        self.description_input = TextInput(
            label=f"{request_type.capitalize()} Description",
            style=nextcord.TextInputStyle.paragraph,
            placeholder=f"Describe the {self.request_type} in detail...",
            required=True,
            min_length=10,
            max_length=1000
        )
        self.add_item(self.description_input)

    async def callback(self, interaction: Interaction):
        description = self.description_input.value
        requester_id = interaction.user.id
        requester_name = interaction.user.name
        timestamp = datetime.utcnow()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO requests (type, description, status, requester_id, requester_name, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (self.request_type, description, "active", requester_id, requester_name, timestamp))
        request_id = cursor.lastrowid
        conn.commit()
        conn.close()

        embed = Embed(
            title=f"{self.request_type.capitalize()} Request Submitted!",
            description=f"Your {self.request_type} request has been successfully submitted.\nID: `{request_id}`",
            color=Color.green(),
            timestamp=timestamp
        )
        embed.add_field(name="Description", value=description, inline=False)
        embed.set_footer(text=f"Submitted by {requester_name}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class RequestListView(View):
    def __init__(self, interaction: Interaction, embeds: list, title: str):
        super().__init__(timeout=180)
        self.interaction = interaction
        self.embeds = embeds
        self.current_page = 0
        self.title = title
        # self.update_buttons() # Called by _create_paginated_embeds after view is created

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user != self.interaction.user:
            await interaction.response.send_message("You cannot control this pagination.", ephemeral=True)
            return False
        return True

    def update_buttons(self):
        if not self.children or len(self.children) < 2: # Ensure buttons are present
            return
            
        self.children[0].disabled = self.current_page == 0
        self.children[1].disabled = self.current_page == len(self.embeds) - 1

        # Update page number in embed footer
        for i, embed in enumerate(self.embeds): # Ensure all embeds are updated if needed
             embed.set_footer(text=f"{self.title} - Page {self.current_page + 1}/{len(self.embeds)}")


    @nextcord.ui.button(label="Previous", style=nextcord.ButtonStyle.grey)
    async def previous_button(self, button: Button, interaction: Interaction):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @nextcord.ui.button(label="Next", style=nextcord.ButtonStyle.grey)
    async def next_button(self, button: Button, interaction: Interaction):
        if self.current_page < len(self.embeds) - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)


class RequestsCog(commands.Cog, name="Requests"):
    def __init__(self, bot):
        self.bot = bot
        self.utc_tz = pytz.utc
        self.pst_tz = pytz.timezone("America/Los_Angeles")

    async def _get_requests(self, request_type: str, status: str = "active"):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, description, requester_name, timestamp FROM requests
            WHERE type = ? AND status = ? ORDER BY timestamp DESC
        """, (request_type, status))
        requests = cursor.fetchall()
        conn.close()
        return requests

    async def _create_paginated_embeds(self, interaction: Interaction, request_list: list, title: str, request_type_display: str):
        embeds = []
        items_per_page = 5
        num_pages = math.ceil(len(request_list) / items_per_page)

        # The calling function should handle the "no requests found" case and not call this if request_list is empty.

        base_color = Color.blue() # Default for features
        if "bug" in request_type_display.lower() or "bug" in title.lower():
            base_color = Color.orange()

        for i in range(num_pages):
            embed = Embed(title=title, color=base_color)
            start_index = i * items_per_page
            end_index = start_index + items_per_page
            page_requests = request_list[start_index:end_index]

            for req in page_requests:
                req_timestamp_pst: datetime # This will be our PST-aware datetime
                try:
                    # req['timestamp'] is a string like '2025-05-23 03:06:33.129370' from SQLite (UTC)
                    ts_str = req['timestamp'].split('.')[0] # Remove microseconds for parsing
                    
                    naive_dt: datetime
                    if 'T' in ts_str: # ISO format with T
                        naive_dt = datetime.fromisoformat(ts_str)
                    else: # Assuming space separator, e.g., "YYYY-MM-DD HH:MM:S"
                        naive_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                    
                    # Make the naive datetime UTC-aware
                    utc_aware_dt = self.utc_tz.localize(naive_dt)
                    
                    # Convert to PST
                    req_timestamp_pst = utc_aware_dt.astimezone(self.pst_tz)

                except ValueError: # Fallback or log error if parsing fails
                    # If parsing fails, create a current timestamp in PST as a fallback
                    now_utc_aware = self.utc_tz.localize(datetime.utcnow())
                    req_timestamp_pst = now_utc_aware.astimezone(self.pst_tz)
                except Exception: 
                    req_timestamp_pst = datetime.now(self.pst_tz)


                embed.add_field(
                    name=f"ID: `{req['id']}` - Submitted by {req['requester_name']}",
                    # .timestamp() on an aware datetime object correctly gives the UTC Unix timestamp
                    value=f"```{req['description'][:200]}{'...' if len(req['description']) > 200 else ''}```\n*Requested: <t:{int(req_timestamp_pst.timestamp())}:R>*",
                    inline=False
                )
            # Footer set by RequestListView.update_buttons
            # embed.set_footer(text=f"{title} - Page {i + 1}/{num_pages}") # This will be set by the view
            embeds.append(embed)
        
        view = RequestListView(interaction, embeds, title)
        view.update_buttons() # Initial button state and footer text
        await interaction.followup.send(embed=embeds[0], view=view, ephemeral=True)


    # --- Feature Request Commands ---
    @nextcord.slash_command(name="feature", description="Manage feature requests.", guild_ids=[GUILD_ID])
    async def feature_group(self, interaction: Interaction):
        # This will not be called if subcommands are used.
        pass

    @feature_group.subcommand(name="request", description="Submit a new feature request.")
    async def feature_request(self, interaction: Interaction):
        modal = RequestModal(request_type="feature", cog_instance=self)
        await interaction.response.send_modal(modal)

    @feature_group.subcommand(name="list", description="List active feature requests.")
    async def feature_list(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        active_features = await self._get_requests(request_type="feature", status="active")

        if not active_features:
            embed = Embed(title="Active Feature Requests", description="No active feature requests found.", color=Color.blue())
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        await self._create_paginated_embeds(interaction, active_features, "Active Feature Requests", "Feature Requests")

    @feature_group.subcommand(name="resolve", description="Mark a feature request as resolved.")
    async def feature_resolve(
        self,
        interaction: Interaction,
        request_id: int = SlashOption(description="The ID of the feature request to resolve.", required=True)
    ):
        if interaction.user.id not in admin_user_ids:
            await interaction.response.send_message("You do not have permission to resolve requests.", ephemeral=True)
            return

        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT description, status, requester_name FROM requests WHERE id = ? AND type = ?", (request_id, "feature"))
        request_data = cursor.fetchone()

        if not request_data:
            await interaction.response.send_message(f"Feature request with ID `{request_id}` not found or is not a feature request.", ephemeral=True)
            conn.close()
            return

        if request_data["status"] == "resolved":
            await interaction.response.send_message(f"Feature request ID `{request_id}` is already resolved.", ephemeral=True)
            conn.close()
            return

        cursor.execute("UPDATE requests SET status = ? WHERE id = ?", ("resolved", request_id))
        conn.commit()
        conn.close()

        embed = Embed(
            title="Feature Request Resolved!",
            description=f"`Request ID {request_id}` has been marked as resolved.",
            color=Color.dark_green()
        )
        desc_val = request_data['description']
        embed.add_field(name="Original Description", value=desc_val[:1020] + "..." if len(desc_val) > 1024 else desc_val, inline=False)
        embed.set_footer(text=f"Originally submitted by {request_data['requester_name']}")
        await interaction.response.send_message(embed=embed) # Non-ephemeral confirmation

    # --- Bug Report Commands ---
    @nextcord.slash_command(name="bug", description="Manage bug reports.", guild_ids=[GUILD_ID])
    async def bug_group(self, interaction: Interaction):
        # This will not be called if subcommands are used.
        pass

    @bug_group.subcommand(name="report", description="Report a new bug.")
    async def bug_report(self, interaction: Interaction):
        modal = RequestModal(request_type="bugfix", cog_instance=self)
        await interaction.response.send_modal(modal)

    @bug_group.subcommand(name="list", description="List active bug reports.")
    async def bug_list(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        active_bugs = await self._get_requests(request_type="bugfix", status="active")

        if not active_bugs:
            embed = Embed(title="Active Bug Reports", description="No active bug reports found.", color=Color.orange())
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        await self._create_paginated_embeds(interaction, active_bugs, "Active Bug Reports", "Bug Reports")

    @bug_group.subcommand(name="resolve", description="Mark a bug report as resolved.")
    async def bug_resolve(
        self,
        interaction: Interaction,
        request_id: int = SlashOption(description="The ID of the bug report to resolve.", required=True)
    ):
        if interaction.user.id not in admin_user_ids:
            await interaction.response.send_message("You do not have permission to resolve requests.", ephemeral=True)
            return

        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT description, status, requester_name FROM requests WHERE id = ? AND type = ?", (request_id, "bugfix"))
        request_data = cursor.fetchone()

        if not request_data:
            await interaction.response.send_message(f"Bug report with ID `{request_id}` not found or is not a bug report.", ephemeral=True)
            conn.close()
            return

        if request_data["status"] == "resolved":
            await interaction.response.send_message(f"Bug report ID `{request_id}` is already resolved.", ephemeral=True)
            conn.close()
            return

        cursor.execute("UPDATE requests SET status = ? WHERE id = ?", ("resolved", request_id))
        conn.commit()
        conn.close()

        embed = Embed(
            title="Bug Report Resolved!",
            description=f"Bug report ID `{request_id}` has been marked as resolved.",
            color=Color.dark_green()
        )
        desc_val = request_data['description']
        embed.add_field(name="Original Description", value=desc_val[:1020] + "..." if len(desc_val) > 1024 else desc_val, inline=False)
        embed.set_footer(text=f"Originally submitted by {request_data['requester_name']}")
        await interaction.response.send_message(embed=embed) # Non-ephemeral confirmation

def setup(bot):
    bot.add_cog(RequestsCog(bot))