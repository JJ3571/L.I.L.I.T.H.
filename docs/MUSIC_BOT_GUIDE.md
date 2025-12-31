# Modern Discord Music Bot Guide

## Overview

This guide explains how the modern Discord music bot works, including how it handles different media sources, playlists, and local files.

## Architecture

### Key Components

1. **MusicPlayer Class**: Manages playback for a single Discord guild
   - Queue management
   - Playback control (play, pause, resume, skip)
   - Loop modes (song, queue, off)
   - Voice client connection management

2. **Song Class**: Represents a single track
   - Stores metadata (title, duration, uploader, thumbnail)
   - Handles both local files and remote URLs
   - Formats duration for display

3. **MusicCog Class**: Discord bot commands
   - Slash commands for user interaction
   - Song extraction and queue management
   - Error handling

## Using yt-dlp as a Python Package

**Yes, you can absolutely use yt-dlp as a Python package!** It's the recommended approach for modern Discord music bots.

### Installation

```bash
pip install yt-dlp
```

### Why yt-dlp?

- **Active Development**: Regularly updated to handle YouTube changes
- **Multi-platform Support**: YouTube, YouTube Music, SoundCloud, Bandcamp, and 1000+ sites
- **Playlist Support**: Built-in playlist extraction
- **Flexible**: Can extract metadata, URLs, or download files
- **Python API**: Easy to integrate programmatically

### Basic Usage

```python
import yt_dlp

ydl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
}

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info(url, download=False)
    audio_url = info['url']
```

## Media Source Differences

### 1. Local Media vs Playlist Links

#### Local Media Files
- **Path**: Direct file system path (e.g., `C:/Music/song.mp3`)
- **Processing**: 
  - No network requests needed
  - Direct file access via `nextcord.FFmpegPCMAudio()`
  - Instant playback (no extraction delay)
- **Limitations**:
  - File must exist on bot's server
  - No metadata extraction (uses filename)
  - No thumbnails or rich embeds
- **Use Case**: Personal music library, custom sound effects

```python
# Local file handling
if os.path.exists(file_path):
    source = nextcord.FFmpegPCMAudio(file_path, **FFMPEG_OPTIONS)
```

#### Playlist Links
- **URLs**: YouTube playlists, YouTube Music playlists, SoundCloud playlists
- **Processing**:
  - yt-dlp extracts all entries from playlist
  - Each entry becomes a separate `Song` object
  - All songs added to queue automatically
- **Features**:
  - Full metadata for each track
  - Thumbnails and rich embeds
  - Can extract 100+ songs at once
- **Performance**:
  - Initial extraction may take time for large playlists
  - Use `extract_flat=True` for faster playlist info (metadata only)
  - Then extract full info per song as needed

```python
# Playlist detection
is_playlist = 'playlist' in url.lower() or 'list=' in url.lower()

if is_playlist:
    ydl_opts['extract_flat'] = True  # Fast extraction
    info = ydl.extract_info(url, download=False)
    # info['entries'] contains all playlist items
```

**Key Difference**: Local files are instant but limited. Playlists require network extraction but provide rich metadata and can queue many songs at once.

### 2. YouTube vs YouTube Music

#### YouTube Links
- **URL Format**: `https://www.youtube.com/watch?v=VIDEO_ID`
- **Content**: Music videos, live streams, user uploads
- **Audio Quality**: Varies (128kbps to 320kbps typically)
- **Metadata**: Title, uploader, duration, thumbnail
- **yt-dlp Support**: ✅ Full support

#### YouTube Music Links
- **URL Format**: `https://music.youtube.com/watch?v=VIDEO_ID` or `https://youtu.be/VIDEO_ID`
- **Content**: Official music tracks, albums, playlists
- **Audio Quality**: Often higher quality (up to 256kbps AAC)
- **Metadata**: More structured (artist, album, track number)
- **yt-dlp Support**: ✅ Full support (same as YouTube)

**Key Difference**: YouTube Music often has better audio quality and more structured metadata, but yt-dlp handles both identically. The bot doesn't need special handling - yt-dlp automatically detects and extracts from both.

### 3. Other Platforms

#### SoundCloud
- **URL Format**: `https://soundcloud.com/artist/track`
- **yt-dlp Support**: ✅ Full support
- **Special Features**: 
  - Can extract playlists
  - Supports private tracks (with authentication)
  - High-quality audio available

#### Spotify
- **URL Format**: `https://open.spotify.com/track/TRACK_ID`
- **yt-dlp Support**: ❌ **No direct playback** (DRM protected)
- **Workaround**: 
  - Use Spotify API to get track metadata
  - Search YouTube for the same track
  - Play YouTube version instead
- **Example Implementation**:
  ```python
  # Pseudo-code for Spotify handling
  if 'spotify.com' in url:
      # Extract track info from Spotify
      track_info = get_spotify_info(url)
      # Search YouTube for same track
      youtube_query = f"{track_info['artist']} {track_info['title']}"
      # Use YouTube result instead
      songs = await extract_song_info(youtube_query)
  ```

#### Other Supported Platforms
yt-dlp supports 1000+ sites including:
- Bandcamp
- Vimeo
- Twitch
- TikTok
- Twitter/X
- And many more!

## How the Bot Works

### Playback Flow

1. **User Command**: `/music play <query>`
2. **Query Detection**:
   - Check if it's a URL → Extract directly
   - Check if it's a local file → Use file path
   - Otherwise → Treat as search query (yt-dlp searches YouTube)
3. **Song Extraction**:
   - yt-dlp extracts audio URL and metadata
   - Creates `Song` objects (one or many for playlists)
4. **Queue Management**:
   - Adds songs to queue
   - If nothing playing, starts playback immediately
5. **Audio Streaming**:
   - FFmpeg streams audio from URL (or local file)
   - Plays through Discord voice connection
   - Automatically plays next song when current ends

### Queue System

```python
# Queue structure
queue: List[Song] = []  # FIFO queue
current_song: Optional[Song] = None  # Currently playing

# Adding songs
player.add_to_queue(song)  # Add to end
player.add_to_queue_front(song)  # Add to front (priority)

# Playing
await player.play_next()  # Pops from queue and plays
```

### Loop Modes

1. **Song Loop**: Repeats current song indefinitely
2. **Queue Loop**: When queue ends, starts from beginning
3. **Off**: Normal playback, stops when queue empty

## Commands

### `/music play <query>`
- Plays a song or adds to queue
- Supports: URLs, search queries, local files
- Auto-detects playlists and queues all songs

### `/music skip`
- Skips current song
- Plays next in queue

### `/music pause` / `/music resume`
- Pauses/resumes playback

### `/music stop`
- Stops playback and clears queue

### `/music queue`
- Shows current song and queue

### `/music nowplaying`
- Rich embed with current song info

### `/music loop <mode>`
- Set loop mode: song, queue, or off

### `/music disconnect`
- Disconnects from voice channel

## Technical Details

### FFmpeg Options

```python
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -filter:a "volume=0.8"'
}
```

- `-reconnect`: Handles network interruptions
- `-vn`: Video disabled (audio only)
- `volume=0.8`: 80% volume (prevents clipping)

### yt-dlp Options

```python
YDL_OPTIONS = {
    'format': 'bestaudio/best',  # Best quality audio
    'noplaylist': False,  # Allow playlists
    'quiet': True,  # Suppress output
    'extract_flat': False,  # Full extraction (slower but complete)
}
```

### Voice Connection

- Uses `nextcord.VoiceClient` for audio streaming
- Auto-reconnects on network issues
- Auto-disconnects when alone in channel (after 60s)

## Best Practices

1. **Error Handling**: Always wrap yt-dlp calls in try/except
2. **Rate Limiting**: Be mindful of YouTube rate limits
3. **Memory Management**: Clear queues when not needed
4. **User Feedback**: Provide clear messages for all actions
5. **Permissions**: Ensure bot has voice channel permissions

## Troubleshooting

### "Could not connect to voice channel"
- Check bot permissions (Connect, Speak)
- Ensure bot isn't already connected elsewhere
- Verify voice channel exists

### "No songs found"
- Check internet connection
- Verify URL is valid
- Try a different search query

### Audio cutting out
- Check network stability
- Increase reconnect delays in FFmpeg options
- Verify FFmpeg is installed correctly

### Playlist not working
- Ensure `noplaylist: False` in yt-dlp options
- Some playlists may be private/restricted
- Large playlists may timeout (use `extract_flat` for speed)

## Dependencies

- `nextcord`: Discord API wrapper
- `yt-dlp`: Audio extraction
- `PyNaCl`: Voice encryption
- `FFmpeg`: Audio processing (system dependency)

## Installation

1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Install FFmpeg:
   - **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html)
   - **Linux**: `sudo apt install ffmpeg`
   - **macOS**: `brew install ffmpeg`

3. Ensure FFmpeg is in your system PATH

4. Run the bot:
   ```bash
   python main.py
   ```

## Summary

- ✅ **yt-dlp works great as a Python package** for Discord music bots
- **Local files**: Instant but limited metadata
- **Playlists**: Rich metadata, can queue many songs
- **YouTube vs YouTube Music**: Same handling, Music often better quality
- **Spotify**: Requires workaround (search YouTube instead)
- **SoundCloud**: Full support via yt-dlp
- The bot automatically detects and handles all these cases!

