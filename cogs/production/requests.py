import nextcord
from nextcord.ext import commands
import sqlite3
from nextcord import Interaction, SlashOption, ChannelType, Embed, Color
from nextcord.ui import Button, View, Modal, TextInput
from datetime import datetime
import math

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

# Initialize the database and table when the script loads
init_db()

class RequestModal(Modal):
    def __init__(self, request_type: str, cog_instance):
        super().__init__(f"Submit {request_type.capitalize()} Request")
        self.request_type = request_type
        self.cog_instance = cog_instance

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
        self.update_buttons()

    async def interaction_check(self, interaction: Interaction) -> bool:
        return interaction.user == self.interaction.user

    def update_buttons(self):
        if self.current_page == 0:
            self.children[0].disabled = True # Previous button
        else:
            self.children[0].disabled = False

        if self.current_page == len(self.embeds) - 1:
            self.children[1].disabled = True # Next button
        else:
            self.children[1].disabled = False

        # Update page number in embed footer
        for embed in self.embeds:
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
        items_per_page = 5 # Reduced from 10 for better display with more fields
        num_pages = math.ceil(len(request_list) / items_per_page)

        if not request_list:
            embed = Embed(title=title, description=f"No active {request_type_display.lower()}s found.", color=Color.blue())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        for i in range(num_pages):
            embed = Embed(title=title, color=Color.blue())
            start_index = i * items_per_page
            end_index = start_index + items_per_page
            page_requests = request_list[start_index:end_index]

            for req in page_requests:
                req_timestamp = datetime.strptime(req['timestamp'].split('.')[0], "%Y-%m-%d %H:%M:%S")
                embed.add_field(
                    name=f"ID: `{req['id']}` - Submitted by {req['requester_name']}",
                    value=f"```{req['description'][:200]}{'...' if len(req['description']) > 200 else ''}```\n*Requested: <t:{int(req_timestamp.timestamp())}:R>*",
                    inline=False
                )
            embed.set_footer(text=f"{title} - Page {i + 1}/{num_pages}")
            embeds.append(embed)
        
        view = RequestListView(interaction, embeds, title)
        view.update_buttons() # Initial button state
        await interaction.response.send_message(embed=embeds[0], view=view, ephemeral=True)


    @nextcord.slash_command(name="request", description="Manage feature and bugfix requests.")
    async def request_group(self, interaction: Interaction):
        # This will not be called if subcommands are used.
        pass

    @request_group.subcommand(name="feature", description="Submit a new feature request.")
    async def request_feature(self, interaction: Interaction):
        modal = RequestModal(request_type="feature", cog_instance=self)
        await interaction.response.send_modal(modal)

    @request_group.subcommand(name="bugfix", description="Report a bug.")
    async def request_bugfix(self, interaction: Interaction):
        modal = RequestModal(request_type="bugfix", cog_instance=self)
        await interaction.response.send_modal(modal)

    @request_group.subcommand(name="list", description="List active feature and bug requests.")
    async def request_list(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        active_features = await self._get_requests("feature", "active")
        active_bugs = await self._get_requests("bugfix", "active")

        if not active_features and not active_bugs:
            await interaction.followup.send("No active feature requests or bug reports found.", ephemeral=True)
            return
        
        if active_features:
            await self._create_paginated_embeds(interaction, active_features, "Active Feature Requests", "Feature Requests")
        else:
            embed_features = Embed(title="Active Feature Requests", description="No active feature requests found.", color=Color.blue())
            await interaction.followup.send(embed=embed_features, ephemeral=True) # Use followup if deferred

        # Send bug list as a new message if features were sent, or followup if no features.
        # To avoid "interaction has already been responded to" if both lists are sent to the same initial interaction response.
        # A better UX might be to combine them or use a different interaction point for the second list.
        # For now, we'll send the second list as a new followup if the first was sent.
        
        if active_bugs:
            # Create a new interaction context for the second list if the first was already sent.
            # This is a simplified way; a more robust solution might involve a different command or a more complex view.
            # For now, we'll send it as a separate followup.
            # If the first list was sent via interaction.response.send_message, subsequent ones must use interaction.followup.send
            
            # Create embeds for bugs
            bug_embeds = []
            items_per_page = 5
            num_bug_pages = math.ceil(len(active_bugs) / items_per_page)

            if num_bug_pages > 0:
                for i in range(num_bug_pages):
                    embed = Embed(title="Active Bug Reports", color=Color.orange())
                    start_index = i * items_per_page
                    end_index = start_index + items_per_page
                    page_bugs = active_bugs[start_index:end_index]

                    for bug in page_bugs:
                        bug_timestamp = datetime.strptime(bug['timestamp'].split('.')[0], "%Y-%m-%d %H:%M:%S")
                        embed.add_field(
                            name=f"ID: `{bug['id']}` - Reported by {bug['requester_name']}",
                            value=f"```{bug['description'][:200]}{'...' if len(bug['description']) > 200 else ''}```\n*Reported: <t:{int(bug_timestamp.timestamp())}:R>*",
                            inline=False
                        )
                    embed.set_footer(text=f"Active Bug Reports - Page {i + 1}/{num_bug_pages}")
                    bug_embeds.append(embed)
            
                bug_view = RequestListView(interaction, bug_embeds, "Active Bug Reports") # Re-use interaction for view owner
                bug_view.update_buttons()
                await interaction.followup.send(embed=bug_embeds[0], view=bug_view, ephemeral=True)

        elif not active_features: # Only if features were also empty
             pass # Already handled by the initial "no active requests" message
        else: # Features existed, but no bugs
            embed_bugs = Embed(title="Active Bug Reports", description="No active bug reports found.", color=Color.orange())
            await interaction.followup.send(embed=embed_bugs, ephemeral=True)


    @request_group.subcommand(name="resolve", description="Mark a request as resolved.")
    async def request_resolve(
        self,
        interaction: Interaction,
        request_id: int = SlashOption(description="The ID of the request to resolve.", required=True)
    ):
        if interaction.user.id not in admin_user_ids:
            await interaction.response.send_message("You do not have permission to resolve requests.", ephemeral=True)
            return

        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT type, description, status, requester_name FROM requests WHERE id = ?", (request_id,))
        request_data = cursor.fetchone()

        if not request_data:
            await interaction.response.send_message(f"Request with ID `{request_id}` not found.", ephemeral=True)
            conn.close()
            return

        if request_data["status"] == "resolved":
            await interaction.response.send_message(f"Request ID `{request_id}` is already resolved.", ephemeral=True)
            conn.close()
            return

        cursor.execute("UPDATE requests SET status = ? WHERE id = ?", ("resolved", request_id))
        conn.commit()
        conn.close()

        embed = Embed(
            title=f"{request_data['type'].capitalize()} Request Resolved!",
            description=f"Request ID `{request_id}` has been marked as resolved.",
            color=Color.dark_green()
        )
        embed.add_field(name="Original Description", value=request_data['description'][:1020] + "..." if len(request_data['description']) > 1024 else request_data['description'] , inline=False)
        embed.set_footer(text=f"Originally submitted by {request_data['requester_name']}")
        await interaction.response.send_message(embed=embed)


def setup(bot):
    bot.add_cog(RequestsCog(bot))