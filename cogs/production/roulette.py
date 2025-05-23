# roulette.py

import nextcord
from nextcord.ext import commands
import random
import asyncio # Needed for sleep

from server_configs.config import GUILD_ID
# --- Roulette Wheel Configuration (European Style) ---
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
BLACK_NUMBERS = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}
ZERO = 0
EUROPEAN_WHEEL_NUMBERS = list(range(37)) # Numbers 0 to 36

NUM_EMOJIS = {
    'red': '🔴',
    'black': '⚫',
    'green': '🟢' # For Zero
}
SPIN_EMOJI = '🎰' # Or '💫'
# ----------------------------------------------------


# Modal for Number Input
class NumberBetModal(nextcord.ui.Modal):
    def __init__(self, parent_view): # Pass the view that will handle the result
        super().__init__(title="Place Number Bet (0-36)")
        self.parent_view = parent_view

        self.number_input = nextcord.ui.TextInput(
            label="Enter Number (0-36)",
            min_length=1,
            max_length=2,
            required=True,
            placeholder="e.g., 17"
        )
        self.add_item(self.number_input)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            num_bet = int(self.number_input.value)
            if 0 <= num_bet <= 36:
                # Call a method on the parent view to handle the confirmed bet
                await self.parent_view.confirm_bet(interaction, "Number", num_bet)
            else:
                await interaction.response.send_message("Invalid number. Must be between 0 and 36.", ephemeral=True)
                # Keep modal or let user try again? Sending ephemeral message is simplest.
        except ValueError:
            await interaction.response.send_message("Invalid input. Please enter a whole number.", ephemeral=True)
        except Exception as e:
            print(f"Error in modal callback: {e}")
            await interaction.response.send_message("An error occurred processing your bet.", ephemeral=True)


# View for Confirmation
class RouletteConfirmView(nextcord.ui.View):
    def __init__(self, cog, original_interaction, user_id, amount, bet_type, bet_value, bet_description):
        super().__init__(timeout=120.0) # Shorter timeout for confirmation
        self.cog = cog
        self.original_interaction = original_interaction # To edit the original message
        self.user_id = user_id
        self.amount = amount
        self.bet_type = bet_type
        self.bet_value = bet_value
        self.bet_description = bet_description
        self.already_spun = False

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your roulette game!", ephemeral=True)
            return False
        if self.already_spun:
             await interaction.response.send_message("The wheel has already been spun.", ephemeral=True)
             return False
        return True

    @nextcord.ui.button(label="Spin!", style=nextcord.ButtonStyle.green)
    async def spin_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.already_spun = True
        # Disable buttons
        for item in self.children:
            item.disabled = True
        # Acknowledge interaction and show "Spinning..."
        spinning_embed = nextcord.Embed(
            title="Roulette - Spinning...",
            description=f"{SPIN_EMOJI} Placing bet on {self.bet_description} for {self.amount} 🪙...",
            color=nextcord.Color.blue()
        )
        await interaction.response.edit_message(embed=spinning_embed, view=self)

        # --- Perform the actual spin logic ---
        # Moved core logic to a separate method in the cog for clarity
        await self.cog._perform_spin(
            interaction=interaction, # Pass button interaction for followup
            user_id=self.user_id,
            amount=self.amount,
            bet_type=self.bet_type,
            bet_value=self.bet_value,
            bet_description=self.bet_description
        )
        # _perform_spin will handle the final result edit
        self.stop()


    @nextcord.ui.button(label="Cancel Bet", style=nextcord.ButtonStyle.red)
    async def cancel_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.already_spun = True # Prevent further action
        for item in self.children:
            item.disabled = True
        cancel_embed = nextcord.Embed(
            title="Roulette - Bet Canceled",
            description=f"Your bet on {self.bet_description} for {self.amount} 🪙 was canceled.",
            color=nextcord.Color.greyple()
        )
        await interaction.response.edit_message(embed=cancel_embed, view=None) # Remove view
        self.stop()

    async def on_timeout(self):
         if not self.already_spun:
             timeout_embed = nextcord.Embed(
                title="Roulette - Timed Out",
                description=f"Your bet confirmation timed out.",
                color=nextcord.Color.dark_grey()
             )
             try:
                 # Use original_interaction context for editing on timeout
                 await self.original_interaction.edit_original_message(embed=timeout_embed, view=None)
             except nextcord.NotFound:
                 pass # Message might have been deleted


# Main View for placing bets
class RouletteBetView(nextcord.ui.View):
    def __init__(self, cog, original_interaction, user_id, amount):
        super().__init__(timeout=180.0)
        self.cog = cog
        self.original_interaction = original_interaction # Interaction from /roulette command
        self.user_id = user_id
        self.amount = amount
        self.bet_type = None
        self.bet_value = None
        self.bet_description = None

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your roulette game!", ephemeral=True)
            return False
        # Add check if bet already placed? No, this view is replaced.
        return True

    async def confirm_bet(self, interaction: nextcord.Interaction, bet_type, bet_value):
        """Called by Modals or other views to finalize bet choice and show confirmation."""
        self.bet_type = bet_type
        self.bet_value = bet_value

        # Generate description based on finalized bet
        if bet_type == "Number":
            self.bet_description = f"Number {bet_value}"
        elif bet_type == "Color":
            color_emoji = NUM_EMOJIS.get(bet_value, '')
            self.bet_description = f"Color {bet_value.capitalize()} {color_emoji}"
        elif bet_type == "Parity":
             self.bet_description = f"Parity {bet_value.capitalize()}"

        confirm_embed = nextcord.Embed(
            title="Roulette - Confirm Bet",
            description=f"You are betting **{self.amount} 🪙** on **{self.bet_description}**.",
            color=nextcord.Color.gold()
        )
        confirm_embed.set_footer(text="Click Spin! to start or Cancel Bet.")

        confirm_view = RouletteConfirmView(
            self.cog, self.original_interaction, self.user_id, self.amount,
            self.bet_type, self.bet_value, self.bet_description
        )

        # Use the interaction from the button/modal to edit the message
        await interaction.response.edit_message(embed=confirm_embed, view=confirm_view)
        self.stop() # Stop this view as it's being replaced

    # --- Button Callbacks for Bet Types ---

    @nextcord.ui.button(label="Number Bet", style=nextcord.ButtonStyle.primary, row=0)
    async def number_bet_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        # Launch the modal
        modal = NumberBetModal(parent_view=self)
        await interaction.response.send_modal(modal)
        # Modal callback will call self.confirm_bet

    @nextcord.ui.button(label="Red", emoji="🔴", style=nextcord.ButtonStyle.danger, row=1)
    async def red_bet_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.confirm_bet(interaction, "Color", "red")

    @nextcord.ui.button(label="Black", emoji="⚫", style=nextcord.ButtonStyle.secondary, row=1)
    async def black_bet_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
         await self.confirm_bet(interaction, "Color", "black")

    @nextcord.ui.button(label="Odd", style=nextcord.ButtonStyle.blurple, row=2)
    async def odd_bet_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
         await self.confirm_bet(interaction, "Parity", "odd")

    @nextcord.ui.button(label="Even", style=nextcord.ButtonStyle.blurple, row=2)
    async def even_bet_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
         await self.confirm_bet(interaction, "Parity", "even")

    async def on_timeout(self):
         # Check if a bet was already confirmed (view replaced)
         # If self.is_finished() is False, it means timeout happened on *this* view
         if not self.is_finished():
             timeout_embed = nextcord.Embed(
                 title="Roulette - Timed Out",
                 description=f"You did not place your bet in time.",
                 color=nextcord.Color.dark_grey()
             )
             try:
                 await self.original_interaction.edit_original_message(embed=timeout_embed, view=None)
             except nextcord.NotFound:
                 pass # Message might have been deleted

# --- Main Cog ---
class Roulette(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def get_economy_cog(self):
        economy_cog = self.bot.get_cog("Economy")
        if economy_cog is None:
            raise Exception("Economy cog not found.")
        return economy_cog

    async def _perform_spin(self, interaction: nextcord.Interaction, user_id: int, amount: int, bet_type: str, bet_value, bet_description: str):
        """Handles the core roulette spin logic and result display. Called by confirm view."""
        try:
            economy_cog = self.get_economy_cog()
        except Exception as e:
            error_embed = nextcord.Embed(title="Error", description=str(e), color=nextcord.Color.red())
            # Use followup as the interaction was deferred/responded to by the button
            await interaction.followup.edit_message('@original', embed=error_embed, view=None)
            return

        # --- Balance Check Again (important before deduction) ---
        balance = economy_cog.get_user_balance(user_id)
        if balance < amount:
             error_embed = nextcord.Embed(title="Roulette Error", description="Insufficient funds found just before spin. Bet canceled.", color=nextcord.Color.red())
             await interaction.followup.edit_message('@original', embed=error_embed, view=None)
             return # Do not proceed with deduction/spin
        # --- End Balance Check ---

        # --- Deduct Wager ---
        economy_cog.update_balance(user_id, -amount)
        # --------------------

        # --- Visual Delay ---
        await asyncio.sleep(3) # Simple delay to simulate spinning
        # --------------------

        # --- Spin and Determine Result --- (Same logic as before)
        winning_number = random.choice(EUROPEAN_WHEEL_NUMBERS)
        winning_color = 'green'
        winning_parity = None
        if winning_number in RED_NUMBERS: winning_color = 'red'
        elif winning_number in BLACK_NUMBERS: winning_color = 'black'
        if winning_number != 0: winning_parity = "even" if winning_number % 2 == 0 else "odd"
        winning_num_emoji = NUM_EMOJIS.get(winning_color, '')
        # ---------------------------------

        # --- Check Win and Calculate Payout --- (Same logic as before)
        is_win = False
        payout = 0
        profit = -amount
        if bet_type == "Number" and bet_value == winning_number: is_win = True; payout = amount * 36
        elif bet_type == "Color" and bet_value == winning_color: is_win = True; payout = amount * 2
        elif bet_type == "Parity" and bet_value == winning_parity: is_win = True; payout = amount * 2
        if is_win:
            profit = payout - amount
            economy_cog.update_balance(user_id, payout)
        # -------------------------------------------

        # --- Create Final Result Embed ---
        result_color = nextcord.Color.green() if is_win else nextcord.Color.red()
        result_text = "You Won!" if is_win else "You Lost!"

        final_embed = nextcord.Embed(
            title="Roulette Spin Result",
            description=(
                f"The ball landed on: **{winning_number} {winning_num_emoji}** "
                f"({winning_color.capitalize()}{f', {winning_parity.capitalize()}' if winning_parity else ''})"
            ),
            color=result_color
        )
        final_embed.add_field(name="Your Bet", value=f"{bet_description}\nWager: {amount} 🪙", inline=True)
        final_embed.add_field(name="Result", value=f"**{result_text}**\nProfit: {profit:+} 🪙", inline=True)
        new_balance = economy_cog.get_user_balance(user_id)
        final_embed.set_footer(text=f"Spin finished. Your new balance: {new_balance} 🪙")
        # ---------------------------

        # --- Edit Original Message with Final Result ---
        # Use followup.edit_message since we responded to the button interaction earlier
        try:
            await interaction.followup.edit_message('@original', embed=final_embed, view=None) # Remove view after spin
        except nextcord.NotFound:
            print("Error: Original message not found when trying to display final roulette result.")
        except Exception as e:
            print(f"Error editing final roulette result: {e}")


    @nextcord.slash_command(name="roulette", description="Play an interactive game of European roulette.",guild_ids=[GUILD_ID])
    async def roulette_command(
        self,
        interaction: nextcord.Interaction,
        amount: int = nextcord.SlashOption(
            description="The amount of coins you want to wager."
        )
    ):
        """Starts the interactive roulette game."""
        try:
            economy_cog = self.get_economy_cog()
        except Exception as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)
            return

        user_id = interaction.user.id

        # --- Input Validation ---
        if amount <= 0:
            await interaction.response.send_message("Wager amount must be positive.", ephemeral=True)
            return
        balance = economy_cog.get_user_balance(user_id)
        if balance < amount:
            await interaction.response.send_message(f"Insufficient funds. Your balance is {balance} coins.", ephemeral=True)
            return
        # --- End Validation ---

        # --- Initial Response: Send Bet Placement View ---
        initial_embed = nextcord.Embed(
            title="Roulette - Place Your Bet",
            description=f"Please select your bet type for **{amount} 🪙**.",
            color=nextcord.Color.default()
        )
        view = RouletteBetView(self, interaction, user_id, amount)
        await interaction.response.send_message(embed=initial_embed, view=view)
        # The view will handle the rest of the interaction flow


# Standard Cog Setup Function
async def setup(bot: commands.Bot):
    """Loads the Roulette cog."""
    bot.add_cog(Roulette(bot))
    print("Interactive RouletteCog loaded.")