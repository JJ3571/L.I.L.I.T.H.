import nextcord
from nextcord.ext import commands, tasks
import json
import os
import asyncio
import random
from datetime import datetime, timedelta

from server_configs.config import GUILD_ID
from server_configs.cogs_config import backup_channel_id, admin_user_ids, afk_channel_id, heads_emoji_id, tails_emoji_id

class EconomyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_file = 'economy_db/economy_data.json'
        self.voice_times_file = 'economy_db/voice_times.json'
        self.load_data()
        self.backup_channel_id = backup_channel_id
        self.afk_channel_id = afk_channel_id
        self.voice_times = {}
        self.load_voice_times()
        self.backup_task.start()
        self.voice_reward_task.start()

    def load_data(self):
        if os.path.exists(self.data_file):
            with open(self.data_file, 'r') as f:
                self.economy_data = json.load(f)
            print("Economy data loaded.")
        else:
            self.economy_data = {}
            print("No economy data found, starting fresh.")

    def save_data(self):
        with open(self.data_file, 'w') as f:
            json.dump(self.economy_data, f)
        print("Economy data saved.")

    def load_voice_times(self):
        if os.path.exists(self.voice_times_file):
            with open(self.voice_times_file, 'r') as f:
                self.voice_times = json.load(f)
            print("Voice times data loaded.")
        else:
            self.voice_times = {}
            print("No voice times data found, starting fresh.")

    def save_voice_times(self):
        with open(self.voice_times_file, 'w') as f:
            json.dump(self.voice_times, f)
        print("Voice times data saved.")

    @tasks.loop(hours=24)
    async def backup_task(self):
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(self.backup_channel_id)
        if channel:
            await channel.send(file=nextcord.File(self.data_file))
            await channel.send(file=nextcord.File(self.voice_times_file))
        print("Backup task completed.")

    @tasks.loop(minutes=5)
    async def voice_reward_task(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot:
                    continue
                if member.voice and member.voice.channel and member.voice.channel.id != self.afk_channel_id:
                    user_id = str(member.id)
                    if user_id not in self.voice_times:
                        self.voice_times[user_id] = datetime.utcnow().isoformat()
                        print(f"Started tracking voice time for {member.display_name}.")
                    else:
                        time_spent = datetime.utcnow() - datetime.fromisoformat(self.voice_times[user_id])
                        if time_spent >= timedelta(minutes=5):
                            if user_id not in self.economy_data:
                                self.economy_data[user_id] = 0
                            self.economy_data[user_id] += 10  # Reward for spending 5 minutes in a voice channel
                            self.voice_times[user_id] = datetime.utcnow().isoformat()
                            self.save_data()
                            self.save_voice_times()
                            print(f"Rewarded {member.display_name} for spending 5 minutes in a voice channel.")

    @nextcord.slash_command(name="econ", description="Economy commands")
    async def econ(self, interaction: nextcord.Interaction):
        pass

    @econ.subcommand(name="add_money", description="Add money to a user")
    async def add_money(self, interaction: nextcord.Interaction, user: nextcord.Member, amount: int):
        if interaction.user.id not in admin_user_ids:
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            print(f"{interaction.user.display_name} attempted to use add_money without permission.")
            return

        user_id = str(user.id)
        if user_id not in self.economy_data:
            self.economy_data[user_id] = 0
        self.economy_data[user_id] += amount
        self.save_data()
        await interaction.response.send_message(f"Added {amount} to {user.mention}. New balance: {self.economy_data[user_id]}")
        print(f"Added {amount} to {user.display_name}. New balance: {self.economy_data[user_id]}")

    @econ.subcommand(name="balance", description="Check the balance of a user")
    async def balance(self, interaction: nextcord.Interaction, user: nextcord.Member = None):
        user = user or interaction.user
        user_id = str(user.id)
        balance = self.economy_data.get(user_id, 0)
        await interaction.response.send_message(f"{user.mention} has a balance of {balance}")
        print(f"{user.display_name} checked their balance: {balance}")

    @econ.subcommand(name="coin_flip", description="Bet an amount of money on a coin flip")
    async def coin_flip(self, interaction: nextcord.Interaction, amount: int, choice: str):
        user_id = str(interaction.user.id)
        if user_id not in self.economy_data or self.economy_data[user_id] < amount:
            await interaction.response.send_message("You do not have enough money to make this bet.", ephemeral=True)
            print(f"{interaction.user.display_name} attempted to bet {amount} but has insufficient funds.")
            return
    
        if choice.lower() not in ["heads", "tails"]:
            await interaction.response.send_message("Invalid choice. Please choose 'heads' or 'tails'.", ephemeral=True)
            return
    
        outcome = random.choice(["heads", "tails"])
        if outcome == choice.lower():
            self.economy_data[user_id] += amount
            result_message = f"You won! You now have {self.economy_data[user_id]}."
        else:
            self.economy_data[user_id] -= amount
            result_message = f"You lost! You now have {self.economy_data[user_id]}."
    
        self.save_data()
    
        # Send the outcome emoji

        outcome_emoji = f"<:heads:{heads_emoji_id}>" if outcome == "heads" else f"<:tails:{tails_emoji_id}>"
        await interaction.response.send_message(result_message)
        await interaction.followup.send(outcome_emoji)
        print(f"{interaction.user.display_name} bet {amount} on {choice} and the outcome was {outcome}. New balance: {self.economy_data[user_id]}")
    
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        user_id = str(message.author.id)
        if user_id not in self.economy_data:
            self.economy_data[user_id] = 0
        self.economy_data[user_id] += 1  # Reward for sending a message
        self.save_data()
        print(f"Rewarded {message.author.display_name} for sending a message.")

def setup(bot):
    bot.add_cog(EconomyCog(bot))