"""
Modern Discord Music Player Bot
Uses yt-dlp for audio extraction from various sources
Supports: YouTube, YouTube Music, playlists, local files, SoundCloud, and more
"""

import nextcord
from nextcord.ext import commands, tasks
from nextcord import SlashOption
import asyncio
import yt_dlp
import os
import aiosqlite
import random
import math
from pathlib import Path
from typing import Optional, List, Dict, Set
import re

from server_configs.config import GUILD_ID
from server_configs.cogs_config import admin_user_ids
from server_configs.database_config import DATABASE_PATHS

DB_PATH = DATABASE_PATHS["music"]
# Jazz folder path - adjust if needed
JAZZ_FOLDER = Path(__file__).parent.parent.parent / "local_music" / "jazz"

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
    """Represents a single song in the queue"""
    def __init__(self, source: str, title: str, duration: Optional[int] = None, 
                 uploader: Optional[str] = None, webpage_url: Optional[str] = None,
                 thumbnail: Optional[str] = None, is_local: bool = False, start_time: int = 0):
        self.source = source
        self.title = title
        self.duration = duration
        self.uploader = uploader
        self.webpage_url = webpage_url
        self.thumbnail = thumbnail
        self.is_local = is_local
        self.start_time = start_time  # For random start positions
    
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


class MusicControlView(nextcord.ui.View):
    """Persistent view with control buttons for music player"""
    def __init__(self, cog_instance, guild_id: int):
        super().__init__(timeout=None)  # No timeout = persistent
        self.cog = cog_instance
        self.guild_id = guild_id
    
    @nextcord.ui.button(label="⏸️ Pause", style=nextcord.ButtonStyle.primary, custom_id="music_pause")
    async def pause_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        player = self.cog.get_player(interaction.guild)
        if not player.is_playing:
            await interaction.response.send_message("❌ Nothing is currently playing!", ephemeral=True)
            return
        
        if player.is_paused:
            await interaction.response.send_message("❌ Already paused!", ephemeral=True)
            return
        
        player.pause()
        await interaction.response.send_message("⏸️ Paused!", ephemeral=True)
        await self.cog.update_control_embed(interaction.guild)
    
    @nextcord.ui.button(label="▶️ Resume", style=nextcord.ButtonStyle.success, custom_id="music_resume")
    async def resume_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        player = self.cog.get_player(interaction.guild)
        if not player.is_paused:
            await interaction.response.send_message("❌ Playback is not paused!", ephemeral=True)
            return
        
        player.resume()
        await interaction.response.send_message("▶️ Resumed!", ephemeral=True)
        await self.cog.update_control_embed(interaction.guild)
    
    @nextcord.ui.button(label="⏭️ Skip", style=nextcord.ButtonStyle.danger, custom_id="music_skip")
    async def skip_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        player = self.cog.get_player(interaction.guild)
        if not player.is_playing:
            await interaction.response.send_message("❌ Nothing is currently playing!", ephemeral=True)
            return
        
        # Check if voting skip is enabled
        voting_enabled = await self.cog.get_voting_skip_enabled(interaction.guild.id)
        
        if voting_enabled:
            # Use voting system
            await self.cog.handle_vote_skip(interaction)
        else:
            # Direct skip
            player.skip()
            await interaction.response.send_message("⏭️ Skipped!", ephemeral=True)
            await self.cog.update_control_embed(interaction.guild)
    
    @nextcord.ui.button(label="⏹️ Stop", style=nextcord.ButtonStyle.danger, custom_id="music_stop")
    async def stop_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        player = self.cog.get_player(interaction.guild)
        player.clear_queue()
        player.skip()
        await interaction.response.send_message("⏹️ Stopped and cleared queue!", ephemeral=True)
        await self.cog.update_control_embed(interaction.guild)
    
    @nextcord.ui.button(label="⚙️ Settings", style=nextcord.ButtonStyle.secondary, custom_id="music_settings")
    async def settings_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        # Only admins can access settings
        if interaction.user.id not in admin_user_ids:
            await interaction.response.send_message("❌ Only admins can access settings!", ephemeral=True)
            return
        
        # Show settings modal/ephemeral message
        await self.cog.show_settings(interaction)


class VoteSkipView(nextcord.ui.View):
    """View for voting to skip"""
    def __init__(self, cog_instance, guild_id: int, song_id: str):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.guild_id = guild_id
        self.song_id = song_id
    
    @nextcord.ui.button(label="👍 Vote Skip", style=nextcord.ButtonStyle.primary, custom_id="vote_skip")
    async def vote_skip(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.cog.handle_vote_skip_vote(interaction, self.song_id)


class MusicPlayer:
    """Manages music playback for a single guild"""
    def __init__(self, guild: nextcord.Guild, cog_instance):
        self.guild = guild
        self.cog = cog_instance
        self.queue: List[Song] = []
        self.current_song: Optional[Song] = None
        self.voice_client: Optional[nextcord.VoiceClient] = None
        self.is_playing = False
        self.is_paused = False
        self.loop = False
        self.loop_queue = False
        self.control_message: Optional[nextcord.Message] = None
        self.control_channel: Optional[nextcord.TextChannel] = None
        self.is_jazz_mode = False
        self.skip_votes: Set[int] = set()  # User IDs who voted to skip
        self.current_skip_song_id: Optional[str] = None  # Track which song votes are for
        self.idle_since: Optional[float] = None  # Timestamp when bot became idle
    
    async def connect(self, channel: nextcord.VoiceChannel, text_channel: Optional[nextcord.TextChannel] = None) -> bool:
        """Connect to a voice channel and set up control embed"""
        try:
            if self.voice_client and self.voice_client.is_connected():
                await self.voice_client.move_to(channel)
            else:
                self.voice_client = await channel.connect()
            
            # Set control channel (use text channel if provided, otherwise try to find one)
            if text_channel:
                self.control_channel = text_channel
            else:
                # Try to find a text channel in the same category or default to first text channel
                if channel.category:
                    text_channels = [ch for ch in channel.category.text_channels if ch.permissions_for(channel.guild.me).send_messages]
                    if text_channels:
                        self.control_channel = text_channels[0]
                    else:
                        self.control_channel = channel.guild.system_channel or next(iter(channel.guild.text_channels), None)
                else:
                    self.control_channel = channel.guild.system_channel or next(iter(channel.guild.text_channels), None)
            
            # Create or update control embed
            if self.control_channel:
                await self.create_control_embed()
            
            return True
        except Exception as e:
            print(f"Error connecting to voice channel: {e}")
            return False
    
    async def create_control_embed(self):
        """Create or update the control embed message"""
        if not self.control_channel:
            return
        
        embed = self.cog.create_control_embed(self)
        view = MusicControlView(self.cog, self.guild.id)
        
        # Register persistent view
        self.cog.bot.add_view(view)
        
        if self.control_message:
            try:
                await self.control_message.edit(embed=embed, view=view)
            except nextcord.NotFound:
                # Message was deleted, create new one
                self.control_message = await self.control_channel.send(embed=embed, view=view)
        else:
            self.control_message = await self.control_channel.send(embed=embed, view=view)
    
    async def disconnect(self):
        """Disconnect from voice channel"""
        self.queue.clear()
        self.current_song = None
        self.is_jazz_mode = False
        self.skip_votes.clear()
        
        # Delete control message if it exists
        if self.control_message:
            try:
                await self.control_message.delete()
            except:
                pass
            self.control_message = None
        
        if self.voice_client:
            await self.voice_client.disconnect()
            self.voice_client = None
        
        self.is_playing = False
        self.is_paused = False
    
    def add_to_queue(self, song: Song):
        """Add a song to the queue"""
        self.queue.append(song)
    
    def clear_queue(self):
        """Clear the queue"""
        self.queue.clear()
    
    def skip(self):
        """Skip the current song"""
        self.skip_votes.clear()
        self.current_skip_song_id = None
        self.idle_since = None  # Reset idle timer
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()
    
    async def play_next(self):
        """Play the next song in the queue"""
        if self.loop and self.current_song:
            await self._play_song(self.current_song)
            return
        
        if self.is_jazz_mode:
            # Jazz mode: pick random track and random position
            await self.play_random_jazz()
        elif self.queue:
            self.current_song = self.queue.pop(0)
            await self._play_song(self.current_song)
            
            if self.loop_queue:
                self.queue.append(self.current_song)
        else:
            self.current_song = None
            self.is_playing = False
            if not self.is_jazz_mode:
                # Only set idle timer if not in jazz mode (jazz mode will auto-play next)
                import time
                self.idle_since = time.time()
            await self.cog.update_control_embed(self.guild)
    
    async def play_random_jazz(self):
        """Play a random jazz track from the jazz folder"""
        jazz_files = list(JAZZ_FOLDER.glob("*.mp3"))
        if not jazz_files:
            self.is_playing = False
            self.current_song = None
            return
        
        # Pick random file
        random_file = random.choice(jazz_files)
        
        # Get file duration to calculate random start position
        # For now, we'll use a simple approach: start at random point (max 80% through)
        # We'll need to get duration from FFprobe or estimate
        
        song = Song(
            source=str(random_file.absolute()),
            title=f"🎷 {random_file.stem}",
            is_local=True,
            start_time=0  # Will be set by FFmpeg
        )
        
        self.current_song = song
        await self._play_song(song, is_jazz=True)
    
    async def _play_song(self, song: Song, is_jazz: bool = False):
        """Internal method to play a song"""
        if not self.voice_client or not self.voice_client.is_connected():
            return
        
        try:
            if song.is_local:
                # For jazz mode with random start, use FFmpeg with -ss option
                if is_jazz and song.start_time == 0:
                    # Get file duration first (simplified - assume long files)
                    # Start at random position (0-80% of file)
                    # For 10-hour files, max start would be ~8 hours
                    max_start_seconds = 8 * 3600  # 8 hours
                    song.start_time = random.randint(0, max_start_seconds)
                
                ffmpeg_opts = FFMPEG_OPTIONS.copy()
                if song.start_time > 0:
                    # Add seek option to start at random position
                    ffmpeg_opts['before_options'] += f' -ss {song.start_time}'
                
                source = nextcord.FFmpegPCMAudio(song.source, **ffmpeg_opts)
            else:
                # Stream from URL using yt-dlp
                ydl_opts = YDL_OPTIONS.copy()
                ydl_opts['format'] = 'bestaudio/best'
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(song.source, download=False)
                    url = info.get('url') or info.get('requested_formats', [{}])[0].get('url')
                    
                    if not url:
                        raise Exception("Could not extract audio URL")
                    
                    source = nextcord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
            
            def after_playing(error):
                if error:
                    print(f"Error in playback: {error}")
                asyncio.create_task(self.play_next())
            
            self.voice_client.play(source, after=after_playing)
            self.is_playing = True
            self.is_paused = False
            self.idle_since = None  # Reset idle timer
            
            # Update control embed
            await self.cog.update_control_embed(self.guild)
            
        except Exception as e:
            print(f"Error playing song: {e}")
            await self.play_next()
    
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


class MusicCog(commands.Cog):
    """Discord Music Bot Cog"""
    def __init__(self, bot):
        self.bot = bot
        self.players: Dict[int, MusicPlayer] = {}  # guild_id -> MusicPlayer
        self.cleanup_task.start()
        print("Initializing MusicCog.")
    
    async def cog_load(self):
        """Initialize database tables"""
        await self.create_tables()
        # Register persistent views
        self.bot.add_view(MusicControlView(self, GUILD_ID))
    
    async def create_tables(self):
        """Create database tables for music settings"""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS music_settings (
                    guild_id INTEGER PRIMARY KEY,
                    voting_skip_enabled BOOLEAN NOT NULL DEFAULT 0,
                    voting_skip_percentage REAL NOT NULL DEFAULT 0.2
                )
            ''')
            await db.commit()
        print("Music database tables created/verified successfully.")
    
    async def get_voting_skip_enabled(self, guild_id: int) -> bool:
        """Get whether voting skip is enabled for a guild"""
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT voting_skip_enabled FROM music_settings WHERE guild_id = ?',
                (guild_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return bool(row['voting_skip_enabled'])
                # Default: disabled
                return False
    
    async def set_voting_skip_enabled(self, guild_id: int, enabled: bool):
        """Set whether voting skip is enabled for a guild"""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                INSERT OR REPLACE INTO music_settings (guild_id, voting_skip_enabled, voting_skip_percentage)
                VALUES (?, ?, 0.2)
            ''', (guild_id, 1 if enabled else 0))
            await db.commit()
    
    async def get_voting_skip_percentage(self, guild_id: int) -> float:
        """Get the voting skip percentage threshold"""
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT voting_skip_percentage FROM music_settings WHERE guild_id = ?',
                (guild_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return float(row['voting_skip_percentage'])
                return 0.2  # Default: 20%
    
    async def set_voting_skip_percentage(self, guild_id: int, percentage: float):
        """Set the voting skip percentage threshold"""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                INSERT OR REPLACE INTO music_settings (guild_id, voting_skip_enabled, voting_skip_percentage)
                VALUES (?, COALESCE((SELECT voting_skip_enabled FROM music_settings WHERE guild_id = ?), 0), ?)
            ''', (guild_id, guild_id, percentage))
            await db.commit()
    
    def get_player(self, guild: nextcord.Guild) -> MusicPlayer:
        """Get or create a music player for a guild"""
        if guild.id not in self.players:
            self.players[guild.id] = MusicPlayer(guild, self)
        return self.players[guild.id]
    
    def create_control_embed(self, player: MusicPlayer) -> nextcord.Embed:
        """Create the control embed"""
        embed = nextcord.Embed(
            title="🎵 Music Player",
            color=0x00ff00 if player.is_playing else 0x808080
        )
        
        if player.current_song:
            status = "⏸️ Paused" if player.is_paused else "▶️ Playing"
            embed.add_field(
                name=f"{status} - Now Playing",
                value=f"**{player.current_song.title}**",
                inline=False
            )
            
            if player.current_song.uploader:
                embed.add_field(name="Uploader", value=player.current_song.uploader, inline=True)
            
            if player.is_jazz_mode:
                embed.add_field(name="Mode", value="🎷 Jazz Mode", inline=True)
        else:
            embed.add_field(
                name="Status",
                value="⏹️ Nothing playing",
                inline=False
            )
        
        if player.queue:
            queue_preview = "\n".join([f"{i+1}. {song.title}" for i, song in enumerate(player.queue[:5])])
            if len(player.queue) > 5:
                queue_preview += f"\n... and {len(player.queue) - 5} more"
            embed.add_field(name="📋 Queue", value=queue_preview or "Empty", inline=False)
        
        # Note: Voting status will be updated via update_control_embed which is async
        
        return embed
    
    async def update_control_embed(self, guild: nextcord.Guild):
        """Update the control embed for a guild"""
        player = self.get_player(guild)
        if player.control_message:
            try:
                embed = await self.create_control_embed_async(player)
                view = MusicControlView(self, guild.id)
                self.bot.add_view(view)
                await player.control_message.edit(embed=embed, view=view)
            except Exception as e:
                print(f"Error updating control embed: {e}")
    
    async def create_control_embed_async(self, player: MusicPlayer) -> nextcord.Embed:
        """Create the control embed (async version with voting info)"""
        embed = self.create_control_embed(player)
        
        # Add voting status if enabled
        voting_enabled = await self.get_voting_skip_enabled(player.guild.id)
        if voting_enabled:
            if player.current_song and player.current_skip_song_id:
                votes_needed = await self.calculate_votes_needed(player)
                current_votes = len(player.skip_votes)
                embed.add_field(
                    name="⏭️ Skip Votes",
                    value=f"{current_votes}/{votes_needed} votes",
                    inline=True
                )
        
        return embed
    
    async def calculate_votes_needed(self, player: MusicPlayer) -> int:
        """Calculate how many votes are needed to skip"""
        if not player.voice_client or not player.voice_client.channel:
            return 1
        
        # Count non-bot members in voice channel
        members = [m for m in player.voice_client.channel.members if not m.bot]
        total_members = len(members)
        
        if total_members == 0:
            return 1
        
        # Get percentage threshold
        try:
            percentage = await self.get_voting_skip_percentage(player.guild.id)
        except:
            percentage = 0.2  # Default 20%
        
        votes_needed = max(1, math.ceil(total_members * percentage))
        return votes_needed
    
    async def handle_vote_skip(self, interaction: nextcord.Interaction):
        """Handle a vote to skip request"""
        player = self.get_player(interaction.guild)
        
        if not player.current_song:
            await interaction.response.send_message("❌ Nothing is currently playing!", ephemeral=True)
            return
        
        # Create unique song ID for this skip vote session
        song_id = f"{player.current_song.source}_{player.current_song.start_time}"
        
        # If this is a new song, reset votes
        if player.current_skip_song_id != song_id:
            player.skip_votes.clear()
            player.current_skip_song_id = song_id
        
        # Add user's vote
        if interaction.user.id in player.skip_votes:
            await interaction.response.send_message("❌ You've already voted to skip!", ephemeral=True)
            return
        
        player.skip_votes.add(interaction.user.id)
        
        # Check if threshold is met
        votes_needed = await self.calculate_votes_needed(player)
        current_votes = len(player.skip_votes)
        
        if current_votes >= votes_needed:
            # Skip the song
            player.skip()
            await interaction.response.send_message(f"✅ Skip vote passed! ({current_votes}/{votes_needed})", ephemeral=False)
            await self.update_control_embed(interaction.guild)
        else:
            await interaction.response.send_message(
                f"👍 Vote recorded! ({current_votes}/{votes_needed} votes needed)",
                ephemeral=True
            )
            await self.update_control_embed(interaction.guild)
    
    async def handle_vote_skip_vote(self, interaction: nextcord.Interaction, song_id: str):
        """Handle a vote from the vote skip button"""
        player = self.get_player(interaction.guild)
        
        if player.current_skip_song_id != song_id:
            await interaction.response.send_message("❌ This vote is for a different song!", ephemeral=True)
            return
        
        if interaction.user.id in player.skip_votes:
            await interaction.response.send_message("❌ You've already voted to skip!", ephemeral=True)
            return
        
        player.skip_votes.add(interaction.user.id)
        
        votes_needed = await self.calculate_votes_needed(player)
        current_votes = len(player.skip_votes)
        
        if current_votes >= votes_needed:
            player.skip()
            await interaction.response.send_message(f"✅ Skip vote passed! ({current_votes}/{votes_needed})", ephemeral=False)
            await self.update_control_embed(interaction.guild)
        else:
            await interaction.response.send_message(
                f"👍 Vote recorded! ({current_votes}/{votes_needed} votes needed)",
                ephemeral=True
            )
            await self.update_control_embed(interaction.guild)
    
    async def show_settings(self, interaction: nextcord.Interaction):
        """Show settings menu for admins"""
        voting_enabled = await self.get_voting_skip_enabled(interaction.guild.id)
        voting_percentage = await self.get_voting_skip_percentage(interaction.guild.id)
        
        embed = nextcord.Embed(
            title="⚙️ Music Bot Settings",
            description="Configure music bot settings",
            color=0x0099ff
        )
        
        embed.add_field(
            name="Voting Skip",
            value="✅ Enabled" if voting_enabled else "❌ Disabled",
            inline=True
        )
        
        embed.add_field(
            name="Vote Threshold",
            value=f"{voting_percentage * 100:.0f}%",
            inline=True
        )
        
        view = SettingsView(self, interaction.guild.id)
        
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    def is_url(self, query: str) -> bool:
        """Check if query is a URL"""
        url_pattern = re.compile(
            r'^https?://'
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
            r'localhost|'
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
            r'(?::\d+)?'
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)
        return url_pattern.match(query) is not None
    
    def is_local_file(self, query: str) -> bool:
        """Check if query is a local file path"""
        return os.path.exists(query) and os.path.isfile(query)
    
    async def extract_song_info(self, query: str, is_local: bool = False) -> List[Song]:
        """Extract song information from a URL, search query, or local file"""
        songs = []
        
        if is_local:
            file_path = Path(query)
            if file_path.exists() and file_path.is_file():
                song = Song(
                    source=str(file_path.absolute()),
                    title=file_path.stem,
                    is_local=True
                )
                songs.append(song)
            return songs
        
        ydl_opts = YDL_OPTIONS.copy()
        is_playlist = any(keyword in query.lower() for keyword in ['playlist', 'list=', '&list='])
        
        if is_playlist:
            ydl_opts['extract_flat'] = True
            ydl_opts['noplaylist'] = False
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=False)
                
                if 'entries' in info:
                    for entry in info['entries']:
                        if entry:
                            if ydl_opts.get('extract_flat'):
                                try:
                                    full_info = ydl.extract_info(entry['url'] or entry['id'], download=False)
                                    song = self._create_song_from_info(full_info)
                                except:
                                    song = Song(
                                        source=entry.get('url', query),
                                        title=entry.get('title', 'Unknown'),
                                        duration=entry.get('duration'),
                                        webpage_url=entry.get('url', query)
                                    )
                            else:
                                song = self._create_song_from_info(entry)
                            
                            if song:
                                songs.append(song)
                else:
                    song = self._create_song_from_info(info)
                    if song:
                        songs.append(song)
        
        except Exception as e:
            print(f"Error extracting song info: {e}")
            raise Exception(f"Could not extract audio information: {str(e)}")
        
        return songs
    
    def _create_song_from_info(self, info: Dict) -> Optional[Song]:
        """Create a Song object from yt-dlp info dictionary"""
        try:
            url = info.get('url')
            if not url and 'requested_formats' in info and info['requested_formats']:
                url = info['requested_formats'][0].get('url')
            if not url:
                url = info.get('webpage_url') or info.get('id')
            
            return Song(
                source=url or info.get('webpage_url', ''),
                title=info.get('title', 'Unknown'),
                duration=info.get('duration'),
                uploader=info.get('uploader') or info.get('channel'),
                webpage_url=info.get('webpage_url'),
                thumbnail=info.get('thumbnail')
            )
        except Exception as e:
            print(f"Error creating song from info: {e}")
            return None
    
    @nextcord.slash_command(name="music", description="Music player commands", guild_ids=[GUILD_ID])
    async def music(self, interaction: nextcord.Interaction):
        pass
    
    @music.subcommand(name="play", description="Play a song from YouTube, YouTube Music, SoundCloud, or a local file")
    async def play(
        self,
        interaction: nextcord.Interaction,
        query: str = SlashOption(description="Song URL, search query, or local file path")
    ):
        """Play a song or add it to the queue"""
        await interaction.response.defer()
        
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send("❌ You need to be in a voice channel to use this command!")
            return
        
        voice_channel = interaction.user.voice.channel
        player = self.get_player(interaction.guild)
        
        if not player.voice_client or not player.voice_client.is_connected():
            connected = await player.connect(voice_channel, interaction.channel)
            if not connected:
                await interaction.followup.send("❌ Could not connect to voice channel!")
                return
        
        is_local = self.is_local_file(query)
        
        try:
            await interaction.followup.send(f"🔍 Searching for: `{query}`...")
            songs = await self.extract_song_info(query, is_local=is_local)
            
            if not songs:
                await interaction.followup.send("❌ No songs found!")
                return
            
            for song in songs:
                player.add_to_queue(song)
            
            if not player.is_playing:
                await player.play_next()
                await interaction.followup.send(f"▶️ Now playing: **{player.current_song}**")
            else:
                if len(songs) == 1:
                    await interaction.followup.send(f"✅ Added to queue: **{songs[0]}** (Position: {len(player.queue)})")
                else:
                    await interaction.followup.send(f"✅ Added {len(songs)} songs to queue!")
                await self.update_control_embed(interaction.guild)
        
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {str(e)}")
    
    @nextcord.slash_command(name="jazz", description="Start jazz mode - plays random jazz tracks from local library", guild_ids=[GUILD_ID])
    async def jazz(self, interaction: nextcord.Interaction):
        """Start jazz mode"""
        await interaction.response.defer()
        
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send("❌ You need to be in a voice channel to use this command!")
            return
        
        # Check if jazz folder exists and has files
        if not JAZZ_FOLDER.exists() or not list(JAZZ_FOLDER.glob("*.mp3")):
            await interaction.followup.send("❌ Jazz folder not found or empty!")
            return
        
        voice_channel = interaction.user.voice.channel
        player = self.get_player(interaction.guild)
        
        # Clear queue and enable jazz mode
        player.clear_queue()
        player.is_jazz_mode = True
        
        if not player.voice_client or not player.voice_client.is_connected():
            connected = await player.connect(voice_channel, interaction.channel)
            if not connected:
                await interaction.followup.send("❌ Could not connect to voice channel!")
                return
        
        await player.play_random_jazz()
        await interaction.followup.send("🎷 Jazz mode activated! Playing random jazz tracks...")
        await self.update_control_embed(interaction.guild)
    
    @music.subcommand(name="skip", description="Skip the current song")
    async def skip(self, interaction: nextcord.Interaction):
        """Skip the current song"""
        player = self.get_player(interaction.guild)
        
        if not player.is_playing:
            await interaction.response.send_message("❌ Nothing is currently playing!")
            return
        
        voting_enabled = await self.get_voting_skip_enabled(interaction.guild.id)
        
        if voting_enabled:
            await self.handle_vote_skip(interaction)
        else:
            player.skip()
            await interaction.response.send_message("⏭️ Skipped!")
            await self.update_control_embed(interaction.guild)
    
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
        await self.update_control_embed(interaction.guild)
    
    @music.subcommand(name="resume", description="Resume playback")
    async def resume(self, interaction: nextcord.Interaction):
        """Resume playback"""
        player = self.get_player(interaction.guild)
        
        if not player.is_paused:
            await interaction.response.send_message("❌ Playback is not paused!")
            return
        
        player.resume()
        await interaction.response.send_message("▶️ Resumed!")
        await self.update_control_embed(interaction.guild)
    
    @music.subcommand(name="stop", description="Stop playback and clear queue")
    async def stop(self, interaction: nextcord.Interaction):
        """Stop playback and clear queue"""
        player = self.get_player(interaction.guild)
        
        player.clear_queue()
        player.is_jazz_mode = False
        player.skip()
        await interaction.response.send_message("⏹️ Stopped and cleared queue!")
        await self.update_control_embed(interaction.guild)
    
    @music.subcommand(name="queue", description="Show the current queue")
    async def queue(self, interaction: nextcord.Interaction):
        """Show the current queue"""
        player = self.get_player(interaction.guild)
        
        if not player.current_song and not player.queue:
            await interaction.response.send_message("❌ Queue is empty!")
            return
        
        embed = nextcord.Embed(title="🎵 Music Queue", color=0x00ff00)
        
        if player.current_song:
            embed.add_field(
                name="▶️ Now Playing",
                value=f"**{player.current_song}**",
                inline=False
            )
        
        if player.queue:
            queue_text = "\n".join([f"{i+1}. {song}" for i, song in enumerate(player.queue[:10])])
            if len(player.queue) > 10:
                queue_text += f"\n... and {len(player.queue) - 10} more"
            embed.add_field(name="📋 Up Next", value=queue_text, inline=False)
        else:
            embed.add_field(name="📋 Up Next", value="No songs in queue", inline=False)
        
        await interaction.response.send_message(embed=embed)
    
    @music.subcommand(name="nowplaying", description="Show the currently playing song")
    async def nowplaying(self, interaction: nextcord.Interaction):
        """Show the currently playing song"""
        player = self.get_player(interaction.guild)
        
        if not player.current_song:
            await interaction.response.send_message("❌ Nothing is currently playing!")
            return
        
        embed = nextcord.Embed(
            title="🎵 Now Playing",
            description=f"**{player.current_song.title}**",
            color=0x00ff00
        )
        
        if player.current_song.uploader:
            embed.add_field(name="Uploader", value=player.current_song.uploader, inline=True)
        
        if player.current_song.duration:
            embed.add_field(name="Duration", value=player.current_song.format_duration(), inline=True)
        
        if player.current_song.webpage_url:
            embed.add_field(name="Link", value=f"[Click here]({player.current_song.webpage_url})", inline=False)
        
        if player.current_song.thumbnail:
            embed.set_thumbnail(url=player.current_song.thumbnail)
        
        await interaction.response.send_message(embed=embed)
    
    @music.subcommand(name="disconnect", description="Disconnect from voice channel")
    async def disconnect(self, interaction: nextcord.Interaction):
        """Disconnect from voice channel"""
        player = self.get_player(interaction.guild)
        await player.disconnect()
        await interaction.response.send_message("👋 Disconnected from voice channel!")
    
    @music.subcommand(name="loop", description="Toggle loop mode (song or queue)")
    async def loop(
        self,
        interaction: nextcord.Interaction,
        mode: str = SlashOption(
            description="Loop mode",
            choices={"song": "song", "queue": "queue", "off": "off"}
        )
    ):
        """Toggle loop mode"""
        player = self.get_player(interaction.guild)
        
        if mode == "song":
            player.loop = True
            player.loop_queue = False
            await interaction.response.send_message("🔁 Looping current song!")
        elif mode == "queue":
            player.loop = False
            player.loop_queue = True
            await interaction.response.send_message("🔁 Looping queue!")
        else:
            player.loop = False
            player.loop_queue = False
            await interaction.response.send_message("🔁 Loop disabled!")
    
    @tasks.loop(seconds=30)
    async def cleanup_task(self):
        """Cleanup task to handle edge cases and auto-disconnect"""
        await self.bot.wait_until_ready()
        
        import time
        current_time = time.time()
        
        for guild_id, player in list(self.players.items()):
            try:
                # Check if voice client exists and is connected
                if player.voice_client:
                    # Check if alone in channel
                    if player.voice_client.channel:
                        members = [m for m in player.voice_client.channel.members if not m.bot]
                        
                        # If not playing and queue is empty and not paused
                        if not player.is_playing and not player.queue and not player.is_paused:
                            # Set idle timer if not set
                            if player.idle_since is None:
                                player.idle_since = current_time
                            
                            # If alone and idle for 5 minutes, disconnect
                            if len(members) == 0 and player.idle_since:
                                if current_time - player.idle_since >= 300:  # 5 minutes
                                    await player.disconnect()
                                    print(f"Auto-disconnected from {player.guild.name} - idle for 5 minutes")
                                    continue
                        else:
                            # Reset idle timer if playing
                            player.idle_since = None
                    
                    # Update control embed periodically (every 30 seconds)
                    await self.update_control_embed(player.guild)
                else:
                    # No voice client but player exists - clean up
                    if not player.is_playing and not player.queue:
                        del self.players[guild_id]
            except Exception as e:
                print(f"Error in cleanup task for {guild_id}: {e}")
    
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


class SettingsView(nextcord.ui.View):
    """View for music bot settings"""
    def __init__(self, cog_instance, guild_id: int):
        super().__init__(timeout=300)  # 5 minute timeout
        self.cog = cog_instance
        self.guild_id = guild_id
    
    @nextcord.ui.button(label="Toggle Voting Skip", style=nextcord.ButtonStyle.primary)
    async def toggle_voting(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id not in admin_user_ids:
            await interaction.response.send_message("❌ Only admins can change settings!", ephemeral=True)
            return
        
        current = await self.cog.get_voting_skip_enabled(self.guild_id)
        await self.cog.set_voting_skip_enabled(self.guild_id, not current)
        
        status = "enabled" if not current else "disabled"
        
        # Refresh settings embed
        voting_enabled = await self.cog.get_voting_skip_enabled(self.guild_id)
        voting_percentage = await self.cog.get_voting_skip_percentage(self.guild_id)
        
        embed = nextcord.Embed(
            title="⚙️ Music Bot Settings",
            description="Configure music bot settings",
            color=0x0099ff
        )
        
        embed.add_field(
            name="Voting Skip",
            value="✅ Enabled" if voting_enabled else "❌ Disabled",
            inline=True
        )
        
        embed.add_field(
            name="Vote Threshold",
            value=f"{voting_percentage * 100:.0f}%",
            inline=True
        )
        
        view = SettingsView(self.cog, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)
    
    @nextcord.ui.button(label="Set Vote %", style=nextcord.ButtonStyle.secondary)
    async def set_percentage(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id not in admin_user_ids:
            await interaction.response.send_message("❌ Only admins can change settings!", ephemeral=True)
            return
        
        modal = PercentageModal(self.cog, self.guild_id)
        await interaction.response.send_modal(modal)


class PercentageModal(nextcord.ui.Modal):
    """Modal for setting vote percentage"""
    def __init__(self, cog_instance, guild_id: int):
        super().__init__(title="Set Vote Percentage")
        self.cog = cog_instance
        self.guild_id = guild_id
        
        self.percentage_input = nextcord.ui.TextInput(
            label="Percentage (0-100)",
            placeholder="20",
            required=True,
            max_length=3
        )
        self.add_item(self.percentage_input)
    
    async def callback(self, interaction: nextcord.Interaction):
        try:
            percentage = float(self.percentage_input.value) / 100.0
            if percentage < 0 or percentage > 1:
                await interaction.response.send_message("❌ Percentage must be between 0 and 100!", ephemeral=True)
                return
            
            await self.cog.set_voting_skip_percentage(self.guild_id, percentage)
            await interaction.response.send_message(f"✅ Vote percentage set to {percentage * 100:.0f}%!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Invalid number!", ephemeral=True)


async def setup(bot):
    bot.add_cog(MusicCog(bot))
    print("MusicCog has been added to the bot.")
