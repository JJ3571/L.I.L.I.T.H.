import nextcord
from nextcord.ext import commands, tasks, menus
import sqlite3
import time, datetime
import random

from server_configs.cogs_config import backup_channel_id, watch_party_channel_id, admin_user_ids, afk_channel_id, heads_emoji_id, tails_emoji_id

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_timers = {}
        self.message_counts = {}
        self.reward_interval = 60  # seconds
        self.voice_reward_amount = 5
        self.message_reward_amount = 1
        self.movie_night_reward = 1000
        self.movie_night_time_threshold = 90 * 60  # 1.5 hours in seconds

        self.db_path = "economy.db"
        self.create_tables()
        self.reward_users.start()
        self.backup_task.start()

    def create_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0
            )
        ''')

        conn.commit()
        conn.close()

    def get_balance(self, user_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0

    def update_balance(self, user_id, amount):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()

    def get_all_balances(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, balance FROM users ORDER BY balance DESC")
        result = cursor.fetchall()
        conn.close()
        return result

    @tasks.loop(minutes=1)
    async def backup_task(self):
        now = datetime.now(pytz.timezone('US/Pacific'))
        if now.hour in [0, 12] and now.minute == 0:
            await self.bot.wait_until_ready()
            channel = self.bot.get_channel(backup_channel_id)
            if channel:
                await channel.send(file=nextcord.File(self.db_path))
                print("Backup task completed.")

    @backup_task.before_loop
    async def before_backup_task(self):
        await self.bot.wait_until_ready()
        print("Backup task is ready to start.")

    def deal_card(self, deck):
        card = random.choice(deck)
        deck.remove(card)
        return card

    def calculate_hand_value(self, hand):
        value = 0
        aces = 0
        for card in hand:
            if card[:-1].isdigit():
                value += int(card[:-1])
            elif card[0] in ['J', 'Q', 'K']:
                value += 10
            elif card[0] == 'A':
                aces += 1
                value += 11
        while value > 21 and aces:
            value -= 10
            aces -= 1
        return value

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        user_id = message.author.id
        if user_id not in self.message_counts:
            self.message_counts[user_id] = 0
        self.message_counts[user_id] += 1

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        user_id = member.id

        if before.channel is None and after.channel is not None:
            # User joined a voice channel
            self.voice_timers[user_id] = time.time()

        elif before.channel is not None and after.channel is None:
            # User left a voice channel
            if user_id in self.voice_timers:
                elapsed_time = time.time() - self.voice_timers[user_id]
                del self.voice_timers[user_id]

                if before.channel.id != afk_channel_id:
                    # Reward regular voice activity
                    self.update_balance(user_id, int(elapsed_time / self.reward_interval) * self.voice_reward_amount)

                if before.channel.id == watch_party_channel_id and elapsed_time >= self.movie_night_time_threshold:
                    # Reward for movie night attendance
                    self.update_balance(user_id, self.movie_night_reward)
                    try:
                        await member.send("You were rewarded 1000 coins for attending movie night!")
                    except nextcord.HTTPException:
                        print(f"Failed to send DM to {member.name}")

    @tasks.loop(seconds=60)
    async def reward_users(self):
        for user_id, count in self.message_counts.items():
            self.update_balance(user_id, count * self.message_reward_amount)
        self.message_counts.clear()

    @nextcord.slash_command(name="balance", description="Check your balance or someone else's")
    async def balance_command(self, interaction: nextcord.Interaction, member: nextcord.Member = nextcord.SlashOption(required=False, description='The member to check the balance of.')):
        member = member or interaction.user
        balance = self.get_balance(member.id)
        await interaction.response.send_message(f"{member.display_name}'s balance: {balance}")

    @nextcord.slash_command(name="give", description="Give currency to another user")
    async def give_command(self, interaction: nextcord.Interaction, member: nextcord.Member, amount: int):
        if amount <= 0:
            await interaction.response.send_message("Amount must be positive.", ephemeral=True)
            return

        sender_id = interaction.user.id

        if sender_id in admin_user_ids:
            view = AdminGiveView(self, member, amount)
            await interaction.response.send_message("Give from your balance or the treasury?", view=view, ephemeral=True)
            return

        sender_balance = self.get_balance(sender_id)
        if sender_balance < amount:
            await interaction.response.send_message("Insufficient funds.", ephemeral=True)
            return

        self.update_balance(sender_id, -amount)
        self.update_balance(member.id, amount)
        await interaction.response.send_message(f"{interaction.user.display_name} gave {member.display_name} {amount} coins.")

    @nextcord.slash_command(name="cointoss", description="Toss a coin and bet your balance.")
    async def cointoss_command(self, interaction: nextcord.Interaction, choice: str = nextcord.SlashOption(choices=["heads", "tails"], description="Heads or tails?"), amount: int = nextcord.SlashOption(description="Amount to bet.")):
        user_id = interaction.user.id
        balance = self.get_balance(user_id)

        if amount <= 0:
            await interaction.response.send_message("Amount must be positive.", ephemeral=True)
            return

        if balance < amount:
            await interaction.response.send_message("Insufficient funds.", ephemeral=True)
            return

        coin_flip = random.choice(["heads", "tails"])

        heads_emoji = self.bot.get_emoji(heads_emoji_id)
        tails_emoji = self.bot.get_emoji(tails_emoji_id)

        if heads_emoji is None or tails_emoji is None:
            await interaction.response.send_message("Heads or tails emoji not found. Please configure them correctly.", ephemeral=True)
            return

        embed = nextcord.Embed(title="Coin Toss Result")

        if coin_flip == "heads":
            embed.set_image(url="https://cdn.discordapp.com/attachments/807342895656730685/1346364014648623116/61tOhQIcfES.png?ex=67c7eab3&is=67c69933&hm=165402180db8b6b8cfb8f8c983c959f62d83ca6469cb534afdb370ddafbbf593&")
        else:
            embed.set_image(url="https://cdn.discordapp.com/attachments/807342895656730685/1346363550926508083/c5uy98beouv41.png?ex=67c7ea44&is=67c698c4&hm=b0ac51853969fb12c4b0a66306cb3537a78e14484aa1d45535218253e2bfdb62&")

        if choice == coin_flip:
            self.update_balance(user_id, amount)
            embed.description = f"You won! The coin landed on {str(heads_emoji) if coin_flip == 'heads' else str(tails_emoji)}. You won {amount} coins."
            embed.color = nextcord.Color.green()
        else:
            self.update_balance(user_id, -amount)
            embed.description = f"You lost! The coin landed on {str(heads_emoji) if coin_flip == 'heads' else str(tails_emoji)}. You lost {amount} coins."
            embed.color = nextcord.Color.red()

        await interaction.response.send_message(embed=embed)

    class LeaderboardSource(menus.ListPageSource):
        def __init__(self, data):
            super().__init__(data, per_page=10)

        async def format_page(self, menu, entries):
            embed = nextcord.Embed(title="Leaderboard", color=nextcord.Color.gold())
            description = "\n".join(entries)
            embed.description = description
            return embed

    @nextcord.slash_command(name="leaderboard", description="Display the leaderboard of user balances")
    async def leaderboard_command(self, interaction: nextcord.Interaction):
        try:
            balances = self.get_all_balances()
            if not balances:
                await interaction.response.send_message("No users found in the leaderboard.")
                return

            leaderboard = []
            for rank, (user_id, balance) in enumerate(balances, start=1):
                try:
                    user = await self.bot.fetch_user(user_id)
                    leaderboard.append(f"{rank}. {user.display_name}: {balance} coins")
                except Exception as e:
                    print(f"Error fetching user {user_id}: {e}")

            pages = menus.MenuPages(source=self.LeaderboardSource(leaderboard), clear_reactions_after=True)
            await pages.start(interaction)
        except Exception as e:
            print(f"Error in leaderboard_command: {e}")
            await interaction.response.send_message("An error occurred while fetching the leaderboard.", ephemeral=True)

    @nextcord.slash_command(name="blackjack", description="Play blackjack with a wager.")
    async def blackjack_command(self, interaction: nextcord.Interaction, amount: int = nextcord.SlashOption(description="Amount to wager.")):
        user_id = interaction.user.id
        balance = self.get_balance(user_id)

        if amount <= 0:
            await interaction.response.send_message("Amount must be positive.", ephemeral=True)
            return

        if balance < amount:
            await interaction.response.send_message("Insufficient funds.", ephemeral=True)
            return

        deck = [f"{rank}{suit}" for suit in ['♠', '♥', '♦', '♣'] for rank in ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']]
        random.shuffle(deck)

        player_hand = [self.deal_card(deck), self.deal_card(deck)]
        dealer_hand = [self.deal_card(deck), self.deal_card(deck)]

        player_value = self.calculate_hand_value(player_hand)
        dealer_value = self.calculate_hand_value(dealer_hand)

        embed = nextcord.Embed(title="Blackjack", description=f"Your hand: {', '.join(player_hand)} ({player_value})\nDealer's hand: {dealer_hand[0]}, ?")
        await interaction.response.send_message(embed=embed, view=BlackjackView(self, interaction, deck, player_hand, dealer_hand, amount))

class BlackjackView(nextcord.ui.View):
    def __init__(self, cog, interaction, deck, player_hand, dealer_hand, amount):
        super().__init__()
        self.cog = cog
        self.interaction = interaction
        self.deck = deck
        self.player_hand = player_hand
        self.dealer_hand = dealer_hand
        self.amount = amount

    @nextcord.ui.button(label="Hit", style=nextcord.ButtonStyle.green)
    async def hit(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message("This is not your game.", ephemeral=True)
            return
        self.player_hand.append(self.cog.deal_card(self.deck))
        player_value = self.cog.calculate_hand_value(self.player_hand)
        dealer_value = self.cog.calculate_hand_value(self.dealer_hand)

        if player_value > 21:
            await self.end_game(interaction, "You busted!")
            return

        embed = nextcord.Embed(title="Blackjack", description=f"Your hand: {', '.join(self.player_hand)} ({player_value})\nDealer's hand: {self.dealer_hand[0]}, ?")
        await interaction.response.edit_message(embed=embed, view=self)

    @nextcord.ui.button(label="Stand", style=nextcord.ButtonStyle.blurple)
    async def stand(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message("This is not your game.", ephemeral=True)
            return
        await self.dealer_turn(interaction)

    async def dealer_turn(self, interaction):
        dealer_value = self.cog.calculate_hand_value(self.dealer_hand)
        while dealer_value < 17:
            self.dealer_hand.append(self.cog.deal_card(self.deck))
            dealer_value = self.cog.calculate_hand_value(self.dealer_hand)

        player_value = self.cog.calculate_hand_value(self.player_hand)

        if dealer_value > 21 or player_value > dealer_value:
            await self.end_game(interaction, "You win!")
        elif player_value == dealer_value:
            await self.end_game(interaction, "Push!")
        else:
            await self.end_game(interaction, "You lose!")

    async def end_game(self, interaction, result):
        player_value = self.cog.calculate_hand_value(self.player_hand)
        dealer_value = self.cog.calculate_hand_value(self.dealer_hand)
        embed = nextcord.Embed(title="Blackjack", description=f"Your hand: {', '.join(self.player_hand)} ({player_value})\nDealer's hand: {', '.join(self.dealer_hand)} ({dealer_value})\n{result}")
        await interaction.response.edit_message(embed=embed, view=None)

        if result == "You win!":
            self.cog.update_balance(self.interaction.user.id, self.amount)
        elif result == "You lose!":
            self.cog.update_balance(self.interaction.user.id, -self.amount)

        self.stop()

class AdminGiveView(nextcord.ui.View):
    def __init__(self, cog, member, amount):
        super().__init__()
        self.cog = cog
        self.member = member
        self.amount = amount

    @nextcord.ui.button(label="From Balance", style=nextcord.ButtonStyle.green)
    async def from_balance(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        sender_id = interaction.user.id
        sender_balance = self.cog.get_balance(sender_id)
        if sender_balance < self.amount:
            await interaction.response.send_message("Insufficient funds.", ephemeral=True)
            return
        self.cog.update_balance(sender_id, -self.amount)
        self.cog.update_balance(self.member.id, self.amount)
        await interaction.response.send_message(f"{interaction.user.display_name} gave {self.member.display_name} {self.amount} coins from their balance.")
        self.stop()

    @nextcord.ui.button(label="From Treasury", style=nextcord.ButtonStyle.blurple)
    async def from_treasury(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.cog.update_balance(self.member.id, self.amount)
        await interaction.response.send_message(f"{interaction.user.display_name} added {self.amount} coins to {self.member.display_name} from the treasury.")
        self.stop()

async def setup(bot):
    await bot.add_cog(Economy(bot))
    print("EconomyCog has been added to the bot.")