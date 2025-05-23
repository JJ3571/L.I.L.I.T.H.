import nextcord
from nextcord.ext import commands
import random
import asyncio

from server_configs.config import GUILD_ID
from server_configs.cogs_config import heads_emoji_id, tails_emoji_id

class Gambling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Ensure Economy cog is loaded during bot setup, checking here is good practice
        # Deferring the actual get_cog call to command runtime is often more robust
        # in case cogs load in different orders.

    def get_economy_cog(self):
        """Safely retrieves the Economy cog."""
        economy_cog = self.bot.get_cog("Economy")
        if economy_cog is None:
            raise Exception("Economy cog not found. Ensure it is loaded.")
        return economy_cog

    def deal_card(self, deck):
        """Deals a single card from the deck."""
        if not deck:
             raise ValueError("Deck is empty!") # Added safety check
        card = random.choice(deck)
        deck.remove(card)
        return card

    def calculate_hand_value(self, hand):
        """Calculates the value of a Blackjack hand."""
        value = 0
        aces = 0
        for card in hand:
            rank = card[:-1] # Get rank (e.g., 'A', 'K', '10', '7')
            if rank.isdigit():
                value += int(rank)
            elif rank in ['J', 'Q', 'K']:
                value += 10
            elif rank == 'A':
                aces += 1
                value += 11 # Add 11 for Ace initially

        # Adjust for Aces if value is over 21
        while value > 21 and aces > 0:
            value -= 10
            aces -= 1
        return value

    @nextcord.slash_command(name="cointoss", description="Toss a coin and potentially double your wager", guild_ids=[GUILD_ID])
    async def cointoss_command(self, interaction: nextcord.Interaction, choice: str = nextcord.SlashOption(choices=["heads", "tails"], description="Heads or tails?"), amount: int = nextcord.SlashOption(description="Amount to bet.")):
        """Handles the coin toss game."""
        try:
            economy_cog = self.get_economy_cog()
        except Exception as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        user_id = interaction.user.id

        if amount <= 0:
            await interaction.response.send_message("Amount must be positive.", ephemeral=True)
            return

        balance = await economy_cog.get_user_balance(user_id)
        if balance < amount:
            await interaction.response.send_message("Insufficient funds.", ephemeral=True)
            return

        # --- Corrected Coin Toss Balance Logic ---
        # Deduct the wager upfront
        await economy_cog.update_balance(user_id, -amount)
        # -----------------------------------------

        coin_flip = random.choice(["heads", "tails"])

        heads_emoji = self.bot.get_emoji(heads_emoji_id)
        tails_emoji = self.bot.get_emoji(tails_emoji_id)

        # Use default text if emojis fail to load
        heads_str = str(heads_emoji) if heads_emoji else "Heads"
        tails_str = str(tails_emoji) if tails_emoji else "Tails"
        result_str = heads_str if coin_flip == 'heads' else tails_str

        embed = nextcord.Embed(title=f"It was: {coin_flip.capitalize()}",)
        # Add image URLs if desired (ensure they are valid)
        if coin_flip == "heads":
            embed.set_image(url="https://cdn.discordapp.com/emojis/808471572335689748.webp?size=240")
        else:
            embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/808471587233595465.webp?size=240")
            
        if choice == coin_flip:
            # --- Corrected Coin Toss Win ---
            payout = amount * 2 # Return wager + winnings
            profit = amount
            await economy_cog.update_balance(user_id, payout) # Add back the winnings + original wager
            # -------------------------------
            embed.add_field(name=f"You won {profit} 🪙!", value="")
            embed.color = nextcord.Color.green()
        else:
            # --- Corrected Coin Toss Loss ---
            # Loss is handled by the upfront deduction, no further balance change needed.
            profit = -amount
            # --------------------------------
            embed.description = f"You lost {amount} 🪙!"
            embed.color = nextcord.Color.red()

        await interaction.response.send_message(embed=embed)

    @nextcord.slash_command(name="blackjack", description="Play blackjack with a wager.",guild_ids=[GUILD_ID])
    async def blackjack_command(self, interaction: nextcord.Interaction, amount: int = nextcord.SlashOption(description="Amount to wager.")):
        """Starts a game of Blackjack."""
        try:
            economy_cog = self.get_economy_cog()
        except Exception as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        user_id = interaction.user.id

        if amount <= 0:
            await interaction.response.send_message("Amount must be positive.", ephemeral=True)
            return

        balance = await economy_cog.get_user_balance(user_id)
        if balance < amount:
            await interaction.response.send_message("Insufficient funds.", ephemeral=True)
            return

        # --- FIX: Deduct the initial wager upfront ---
        await economy_cog.update_balance(user_id, -amount)
        current_balance = await economy_cog.get_user_balance(user_id) # Get updated balance for double down check later
        # ---------------------------------------------

        # Create the deck and deal cards
        deck = [f"{rank}{suit}" for suit in ['♠', '♥', '♦', '♣'] for rank in ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']]
        random.shuffle(deck)

        player_hand = []
        dealer_hand = []
        try:
             player_hand = [self.deal_card(deck), self.deal_card(deck)]
             dealer_hand = [self.deal_card(deck), self.deal_card(deck)]
        except ValueError:
             await interaction.response.send_message("Error dealing cards. The deck might be empty (this shouldn't happen with a single deck).", ephemeral=True)
             await economy_cog.update_balance(user_id, amount) # Refund wager if deal fails
             return

        player_value = self.calculate_hand_value(player_hand)
        dealer_value = self.calculate_hand_value(dealer_hand) # Calculate initial dealer value for Blackjack check

        # --- FIX: Check for Immediate Blackjacks ---
        player_blackjack = player_value == 21 and len(player_hand) == 2
        dealer_blackjack = dealer_value == 21 and len(dealer_hand) == 2

        view = BlackjackView(self, economy_cog, interaction, deck, player_hand, dealer_hand, amount, current_balance) # Pass current balance

        if player_blackjack or dealer_blackjack:
            await view.handle_blackjack_outcome(interaction, player_blackjack, dealer_blackjack)
            return # Game ends immediately
        # -----------------------------------------

        # Create the initial embed
        embed = nextcord.Embed(
            title="Blackjack",
            description=(
                f"Your hand: {', '.join(player_hand)} `({player_value})`\n"
                f"Dealer's showing: {dealer_hand[0]}, `?`\n\n"
                f"Wager: {amount} 🪙"
            ),
            color=nextcord.Color.gold()
        )
        embed.set_footer(text="Use the buttons below to play.")

        await interaction.response.send_message(embed=embed, view=view)


class BlackjackView(nextcord.ui.View):
    def __init__(self, cog: Gambling, economy_cog, interaction: nextcord.Interaction, deck: list, player_hand: list, dealer_hand: list, original_wager: int, initial_balance_after_bet: int):
        super().__init__(timeout=180.0) # Add a timeout
        self.cog = cog
        self.economy_cog = economy_cog
        self.interaction = interaction # The original interaction that started the game
        self.deck = deck
        self.player_hand = player_hand
        self.dealer_hand = dealer_hand
        self.original_wager = original_wager
        self.current_wager = original_wager # The amount currently staked (can increase with double down)
        self.initial_balance_after_bet = initial_balance_after_bet # Store balance *after* initial bet was placed
        self.doubled_down = False
        self.game_over = False

        # Disable double down if player doesn't have enough funds *initially*
        # (This check is slightly simplified, a dedicated get_balance call is safer)
        if self.initial_balance_after_bet < self.original_wager:
             # Find the button by custom_id or iterate and check label
             for item in self.children:
                 if isinstance(item, nextcord.ui.Button) and item.label == "Double Down":
                     item.disabled = True
                     break

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        """Ensures only the player who started the game can interact."""
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message("This is not your game!", ephemeral=True)
            return False
        if self.game_over:
             await interaction.response.send_message("The game has already ended.", ephemeral=True)
             return False
        return True

    async def disable_buttons(self, disable_all=False):
        """Disables buttons, typically after an action or game end."""
        for item in self.children:
            if isinstance(item, nextcord.ui.Button):
                 if disable_all:
                      item.disabled = True
                 # Disable Double Down after first action (hit/stand) or if used
                 elif item.label == "Double Down":
                      item.disabled = True
        # Keep Hit/Stand active unless disable_all=True

    @nextcord.ui.button(label="Hit", style=nextcord.ButtonStyle.green)
    async def hit(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        """Player chooses to take another card."""
        # interaction_check is implicitly called

        self.player_hand.append(self.cog.deal_card(self.deck))
        player_value = self.cog.calculate_hand_value(self.player_hand)

        await self.disable_buttons() # Disable Double Down after hitting

        if player_value > 21:
            await self.end_game(interaction, "Player Bust")
        else:
            embed = nextcord.Embed(
                title="Blackjack - Your Turn",
                description=(
                    f"Your hand: {', '.join(self.player_hand)} `({player_value})`\n"
                    f"Dealer's showing: {self.dealer_hand[0]}, `?`\n\n"
                    f"Wager: {self.current_wager} 🪙"
                 ),
                color=nextcord.Color.gold()
            )
            await interaction.response.edit_message(embed=embed, view=self)

    @nextcord.ui.button(label="Stand", style=nextcord.ButtonStyle.blurple)
    async def stand(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        """Player chooses to stand, dealer takes their turn."""
        # interaction_check is implicitly called by the framework before this runs

        # --- FIX: Defer interaction immediately ---
        # Acknowledge the button click within 3 seconds to prevent "Interaction Failed"
        await interaction.response.defer()
        # -----------------------------------------

        # Disable Double Down (and potentially other buttons if needed)
        # This is safe to do after deferring
        await self.disable_buttons()

        # Now call the dealer_turn logic. Edits within dealer_turn will use
        # interaction.followup.edit_message, which is correct after deferring.
        await self.dealer_turn(interaction)

    @nextcord.ui.button(label="Double Down", style=nextcord.ButtonStyle.red)
    async def double_down(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        """Player doubles their wager, takes one card, and stands."""
        # interaction_check is implicitly called

        # --- FIX: Double Down Rule Enforcement ---
        if len(self.player_hand) != 2:
             await interaction.response.send_message("You can only double down on your first two cards.", ephemeral=True)
             return
        # -----------------------------------------

        # --- FIX: Correct Balance Check ---
        # Check if the user has enough for the *additional* wager
        current_balance = await self.economy_cog.get_user_balance(self.interaction.user.id)
        if current_balance < self.original_wager:
            await interaction.response.send_message(
                f"Insufficient funds to double down. You need {self.original_wager} more coins.",
                ephemeral=True
            )
            return
        # -----------------------------------

        # --- FIX: Deduct additional wager and update state ---
        await self.economy_cog.update_balance(self.interaction.user.id, -self.original_wager)
        self.current_wager += self.original_wager # Or self.current_wager *= 2
        self.doubled_down = True
        button.disabled = True # Disable button after use
        # ----------------------------------------------------

        # Deal one card
        self.player_hand.append(self.cog.deal_card(self.deck))
        player_value = self.cog.calculate_hand_value(self.player_hand)

        # Update embed temporarily showing the new card before dealer plays
        embed = nextcord.Embed(
             title="Blackjack - Doubled Down!",
             description=(
                  f"Your hand: {', '.join(self.player_hand)} `({player_value})`\n"
                  f"Dealer's showing: {self.dealer_hand[0]}, `?`\n\n"
                  f"Wager: {self.current_wager} 🪙"
             ),
             color=nextcord.Color.orange() # Indicate doubled down state
         )
        await interaction.response.edit_message(embed=embed, view=self)
        await asyncio.sleep(1) # Optional delay

        # Check for bust immediately after doubling down
        if player_value > 21:
            await self.end_game(interaction, "Player Bust")
        else:
            # Double Down forces a Stand
            await self.dealer_turn(interaction)


    async def dealer_turn(self, interaction: nextcord.Interaction):
            """Handles the dealer's turn logic."""
            player_value = self.cog.calculate_hand_value(self.player_hand)

            # Player already busted check remains the same...
            if player_value > 21:
                if not self.game_over:
                    await self.end_game(interaction, "Player Bust")
                return

            dealer_value = self.cog.calculate_hand_value(self.dealer_hand)

            # --- MODIFICATION: Use followup webhook for editing ---
            # Initial embed showing dealer's full hand
            embed = nextcord.Embed(
                title="Blackjack - Dealer's Turn",
                description=(
                    f"Your hand: {', '.join(self.player_hand)} `({player_value})`\n"
                    f"Dealer's hand: {', '.join(self.dealer_hand)} `({dealer_value})`\n\n"
                    f"Wager: {self.current_wager} 🪙"
                ),
                color=nextcord.Color.blue()
            )
            try:
                # Use followup.edit_message('@original') to edit the initial response message
                await interaction.followup.edit_message('@original', embed=embed, view=self)
            except nextcord.NotFound:
                # Handle case where the original message might have been deleted
                print("Error: Original message not found during dealer turn (initial reveal).")
                await self.end_game(interaction, "Error - Message Deleted") # End game gracefully
                return
            except Exception as e:
                print(f"Error editing message in dealer_turn (initial reveal): {e}")
                # Potentially try to send a new message or end game
                await self.end_game(interaction, "Error - Cannot Edit Message")
                return

            await asyncio.sleep(1.5) # Pause to show dealer hand

            # Dealer hits loop
            while dealer_value < 17:
                # Check if game ended prematurely (e.g., timeout during sleep)
                if self.game_over:
                    return

                await asyncio.sleep(1) # Pause between dealer hits
                try:
                    self.dealer_hand.append(self.cog.deal_card(self.deck))
                except ValueError: # Handle empty deck just in case
                    # Decide how to handle: maybe dealer stands? Or game error?
                    print("Error: Deck became empty during dealer turn.")
                    # For now, let dealer stand with current value
                    break
                dealer_value = self.cog.calculate_hand_value(self.dealer_hand)

                # Update embed description in loop
                embed.description=(
                    f"Your hand: {', '.join(self.player_hand)} `({player_value})`\n"
                    f"Dealer's hand: {', '.join(self.dealer_hand)} `({dealer_value})`\n\n"
                    f"Wager: {self.current_wager} 🪙"
                )
                try:
                    # Edit using followup webhook again
                    await interaction.followup.edit_message('@original', embed=embed, view=self)
                except nextcord.NotFound:
                    print("Error: Original message not found during dealer turn (hit loop).")
                    await self.end_game(interaction, "Error - Message Deleted")
                    return
                except Exception as e:
                    print(f"Error editing message in dealer_turn (hit loop): {e}")
                    await self.end_game(interaction, "Error - Cannot Edit Message")
                    return

            # --- Determine Outcome --- (No changes needed here)
            # Check again if game ended during the process
            if self.game_over:
                return

            if dealer_value > 21:
                await self.end_game(interaction, "Dealer Bust")
            elif player_value == dealer_value:
                await self.end_game(interaction, "Push")
            elif player_value > dealer_value:
                await self.end_game(interaction, "Player Win")
            else: # dealer_value > player_value
                await self.end_game(interaction, "Dealer Win")
            # --- End of MODIFICATION ---

    async def handle_blackjack_outcome(self, interaction: nextcord.Interaction, player_bj: bool, dealer_bj: bool):
         """Handles immediate game end due to natural blackjacks."""
         if player_bj and dealer_bj:
             await self.end_game(interaction, "Push") # Both have BJ -> Push
         elif player_bj:
              # Player BJ usually pays 3:2, but we'll do 1:1 for simplicity matching current win logic
              await self.end_game(interaction, "Player Blackjack")
         elif dealer_bj:
              await self.end_game(interaction, "Dealer Blackjack")
         # No need for else, this function only called if at least one BJ exists


    async def end_game(self, interaction: nextcord.Interaction, result: str):
        """Ends the game, calculates payout, updates balance, and shows results."""
        if self.game_over: # Prevent running multiple times
            return
        self.game_over = True
        self.stop() # Stop the view from listening

        player_value = self.cog.calculate_hand_value(self.player_hand)
        dealer_value = self.cog.calculate_hand_value(self.dealer_hand)

        # --- FIX: Correct Payout Logic based on upfront deduction ---
        payout = 0 # Amount to add back to the player's balance
        profit = 0 # Net gain/loss for this hand
        final_result_text = ""
        color = nextcord.Color.default()

        if result in ["Player Win", "Dealer Bust", "Player Blackjack"]:
            # Player wins: Get back wager + winnings equal to wager
            payout = self.current_wager * 2
            profit = self.current_wager
            final_result_text = "You Win!" + (" (Blackjack!)" if result == "Player Blackjack" else "")
            color = nextcord.Color.green()
            if result == "Dealer Bust":
                 final_result_text = "Dealer Bust! You Win!"

        elif result == "Push":
            # Push: Get wager back
            payout = self.current_wager
            profit = 0
            final_result_text = "Push!"
            color = nextcord.Color.gold()

        else: # Player Loss scenarios: "Dealer Win", "Player Bust", "Dealer Blackjack"
            # Loss: Player gets nothing back (loss already happened via deductions)
            payout = 0
            profit = -self.current_wager # Loss is the total amount wagered
            color = nextcord.Color.red()
            if result == "Player Bust":
                final_result_text = "You Busted!"
            elif result == "Dealer Blackjack":
                 final_result_text = "Dealer Blackjack! You Lose."
            else: # Dealer Win
                final_result_text = "You Lose!"

        # Update the player's balance
        if payout > 0:
            await self.economy_cog.update_balance(self.interaction.user.id, payout)
        # ---------------------------------------------------------------

        # Create the final embed
        embed = nextcord.Embed(
            title=f"Blackjack - {final_result_text}",
            color=color
        )
        embed.add_field(name="Your Hand", value=f"{', '.join(self.player_hand)} `({player_value})`", inline=True)
        embed.add_field(name="Dealer's Hand", value=f"{', '.join(self.dealer_hand)} `({dealer_value})`", inline=True)

        # Use field for results for better spacing
        embed.add_field(
             name="Result",
             value=f"Wager: {self.current_wager} 🪙\nProfit: {profit:+} 🪙", # Show sign for profit
             inline=False
        )
        new_balance = await self.economy_cog.get_user_balance(self.interaction.user.id)
        embed.set_footer(text=f"Game over. Your new balance: {new_balance} 🪙")

        # Edit the original message, remove the view
        # Check if interaction response was deferred or already responded to
        try:
             # If the interaction leading to end_game was the first response (e.g. immediate BJ)
             if interaction.response.is_done():
                  await interaction.edit_original_message(embed=embed, view=None)
             else:
                  # If interaction was from a button click (edit_message used previously)
                  await interaction.response.edit_message(embed=embed, view=None)
        except nextcord.NotFound:
             # Fallback if the original message or interaction is lost
             await self.interaction.channel.send(embed=embed)
        except Exception as e:
             print(f"Error editing message in end_game: {e}")
             # Try sending a new message as a last resort
             try:
                await self.interaction.channel.send(embed=embed)
             except Exception as final_e:
                print(f"Failed to send final game message: {final_e}")


    async def on_timeout(self):
        """Handles the view timing out."""
        if self.game_over:
             return # Game already ended normally

        self.game_over = True
        # Consider the wager lost on timeout
        profit = -self.current_wager
        payout = 0 # Nothing is returned

        # If double down occured, the second wager was also deducted.
        # The initial deduction covers the original_wager loss.
        # If doubled, the current_wager reflects the total loss.

        embed = nextcord.Embed(
            title="Blackjack - Timeout",
            description="You did not finish the game in time. Your wager has been forfeited.",
            color=nextcord.Color.dark_grey()
        )
        embed.add_field(name="Your Hand", value=f"{', '.join(self.player_hand)} `({self.cog.calculate_hand_value(self.player_hand)})`", inline=True)
        embed.add_field(name="Dealer's Showing", value=f"{self.dealer_hand[0]}, `?`", inline=True)
        embed.add_field(
             name="Result",
             value=f"Wager: {self.current_wager} 🪙\nProfit: {profit:+} 🪙",
             inline=False
        )
        new_balance = await self.economy_cog.get_user_balance(self.interaction.user.id)
        embed.set_footer(text=f"Your new balance: {new_balance} 🪙")

        try:
            await self.interaction.edit_original_message(embed=embed, view=None)
        except nextcord.NotFound:
             # If message was deleted or interaction expired fully
             pass # Silently fail or log
        except Exception as e:
             print(f"Error editing message on timeout: {e}")


# Setup function remains the same
async def setup(bot: commands.Bot):
    bot.add_cog(Gambling(bot))
    print("GamblingCog loaded.")