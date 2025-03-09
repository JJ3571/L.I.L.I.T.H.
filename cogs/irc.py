import nextcord
from nextcord.ext import commands, tasks
import irc.client
import asyncio

class IRCBridge(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.irc_client = irc.client.Reactor()
        self.irc_server = None
        self.irc_channel = "#minecraft"
        self.irc_nickname = "DiscordBot"
        self.irc_server_address = "localhost"
        self.irc_server_port = 6667
        self.discord_channel_id = 123456789012345678  # Replace with your Discord channel ID

        self.connect_to_irc()

    def connect_to_irc(self):
        try:
            self.irc_server = self.irc_client.server().connect(
                self.irc_server_address,
                self.irc_server_port,
                self.irc_nickname
            )
            self.irc_server.add_global_handler("welcome", self.on_connect)
            self.irc_server.add_global_handler("pubmsg", self.on_public_message)
            print("Connected to IRC server.")
        except irc.client.ServerConnectionError as e:
            print(f"Failed to connect to IRC server: {e}")

    def on_connect(self, connection, event):
        connection.join(self.irc_channel)
        print(f"Joined IRC channel: {self.irc_channel}")

    def on_public_message(self, connection, event):
        message = event.arguments[0]
        author = event.source.nick
        asyncio.run_coroutine_threadsafe(
            self.send_to_discord(f"<{author}> {message}"),
            self.bot.loop
        )

    async def send_to_discord(self, message):
        channel = self.bot.get_channel(self.discord_channel_id)
        if channel:
            await channel.send(message)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        if message.channel.id == self.discord_channel_id:
            self.irc_server.privmsg(self.irc_channel, f"<{message.author.display_name}> {message.content}")

    @tasks.loop(seconds=1)
    async def irc_loop(self):
        self.irc_client.process_once(0.2)

    @irc_loop.before_loop
    async def before_irc_loop(self):
        await self.bot.wait_until_ready()

def setup(bot):
    bot.add_cog(IRCBridge(bot))