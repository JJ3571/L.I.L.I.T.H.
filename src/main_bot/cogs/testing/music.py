"""
Minimal Discord Music Player Bot - Phase 1
Uses yt-dlp for audio extraction from various sources
Goal: Get basic playback working to isolate FFmpeg vs connection issues
"""

import nextcord
from nextcord.ext import commands
from nextcord import SlashOption
import asyncio
import yt_dlp
from typing import Optional

from main_bot.server_configs.config import GUILD_ID

# Suppress yt-dlp warnings
yt_dlp.utils.bug_reports_message = lambda: ''

# FFmpeg options for audio streaming
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -loglevel quiet',
    'options': '-vn -filter:a "volume=0.8"'
}

# yt-dlp options for extracting audio
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': False,
    'quiet': True,
    'no_warnings': True,
    'extract_flat': False,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}


class Song:
    """Represents a single song - minimal for Phase 1"""
    def __init__(self, source: str, title: str, duration: Optional[int] = None):
        self.source = source  # Audio URL or file path
        self.title = title
        self.duration = duration
    
    def __str__(self):
        duration_str = f" ({self.format_duration()})" if self.duration else ""
        return f"{self.title}{duration_str}"
    
    def format_duration(self) -> str:
        """Format duration in MM:SS or HH:MM:SS"""
        if not self.duration:
            return "Unknown"
        hours, remainder = divmod(self.duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"


class MusicPlayer:
    """Manages music playback for a single guild - minimal for Phase 1"""
    def __init__(self, guild: nextcord.Guild, cog_instance):
        self.guild = guild
        self.cog = cog_instance
        self.voice_client: Optional[nextcord.VoiceClient] = None
        self.current_song: Optional[Song] = None
        self.is_playing = False
        self.is_paused = False
    
    async def connect(self, channel: nextcord.VoiceChannel) -> bool:
        """Simplified connection logic - use guild.voice_client as source of truth"""
        guild = channel.guild
        
        # Check existing connection
        if guild.voice_client:
            if guild.voice_client.channel.id == channel.id:
                # Already in target channel - reuse
                print(f"Already in target channel: {channel.name}, reusing connection")
                self.voice_client = guild.voice_client
                return True
            else:
                # Move to target channel
                print(f"Moving from {guild.voice_client.channel.name} to {channel.name}")
                try:
                    await guild.voice_client.move_to(channel)
                    self.voice_client = guild.voice_client
                    return True
                except Exception as e:
                    print(f"Error moving to channel: {e}")
                    # Fall through to fresh connection
        
        # No existing connection - connect fresh
        print(f"Connecting to voice channel: {channel.name} (id: {channel.id})")
        try:
            self.voice_client = await channel.connect(timeout=10.0, reconnect=False)
            print(f"Successfully connected to {channel.name}")
            return True
        except Exception as e:
            print(f"Connection error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def play(self, song: Song):
        """Play a song - minimal implementation"""
        if not self.voice_client or not self.voice_client.is_connected():
            print("ERROR: Voice client not connected")
            return False
        
        self.current_song = song
        self.is_playing = True
        self.is_paused = False
        
        try:
            print(f"Playing: {song.title} from {song.source[:50]}...")
            source = nextcord.FFmpegPCMAudio(song.source, **FFMPEG_OPTIONS)
            
            def after_playing(error):
                """Callback after song ends"""
                if error:
                    print(f"Playback error: {error}")
                self.is_playing = False
                self.current_song = None
                # Schedule async cleanup
                asyncio.create_task(self.on_song_end(error))
            
            self.voice_client.play(source, after=after_playing)
            print(f"Started playing: {song.title}")
            return True
        except Exception as e:
            print(f"Error starting playback: {e}")
            import traceback
            traceback.print_exc()
            self.is_playing = False
            self.current_song = None
            return False
    
    async def on_song_end(self, error):
        """Handle song end - minimal for Phase 1"""
        print(f"Song ended. Error: {error}")
        # For Phase 1, just stop - no queue handling yet
    
    def pause(self):
        """Pause playback"""
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.pause()
            self.is_paused = True
    
    def resume(self):
        """Resume playback"""
        if self.voice_client and self.voice_client.is_paused():
            self.voice_client.resume()
            self.is_paused = False
    
    def stop(self):
        """Stop playback"""
        if self.voice_client:
            self.voice_client.stop()
        self.is_playing = False
        self.is_paused = False
        self.current_song = None
    
    async def disconnect(self):
        """Disconnect from voice channel"""
        self.stop()
        if self.voice_client:
            await self.voice_client.disconnect()
            self.voice_client = None


class MusicCog(commands.Cog):
    """Discord Music Bot Cog - Phase 1: Minimal implementation"""
    def __init__(self, bot):
        self.bot = bot
        self.players: dict[int, MusicPlayer] = {}
        print("MusicCog initialized (Phase 1 - Minimal)")
    
    def get_player(self, guild: nextcord.Guild) -> MusicPlayer:
        """Get or create a music player for the guild"""
        if guild.id not in self.players:
            self.players[guild.id] = MusicPlayer(guild, self)
        return self.players[guild.id]
    
    async def extract_song_info(self, query: str) -> Optional[Song]:
        """Extract song information using yt-dlp"""
        ydl_opts = YDL_OPTIONS.copy()
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract info
                info = ydl.extract_info(query, download=False)
                
                # Handle playlists - for Phase 1, just get first song
                if 'entries' in info:
                    if not info['entries']:
                        return None
                    info = info['entries'][0]
                
                # Get audio URL
                formats = info.get('formats', [])
                audio_url = None
                
                for fmt in formats:
                    if fmt.get('acodec') != 'none' and fmt.get('url'):
                        audio_url = fmt['url']
                        break
                
                if not audio_url:
                    # Fallback: use the best format URL
                    audio_url = info.get('url')
                
                if not audio_url:
                    print(f"ERROR: Could not find audio URL for {query}")
                    return None
                
                title = info.get('title', 'Unknown Title')
                duration = info.get('duration')
                
                print(f"Extracted: {title} (duration: {duration}s, URL: {audio_url[:50]}...)")
                return Song(source=audio_url, title=title, duration=duration)
        
        except Exception as e:
            print(f"Error extracting song info: {e}")
            raise Exception(f"Could not extract audio information: {str(e)}")
    
    @nextcord.slash_command(name="music", description="Music player commands", guild_ids=[GUILD_ID])
    async def music(self, interaction: nextcord.Interaction):
        pass
    
    @music.subcommand(name="play", description="Play a song - Phase 1: URL or search query")
    async def play(
        self,
        interaction: nextcord.Interaction,
        query: str = SlashOption(description="Song URL or search query")
    ):
        """Play a song - Phase 1: Basic playback only"""
        await interaction.response.defer()
        
        # Check if user is in voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send("❌ You need to be in a voice channel to use this command!")
            return
        
        voice_channel = interaction.user.voice.channel
        player = self.get_player(interaction.guild)
        
        # Connect if not connected
        if not player.voice_client or not player.voice_client.is_connected():
            await interaction.followup.send(f"🔌 Connecting to {voice_channel.name}...")
            connected = await player.connect(voice_channel)
            if not connected:
                await interaction.followup.send("❌ Could not connect to voice channel!")
                return
        
        try:
            await interaction.followup.send(f"🔍 Searching for: `{query}`...")
            song = await self.extract_song_info(query)
            if not song:
                await interaction.followup.send("❌ No song found!")
                return
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {str(e)}")
            return
        
        # Stop current song if playing
        if player.is_playing:
            player.stop()
        
        success = await player.play(song)
        if success:
            await interaction.followup.send(f"▶️ Now playing: **{song}**")
        else:
            await interaction.followup.send("❌ Failed to start playback.")
    
    @music.subcommand(name="pause", description="Pause playback")
    async def pause(self, interaction: nextcord.Interaction):
        """Pause playback"""
        player = self.get_player(interaction.guild)
        
        if not player.is_playing:
            await interaction.response.send_message("❌ Nothing is currently playing!")
            return
        
        if player.is_paused:
            await interaction.response.send_message("❌ Already paused!")
            return
        
        player.pause()
        await interaction.response.send_message("⏸️ Paused!")
    
    @music.subcommand(name="resume", description="Resume playback")
    async def resume(self, interaction: nextcord.Interaction):
        """Resume playback"""
        player = self.get_player(interaction.guild)
        
        if not player.is_paused:
            await interaction.response.send_message("❌ Playback is not paused!")
            return
        
        player.resume()
        await interaction.response.send_message("▶️ Resumed!")
    
    @music.subcommand(name="stop", description="Stop playback")
    async def stop(self, interaction: nextcord.Interaction):
        """Stop playback"""
        player = self.get_player(interaction.guild)
        player.stop()
        await interaction.response.send_message("⏹️ Stopped!")
    
    @music.subcommand(name="queue", description="Show now playing (Phase 1: no queue)")
    async def queue(self, interaction: nextcord.Interaction):
        """Show now playing"""
        player = self.get_player(interaction.guild)
        if not player.current_song:
            await interaction.response.send_message("❌ Nothing playing.")
            return
        await interaction.response.send_message(f"▶️ Now playing: **{player.current_song}**")
    
    @music.subcommand(name="nowplaying", description="Show the currently playing song")
    async def nowplaying(self, interaction: nextcord.Interaction):
        """Show the currently playing song"""
        player = self.get_player(interaction.guild)
        if not player.current_song:
            await interaction.response.send_message("❌ Nothing is currently playing!")
            return
        s = player.current_song
        duration_str = f" ({s.format_duration()})" if s.duration else ""
        await interaction.response.send_message(f"🎵 **{s.title}**{duration_str}")
    
    @music.subcommand(name="disconnect", description="Disconnect from voice channel")
    async def disconnect(self, interaction: nextcord.Interaction):
        """Disconnect from voice channel"""
        player = self.get_player(interaction.guild)
        await player.disconnect()
        await interaction.response.send_message("👋 Disconnected from voice channel!")
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Auto-disconnect if bot is alone in voice channel"""
        if member.bot:
            return
        
        for guild_id, player in list(self.players.items()):
            if player.voice_client and player.voice_client.channel:
                if len(player.voice_client.channel.members) == 1:
                    await asyncio.sleep(60)
                    if (player.voice_client and player.voice_client.channel and 
                        len(player.voice_client.channel.members) == 1):
                        await player.disconnect()


async def setup(bot):
    bot.add_cog(MusicCog(bot))
    print("MusicCog has been added to the bot.")
