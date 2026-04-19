import nextcord
from nextcord.ext import commands
import asyncpg
from nextcord import Interaction, SlashOption, ChannelType
from nextcord.ui import Button, View, Modal, TextInput
from datetime import datetime

from main_bot.boot_log import boot_print
from main_bot.cog_log_mixin import CogLogMixin
from main_bot.server_configs.config import GUILD_ID
from main_bot.server_configs.config import admin_user_ids

_WG = "wager"


def _dt_ts(val) -> int:
    if val is None:
        return 0
    if isinstance(val, datetime):
        return int(val.timestamp())
    s = str(val).split("+")[0].strip()
    if "." in s:
        s = s.rsplit(".", 1)[0]
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp())


# --- UI Modals ---
class BetAmountModal(Modal):
    def __init__(self, event_id: int, outcome_id: int, outcome_text: str, betting_cog):
        super().__init__(title=f"Bet on: {outcome_text}")
        self.event_id = event_id
        self.outcome_id = outcome_id
        self.outcome_text = outcome_text
        self.betting_cog = betting_cog

        self.amount_input = TextInput(
            label="Enter your bet amount",
            placeholder="e.g., 100",
            min_length=1,
            max_length=10,
            required=True,
            style=nextcord.TextInputStyle.short
        )
        self.add_item(self.amount_input)

    async def callback(self, interaction: Interaction):
        try:
            amount = int(self.amount_input.value)
            if amount <= 0:
                await interaction.send("Bet amount must be a positive number.", ephemeral=True)
                return
        except ValueError:
            await interaction.send("Invalid amount. Please enter a number.", ephemeral=True)
            return

        economy_cog = self.betting_cog.bot.get_cog('Economy')
        if not economy_cog:
            await interaction.send("Economy system is currently unavailable.", ephemeral=True)
            return

        user_id = interaction.user.id
        user_balance = await economy_cog.get_user_balance(user_id)

        if amount > user_balance:
            await interaction.send(f"You do not have enough funds. Your balance: {user_balance}", ephemeral=True)
            return

        await economy_cog.update_balance(user_id, -amount)

        try:
            async with self.betting_cog.bot.pg_pool.acquire() as conn:
                await conn.execute(
                    f'''
                    INSERT INTO "{_WG}".user_bets (user_id, event_id, outcome_id, amount)
                    VALUES ($1, $2, $3, $4)
                    ''',
                    user_id,
                    self.event_id,
                    self.outcome_id,
                    amount,
                )
            await interaction.send(
                f"You successfully bet {amount} on '{self.outcome_text}' for Event ID {self.event_id}!",
                ephemeral=True,
            )
            await self.betting_cog.update_event_message(self.event_id)
        except asyncpg.PostgresError as e:
            await economy_cog.update_balance(user_id, amount)
            await interaction.send(f"An error occurred while placing your bet: {e}", ephemeral=True)


class ViewBetsButton(Button):
    def __init__(self, event_id: int, cog_instance):
        super().__init__(label="View Current Bets", style=nextcord.ButtonStyle.secondary, custom_id=f"view_bets_{event_id}")
        self.event_id = event_id
        self.cog = cog_instance

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        pool = self.cog.bot.pg_pool
        async with pool.acquire() as conn:
            event_details = await conn.fetchrow(
                f'SELECT title FROM "{_WG}".betting_events WHERE event_id = $1',
                self.event_id,
            )
            if not event_details:
                await interaction.followup.send("Could not find details for this event.", ephemeral=True)
                return

            outcomes = await conn.fetch(
                f'SELECT outcome_id, outcome_text FROM "{_WG}".event_outcomes WHERE event_id = $1',
                self.event_id,
            )

            bets_by_outcome = {outcome["outcome_id"]: [] for outcome in outcomes}

            all_bets = await conn.fetch(
                f'SELECT user_id, outcome_id, amount FROM "{_WG}".user_bets WHERE event_id = $1',
                self.event_id,
            )

        for bet in all_bets:
            if bet["outcome_id"] in bets_by_outcome:
                member = interaction.guild.get_member(bet["user_id"])
                user_display = member.mention if member else f"User ID: {bet['user_id']}"
                bets_by_outcome[bet["outcome_id"]].append(f"{user_display}: {bet['amount']}")

        if not all_bets:
            await interaction.followup.send(f"No bets have been placed on '{event_details['title']}' yet.", ephemeral=True)
            return

        embed = nextcord.Embed(title=f"Current Bets on: {event_details['title']}", color=nextcord.Color.gold())

        for outcome in outcomes:
            outcome_id = outcome['outcome_id']
            outcome_text = outcome['outcome_text']
            bets_list = bets_by_outcome.get(outcome_id, [])
            
            if bets_list:
                embed.add_field(name=f"Outcome: {outcome_text}", value="\n".join(bets_list), inline=False)
            else:
                embed.add_field(name=f"Outcome: {outcome_text}", value="No bets yet.", inline=False)
        
        if not embed.fields: # Should not happen if outcomes exist, but as a safeguard
             await interaction.followup.send(f"No bets or outcomes to display for '{event_details['title']}'.", ephemeral=True)
             return

        await interaction.followup.send(embed=embed, ephemeral=True)


class BettingEventView(View):
    def __init__(self, event_id: int, outcomes: list, cog_instance, event_creator_id: int):
        super().__init__(timeout=None) # Persistent view
        self.event_id = event_id
        self.cog = cog_instance
        self.event_creator_id = event_creator_id

        for outcome in outcomes: # outcome is a dict/Row like {'outcome_id': 1, 'outcome_text': 'Team A'}
            self.add_item(OutcomeButton(event_id, outcome['outcome_id'], outcome['outcome_text'], cog_instance))
        
        self.add_item(FinalizeEventButton(event_id, cog_instance, event_creator_id))
        self.add_item(ViewBetsButton(event_id, cog_instance))


class OutcomeButton(Button):
    def __init__(self, event_id: int, outcome_id: int, outcome_text: str, cog_instance):
        super().__init__(label=outcome_text, style=nextcord.ButtonStyle.primary, custom_id=f"bet_{event_id}_{outcome_id}")
        self.event_id = event_id
        self.outcome_id = outcome_id
        self.outcome_text = outcome_text
        self.cog = cog_instance

    async def callback(self, interaction: Interaction):
        async with self.cog.bot.pg_pool.acquire() as conn:
            event_data = await conn.fetchrow(
                f'SELECT status FROM "{_WG}".betting_events WHERE event_id = $1',
                self.event_id,
            )

        if not event_data or event_data["status"] != "open":
            await interaction.send("Betting for this event is currently closed.", ephemeral=True)
            return
            
        # If admin, and wants to bet (this is simplified: admin clicking is a bet by default here)
        # The "are you betting or managing" distinction is better handled at finalization stage or with separate admin commands
        
        modal = BetAmountModal(self.event_id, self.outcome_id, self.outcome_text, self.cog)
        await interaction.response.send_modal(modal)


class FinalizeEventButton(Button):
    def __init__(self, event_id: int, cog_instance, event_creator_id: int):
        super().__init__(label="Close & Request Finalization", style=nextcord.ButtonStyle.secondary, custom_id=f"finalize_req_{event_id}")
        self.event_id = event_id
        self.cog = cog_instance
        self.event_creator_id = event_creator_id # To allow creator to initiate finalization request

    async def callback(self, interaction: Interaction):
        pool = self.cog.bot.pg_pool
        async with pool.acquire() as conn:
            event = await conn.fetchrow(
                f'SELECT status, creator_user_id FROM "{_WG}".betting_events WHERE event_id = $1',
                self.event_id,
            )

        if not event:
            await interaction.send("Event not found.", ephemeral=True)
            return

        is_admin = interaction.user.id in admin_user_ids
        is_creator = interaction.user.id == event["creator_user_id"]

        if event["status"] == "open" and (is_admin or is_creator):
            async with pool.acquire() as conn:
                await conn.execute(
                    f'UPDATE "{_WG}".betting_events SET status = $1 WHERE event_id = $2',
                    "closed_for_betting",
                    self.event_id,
                )
            await interaction.send(
                "Betting for this event has been closed. Admins can now finalize and choose the winning outcome!",
                ephemeral=True,
            )
            await self.cog.update_event_message(self.event_id, new_status_display="Betting Closed")
        elif event["status"] in ("closed_for_betting", "pending_finalization") and is_admin:
            async with pool.acquire() as conn:
                outcomes = await conn.fetch(
                    f'SELECT outcome_id, outcome_text FROM "{_WG}".event_outcomes WHERE event_id = $1',
                    self.event_id,
                )
            if not outcomes:
                await interaction.send("No outcomes found for this event to finalize.", ephemeral=True)
                return

            admin_has_bets = await pool.fetchval(
                f'SELECT 1 FROM "{_WG}".user_bets WHERE event_id = $1 AND user_id = $2',
                self.event_id,
                interaction.user.id,
            ) is not None

            if admin_has_bets:
                confirm_view = ConfirmAdminFinalizeView(
                    self.event_id,
                    outcomes,
                    self.cog,
                    interaction.user.id,
                    "You have personal bets on this event. This action will be logged. Proceed?",
                )
                await interaction.send(
                    "**Admin Finalization Warning**\n\nYou have placed personal bets on this event. Finalizing it yourself will be logged! Please select the winning outcome:",
                    view=confirm_view,
                    ephemeral=True,
                )
            else:
                select_view = AdminSelectOutcomeView(self.event_id, outcomes, self.cog, interaction.user.id)
                await interaction.send("Please select the winning outcome:", view=select_view, ephemeral=True)

        elif event["status"] == "finalized":
            await interaction.send("This event has already been finalized.", ephemeral=True)
        else:
            await interaction.send(
                "You do not have permission to finalize this event now, or it's not ready for finalization.",
                ephemeral=True,
            )


class PendingFinalizationView(View):
    def __init__(self, pending_events: list, cog_instance):
        super().__init__(timeout=300) # 5 minutes
        self.cog = cog_instance
        
        if not pending_events:
            # This view shouldn't be created if there are no pending events.
            # The calling command should handle this.
            return

        for event in pending_events[:5]: # Limit to 5 buttons to keep view clean
            self.add_item(TriggerFinalizationButton(event_id=event['event_id'], cog_instance=self.cog))


class TriggerFinalizationButton(Button):
    def __init__(self, event_id: int, cog_instance):
        super().__init__(label=f"Finalize Event ID: {event_id}", style=nextcord.ButtonStyle.danger, custom_id=f"trigger_finalize_{event_id}")
        self.event_id = event_id
        self.cog = cog_instance

    async def callback(self, interaction: Interaction):
        # This button is intended for admins from the list_pending_finalization view.
        # It will essentially replicate the admin part of FinalizeEventButton's callback
        if interaction.user.id not in admin_user_ids:
            await interaction.send("You do not have permission to do this.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        pool = self.cog.bot.pg_pool
        async with pool.acquire() as conn:
            event = await conn.fetchrow(
                f'SELECT status FROM "{_WG}".betting_events WHERE event_id = $1',
                self.event_id,
            )

        if not event:
            await interaction.followup.send("Event not found.", ephemeral=True)
            return

        if event["status"] not in ("closed_for_betting", "pending_finalization"):
            await interaction.followup.send(
                f"Event {self.event_id} is not ready for finalization (Status: {event['status']}).",
                ephemeral=True,
            )
            return

        async with pool.acquire() as conn:
            outcomes = await conn.fetch(
                f'SELECT outcome_id, outcome_text FROM "{_WG}".event_outcomes WHERE event_id = $1',
                self.event_id,
            )

        if not outcomes:
            await interaction.followup.send("No outcomes found for this event to finalize.", ephemeral=True)
            return

        admin_has_bets = await pool.fetchval(
            f'SELECT 1 FROM "{_WG}".user_bets WHERE event_id = $1 AND user_id = $2',
            self.event_id,
            interaction.user.id,
        ) is not None

        if admin_has_bets:
            confirm_view = ConfirmAdminFinalizeView(self.event_id, outcomes, self.cog, interaction.user.id, "You have personal bets on this event. This action will be logged. Proceed?")
            await interaction.followup.send(
                "**Admin Finalization Warning**\n\nYou have placed personal bets on this event. Finalizing it yourself will be logged! Please select the winning outcome:",
                view=confirm_view,
                ephemeral=True
            )
        else:
            select_view = AdminSelectOutcomeView(self.event_id, outcomes, self.cog, interaction.user.id)
            await interaction.followup.send("Please select the winning outcome:", view=select_view, ephemeral=True)


class AdminSelectOutcomeView(View):
    def __init__(self, event_id: int, outcomes: list, cog_instance, admin_id: int, prompt_message:str = None):
        super().__init__(timeout=180) # Admin has some time to select
        self.event_id = event_id
        self.cog = cog_instance
        self.admin_id = admin_id
        
        options = []
        for outcome in outcomes:
            options.append(nextcord.SelectOption(label=outcome['outcome_text'], value=str(outcome['outcome_id']), description=f"ID: {outcome['outcome_id']}"))
        
        self.select_outcome = nextcord.ui.Select(placeholder="Choose the winning outcome...", min_values=1, max_values=1, options=options)
        self.select_outcome.callback = self.outcome_selected_callback # Assign callback directly
        self.add_item(self.select_outcome)
        if prompt_message: # For the confirm view
            self.prompt_message_content = prompt_message

    async def outcome_selected_callback(self, interaction: Interaction):
        winning_outcome_id = int(self.select_outcome.values[0])
        
        # Disable the view after selection
        for item in self.children:
            item.disabled = True # Ensure all items in the view are disabled
        
        # Use interaction.response.edit_message for component interactions
        await interaction.response.edit_message(view=self)

        await self.cog.finalize_event_logic(interaction, self.event_id, winning_outcome_id, self.admin_id)


class SelectWagerButton(Button):
    def __init__(self, event_id: int, event_title: str, cog_instance):
        # Shorten title if too long for a button label
        label = f"ID: {event_id} - {event_title[:50]}" + ("..." if len(event_title) > 50 else "")
        super().__init__(label=label, style=nextcord.ButtonStyle.secondary, custom_id=f"list_select_event_{event_id}")
        self.event_id = event_id
        self.cog = cog_instance # BettingCog instance

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        pool = self.cog.bot.pg_pool
        async with pool.acquire() as conn:
            event_data = await conn.fetchrow(
                f'''
                SELECT event_id, title, description, creator_user_id FROM "{_WG}".betting_events
                WHERE event_id = $1 AND status = 'open'
                ''',
                self.event_id,
            )

            if not event_data:
                await interaction.followup.send("This wager might no longer be active or available.", ephemeral=True)
                return

            outcomes = await conn.fetch(
                f'SELECT outcome_id, outcome_text FROM "{_WG}".event_outcomes WHERE event_id = $1',
                self.event_id,
            )

        if not outcomes:
            await interaction.followup.send("Could not retrieve outcomes for this wager.", ephemeral=True)
            return

        # Prepare data for BettingEventView
        # outcomes from db are already list of Rows (dict-like)
        
        embed = nextcord.Embed(title=f"📢 Wager: {event_data['title']}", color=nextcord.Color.green())
        if event_data['description']:
            embed.description = event_data['description']
        embed.add_field(name="Status", value="Open for Betting", inline=False)
        embed.set_footer(text=f"Event ID: {event_data['event_id']}")

        for i, outcome_row in enumerate(outcomes):
            embed.add_field(name=f"Outcome {i+1}", value=outcome_row['outcome_text'], inline=True)
        
        # Create and send the BettingEventView for the selected wager
        # Note: BettingEventView has timeout=None, which is fine for ephemeral messages too.
        # It means it won't be auto-removed by nextcord after a timeout, but will vanish when Discord cleans up ephemeral messages.
        individual_wager_view = BettingEventView(
            event_id=event_data['event_id'],
            outcomes=outcomes, # Pass the list of outcome dicts/Rows
            cog_instance=self.cog,
            event_creator_id=event_data['creator_user_id']
        )
        await interaction.followup.send(embed=embed, view=individual_wager_view, ephemeral=True)

class ConfirmAdminFinalizeView(AdminSelectOutcomeView): # Inherits from AdminSelectOutcomeView
    def __init__(self, event_id: int, outcomes: list, cog_instance, admin_id: int, warning_message: str):
        super().__init__(event_id, outcomes, cog_instance, admin_id, prompt_message=warning_message) # Pass up prompt_message

class ActiveWagersListView(View):
    def __init__(self, active_events: list, cog_instance):
        super().__init__(timeout=180) # View will timeout after 3 minutes
        self.cog = cog_instance

        if not active_events:
            # Optionally, add a disabled button or a label indicating no active events
            # For now, if list is empty, the calling command should handle it.
            pass
        else:
            for event in active_events:
                # Max 25 components per view. If more, pagination would be needed.
                self.add_item(SelectWagerButton(event_id=event['event_id'], 
                                                event_title=event['title'], 
                                                cog_instance=self.cog))


class BettingCog(commands.Cog, CogLogMixin, name="BettingEvents"):  # Renamed for clarity
    def __init__(self, bot):
        self.bot = bot
        self.create_tables()
        self.bot.loop.create_task(self.add_persistent_views())


    async def add_persistent_views(self):
        await self.bot.wait_until_ready()
        async with self.bot.pg_pool.acquire() as conn:
            events_to_reactivate = await conn.fetch(
                f'''
                SELECT event_id, creator_user_id FROM "{_WG}".betting_events
                WHERE status IN ('open', 'closed_for_betting', 'pending_finalization') AND message_id IS NOT NULL
                '''
            )
            for event_row in events_to_reactivate:
                outcomes = await conn.fetch(
                    f'SELECT outcome_id, outcome_text FROM "{_WG}".event_outcomes WHERE event_id = $1',
                    event_row["event_id"],
                )
                if outcomes:
                    view = BettingEventView(
                        event_row["event_id"],
                        outcomes,
                        self,
                        event_row["creator_user_id"],
                    )
                    self.bot.add_view(view, message_id=None)
        self.cog_print("Attempted to re-add persistent views for betting events.")

    def create_tables(self):
        return

    @nextcord.slash_command(name="wager", description="Manage betting events.",guild_ids=[GUILD_ID]) 
    async def event_parent_cmd(self, interaction: Interaction):
        pass # This will just group subcommands

    @event_parent_cmd.subcommand(name="create", description="Create a new wager.")
    async def event_create(
        self,
        interaction: Interaction,
        title: str = SlashOption(description="Title of the event.", required=True),
        outcomes_str: str = SlashOption(description="Possible outcomes, separated by semicolons (e.g., Outcome A;Outcome B)", required=True),
        description: str = SlashOption(description="Optional description for the event.", required=False)
    ):
        await interaction.response.defer(ephemeral=True)

        outcome_list = [o.strip() for o in outcomes_str.split(';') if o.strip()]
        if len(outcome_list) < 2:
            await interaction.send("Please provide at least two distinct outcomes.", ephemeral=True)
            return

        try:
            async with self.bot.pg_pool.acquire() as conn:
                async with conn.transaction():
                    event_id = await conn.fetchval(
                        f'''
                        INSERT INTO "{_WG}".betting_events
                            (creator_user_id, title, description, guild_id, channel_id, status)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        RETURNING event_id
                        ''',
                        interaction.user.id,
                        title,
                        description,
                        interaction.guild.id,
                        interaction.channel.id,
                        "open",
                    )

                    db_outcomes = []
                    for outcome_text in outcome_list:
                        oid = await conn.fetchval(
                            f'''
                            INSERT INTO "{_WG}".event_outcomes (event_id, outcome_text) VALUES ($1, $2)
                            RETURNING outcome_id
                            ''',
                            event_id,
                            outcome_text,
                        )
                        db_outcomes.append({"outcome_id": oid, "outcome_text": outcome_text})

            embed = nextcord.Embed(title=f"📢 New Wager: {title}", color=nextcord.Color.blue())
            if description:
                embed.description = description
            embed.add_field(name="Status", value="Open for Betting", inline=False)
            embed.set_footer(text=f"Event ID: {event_id} | Created by: {interaction.user.display_name}")

            for i, outcome_t in enumerate(outcome_list):
                embed.add_field(name=f"Outcome {i+1}", value=outcome_t, inline=True)

            view = BettingEventView(event_id, db_outcomes, self, interaction.user.id)

            event_message = await interaction.channel.send(embed=embed, view=view)

            async with self.bot.pg_pool.acquire() as conn:
                await conn.execute(
                    f'''
                    UPDATE "{_WG}".betting_events SET message_id = $1, channel_id = $2 WHERE event_id = $3
                    ''',
                    event_message.id,
                    interaction.channel.id,
                    event_id,
                )

            await interaction.send(f"Betting event '{title}' (ID: {event_id}) created successfully!", ephemeral=True)

        except asyncpg.PostgresError as e:
            await interaction.send(f"Database error creating event: {e}", ephemeral=True)

    @event_parent_cmd.subcommand(name="list", description="List all active wagers you can bet on.")
    async def event_list_active(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        async with self.bot.pg_pool.acquire() as conn:
            active_events_data = await conn.fetch(
                f'''
                SELECT event_id, title FROM "{_WG}".betting_events WHERE status = 'open' ORDER BY created_at DESC
                '''
            )

        if not active_events_data:
            await interaction.followup.send("There are no active wagers at the moment.", ephemeral=True)
            return

        # Create an embed to list the wagers
        embed = nextcord.Embed(title="Active Wagers", color=nextcord.Color.blurple())
        
        if len(active_events_data) > 20: # Discord button limits
            embed.description = "Showing the latest 20 active wagers. More may exist."
            active_events_data = active_events_data[:20] # Limit to avoid hitting component limits

        description_lines = []
        for i, event_row in enumerate(active_events_data):
            description_lines.append(f"**{i+1}. {event_row['title']}** (ID: {event_row['event_id']})")
        
        if description_lines:
            embed.description = "\n".join(description_lines) + "\n\nSelect a wager below to view details and place a bet:"
        else: # Should be caught by the initial check, but as a fallback
            embed.description = "No active wagers found to list with buttons."


        view = ActiveWagersListView(active_events_data, self)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        

    @event_parent_cmd.subcommand(name="finalize", description="[Admin] List wagers needing finalization.")
    async def event_finalize(self, interaction: Interaction):
        if interaction.user.id not in admin_user_ids:
            await interaction.send("You do not have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        async with self.bot.pg_pool.acquire() as conn:
            pending_events = await conn.fetch(
                f'''
                SELECT event_id, title, status FROM "{_WG}".betting_events
                WHERE status IN ('closed_for_betting', 'pending_finalization') ORDER BY created_at ASC
                '''
            )

        if not pending_events:
            await interaction.followup.send("No wagers are currently pending finalization.", ephemeral=True)
            return

        embed = nextcord.Embed(title="Wagers Pending Finalization", color=nextcord.Color.orange())
        
        description_lines = []
        for event_row in pending_events:
            description_lines.append(f"ID: {event_row['event_id']} - **{event_row['title']}** (Status: {event_row['status'].replace('_', ' ').capitalize()})")

        if not description_lines: # Should be caught by pending_events check
            await interaction.followup.send("No wagers found pending finalization.", ephemeral=True)
            return

        embed.description = "\n".join(description_lines[:15]) # Show up to 15 in description
        if len(pending_events) > 15:
            embed.set_footer(text=f"Showing {len(description_lines[:15])} of {len(pending_events)} pending wagers.")
        
        view = PendingFinalizationView(pending_events, self)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


    @event_parent_cmd.subcommand(name="history", description="View history of recently finalized wagers.")
    async def event_history(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        async with self.bot.pg_pool.acquire() as conn:
            finalized_events = await conn.fetch(
                f'''
                SELECT be.event_id, be.title, be.resolved_by_admin_id, eo.outcome_text AS winning_outcome, be.created_at
                FROM "{_WG}".betting_events be
                LEFT JOIN "{_WG}".event_outcomes eo ON be.winning_outcome_id = eo.outcome_id
                WHERE be.status = 'finalized'
                ORDER BY be.created_at DESC
                LIMIT 10
                '''
            )

        if not finalized_events:
            await interaction.followup.send("No finalized wagers found in the recent history.", ephemeral=True)
            return

        embed = nextcord.Embed(title="Recent Wager History", color=nextcord.Color.dark_grey())
        
        history_lines = []
        for event_row in finalized_events:
            admin_mention = f"<@{event_row['resolved_by_admin_id']}>" if event_row['resolved_by_admin_id'] else "N/A"
            winning_text = event_row["winning_outcome"] if event_row["winning_outcome"] else "N/A (or no winning bets)"
            ts = _dt_ts(event_row["created_at"])
            history_lines.append(
                f"**{event_row['title']}** (ID: {event_row['event_id']})\n"
                f"  Winner: {winning_text}\n"
                f"  Finalized by: {admin_mention} on <t:{ts}:D>"
            )
        
        embed.description = "\n\n".join(history_lines)
        embed.set_footer(text="Showing up to 10 most recent finalized wagers.")
        await interaction.followup.send(embed=embed, ephemeral=True)


    @event_parent_cmd.subcommand(name="my_bets", description="View your personal betting history (active and past).")
    async def event_my_bets(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        async with self.bot.pg_pool.acquire() as conn:
            my_bets_data = await conn.fetch(
                f'''
                SELECT
                    ub.bet_id, ub.amount, ub.placed_at,
                    be.event_id, be.title AS event_title, be.status AS event_status,
                    eo_bet.outcome_text AS bet_on_outcome,
                    eo_win.outcome_text AS winning_outcome_text
                FROM "{_WG}".user_bets ub
                JOIN "{_WG}".betting_events be ON ub.event_id = be.event_id
                JOIN "{_WG}".event_outcomes eo_bet ON ub.outcome_id = eo_bet.outcome_id
                LEFT JOIN "{_WG}".event_outcomes eo_win ON be.winning_outcome_id = eo_win.outcome_id
                WHERE ub.user_id = $1
                ORDER BY ub.placed_at DESC
                LIMIT 15
                ''',
                user_id,
            )

        if not my_bets_data:
            await interaction.followup.send("You haven't placed any bets yet, or your betting history is empty.", ephemeral=True)
            return

        embed = nextcord.Embed(title=f"{interaction.user.display_name}'s Betting Ledger", color=interaction.user.color)
        
        bet_lines = []
        for bet in my_bets_data:
            placed_ts = _dt_ts(bet["placed_at"])
            line = (
                f"**{bet['event_title']}** (ID: {bet['event_id']}) - Bet ID: {bet['bet_id']}\n"
                f"  Amount: {bet['amount']} on '{bet['bet_on_outcome']}'\n"
                f"  Placed: <t:{placed_ts}:R>\n"
                f"  Status: {bet['event_status'].replace('_', ' ').capitalize()}"
            )
            if bet['event_status'] == 'finalized':
                if bet['bet_on_outcome'] == bet['winning_outcome_text']:
                    # To show actual winnings, you'd need to re-calculate or store payout per user_bet
                    line += " - 🎉 **Won!**" 
                else:
                    line += f" - Lost (Winner: {bet['winning_outcome_text'] or 'N/A'})"
            bet_lines.append(line)

        embed.description = "\n\n".join(bet_lines)
        embed.set_footer(text="Showing up to 15 of your most recent bets. Payout details for wins are simplified here.")
        await interaction.followup.send(embed=embed, ephemeral=True)


    @event_parent_cmd.subcommand(name="delete", description="[Admin] Delete a wager entirely.")
    async def event_delete(
        self,
        interaction: Interaction,
        event_id: int = SlashOption(description="The ID of the wager to delete.", required=True)
    ):
        if interaction.user.id not in admin_user_ids:
            await interaction.send("You do not have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            async with self.bot.pg_pool.acquire() as conn:
                event_info = await conn.fetchrow(
                    f'''
                    SELECT message_id, channel_id, guild_id, title FROM "{_WG}".betting_events WHERE event_id = $1
                    ''',
                    event_id,
                )

            if not event_info:
                await interaction.followup.send(f"Wager with ID {event_id} not found.", ephemeral=True)
                return

            async with self.bot.pg_pool.acquire() as conn:
                await conn.execute(f'DELETE FROM "{_WG}".betting_events WHERE event_id = $1', event_id)

            deleted_message_info = ""
            if event_info["message_id"] and event_info["channel_id"] and event_info["guild_id"]:
                try:
                    guild = self.bot.get_guild(event_info["guild_id"])
                    if guild:
                        channel = guild.get_channel(event_info["channel_id"])
                        if channel:
                            message = await channel.fetch_message(event_info["message_id"])
                            await message.delete()
                            deleted_message_info = " The original event message was also deleted."
                except nextcord.NotFound:
                    deleted_message_info = " The original event message could not be found or was already deleted."
                except nextcord.Forbidden:
                    deleted_message_info = " I lack permissions to delete the original event message."
                except Exception as e:
                    deleted_message_info = f" An error occurred while trying to delete the event message: {e}"

            await interaction.followup.send(
                f"Successfully deleted wager '{event_info['title']}' (ID: {event_id}) and all associated bets/outcomes.{deleted_message_info}",
                ephemeral=True,
            )

        except asyncpg.PostgresError as e:
            await interaction.followup.send(f"Database error deleting event: {e}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"An unexpected error occurred: {e}", ephemeral=True)


    async def update_event_message(self, event_id: int, new_status_display: str = None):
        async with self.bot.pg_pool.acquire() as conn:
            event_data = await conn.fetchrow(
                f'''
                SELECT message_id, channel_id, title, description, status, guild_id
                FROM "{_WG}".betting_events WHERE event_id = $1
                ''',
                event_id,
            )
            if not event_data or not event_data["message_id"] or not event_data["channel_id"]:
                self.cog_print(f"Event {event_id} missing message_id or channel_id for update.")
                return

            outcomes = await conn.fetch(
                f'SELECT outcome_text FROM "{_WG}".event_outcomes WHERE event_id = $1',
                event_id,
            )

        try:
            guild = self.bot.get_guild(event_data["guild_id"])
            if not guild:
                self.cog_print(f"Guild {event_data['guild_id']} not found for event {event_id}.")
                return

            channel = guild.get_channel(event_data["channel_id"])
            if not channel:
                self.cog_print(f"Channel {event_data['channel_id']} not found in guild {guild.id} for event {event_id}.")
                return

            target_message = await channel.fetch_message(event_data["message_id"])

            embed = (
                target_message.embeds[0]
                if target_message.embeds
                else nextcord.Embed(title=event_data["title"])
            )
            embed.clear_fields()

            current_status_display = (
                new_status_display
                if new_status_display
                else event_data["status"].replace("_", " ").capitalize()
            )
            embed.add_field(name="Status", value=current_status_display, inline=False)

            for i, outcome_row in enumerate(outcomes):
                embed.add_field(
                    name=f"Outcome {i+1}",
                    value=outcome_row["outcome_text"],
                    inline=True,
                )

            await target_message.edit(embed=embed)

        except nextcord.NotFound:
            self.cog_print(f"Message {event_data['message_id']} for event {event_id} not found for update.")
        except Exception as e:
            self.cog_print(f"Error updating event message for {event_id}: {e}")


    async def finalize_event_logic(self, interaction: Interaction, event_id: int, winning_outcome_id: int, admin_id: int):
        """Handles the logic after an admin has confirmed the winning outcome."""
        try:
            async with self.bot.pg_pool.acquire() as conn:
                await conn.execute(
                    f'''
                    UPDATE "{_WG}".betting_events
                    SET status = 'finalized', winning_outcome_id = $1, resolved_by_admin_id = $2
                    WHERE event_id = $3
                    ''',
                    winning_outcome_id,
                    admin_id,
                    event_id,
                )

                all_bets = await conn.fetch(
                    f'SELECT user_id, outcome_id, amount FROM "{_WG}".user_bets WHERE event_id = $1',
                    event_id,
                )

            if not all_bets:
                await interaction.followup.send("Event finalized. No bets were placed.", ephemeral=True)
                await self.update_event_message(event_id, new_status_display="Finalized - No Bets")
                return

            total_pot = sum(bet["amount"] for bet in all_bets)
            winning_bets = [bet for bet in all_bets if bet["outcome_id"] == winning_outcome_id]

            if not winning_bets:
                await interaction.followup.send(
                    f"Event finalized. Winning Outcome ID: {winning_outcome_id}. No one bet on the winning outcome. Pot of {total_pot} sent to the Treasury.",
                    ephemeral=True,
                )
                await self.update_event_message(
                    event_id,
                    new_status_display=f"Finalized - No Winners (Pot: {total_pot})",
                )
                return

            total_bet_on_winning_outcome = sum(bet["amount"] for bet in winning_bets)

            economy_cog = self.bot.get_cog("Economy")
            if not economy_cog:
                await interaction.followup.send("Economy cog not found. Cannot process payouts.", ephemeral=True)
                return

            payout_summary = []
            for winner_bet in winning_bets:
                payout = round((winner_bet["amount"] / total_bet_on_winning_outcome) * total_pot)
                await economy_cog.update_balance(winner_bet["user_id"], payout)
                payout_summary.append(
                    f"<@{winner_bet['user_id']}> won {payout} (staked {winner_bet['amount']})"
                )

            async with self.bot.pg_pool.acquire() as conn:
                winning_outcome_text_row = await conn.fetchrow(
                    f'SELECT outcome_text FROM "{_WG}".event_outcomes WHERE outcome_id = $1',
                    winning_outcome_id,
                )
            winning_outcome_text = (
                winning_outcome_text_row["outcome_text"] if winning_outcome_text_row else "N/A"
            )

            summary_message = (
                f"Event ID {event_id} finalized!\nWinning Outcome: **{winning_outcome_text}**\nTotal Pot: {total_pot}\n\nPayouts:\n"
                + "\n".join(payout_summary)
            )
            await interaction.followup.send(summary_message, ephemeral=False)

            await self.update_event_message(
                event_id,
                new_status_display=f"Finalized - Won: {winning_outcome_text}",
            )

        except asyncpg.PostgresError as e:
            await interaction.followup.send(f"Database error during finalization: {e}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"An unexpected error occurred during finalization: {e}", ephemeral=True)


def setup(bot):
    bot.add_cog(BettingCog(bot))
    boot_print("WagerCog has been loaded with new event-based functionality.")