import nextcord
from nextcord.ext import commands
import aiosqlite
import os
import time, datetime
import pytz
import re

from server_configs.config import GUILD_ID
from server_configs.database_config import DATABASE_PATHS

class Event(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = DATABASE_PATHS["event"]
        # Initialize database when cog loads
        self.bot.loop.create_task(self.create_tables())

    async def create_tables(self):
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                # Events table
                await cursor.execute('''
                    CREATE TABLE IF NOT EXISTS events (
                        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        creator_id INTEGER NOT NULL,
                        event_name TEXT NOT NULL,
                        event_description TEXT,
                        event_time TIMESTAMP NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        max_attendees INTEGER DEFAULT NULL,
                        status TEXT DEFAULT 'active'
                    )
                ''')
                
                # Event attendees table
                await cursor.execute('''
                    CREATE TABLE IF NOT EXISTS event_attendees (
                        event_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        status TEXT DEFAULT 'confirmed',
                        PRIMARY KEY (event_id, user_id),
                        FOREIGN KEY (event_id) REFERENCES events (event_id) ON DELETE CASCADE
                    )
                ''')
            await conn.commit()

    async def create_event(self, creator_id: int, event_name: str, event_description: str, event_time: str, max_attendees: int = None):
        """Create a new event and return the event_id"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    INSERT INTO events (creator_id, event_name, event_description, event_time, max_attendees)
                    VALUES (?, ?, ?, ?, ?)
                ''', (creator_id, event_name, event_description, event_time, max_attendees))
                await conn.commit()
                return cursor.lastrowid

    async def get_event(self, event_id: int):
        """Get event details by event_id"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    SELECT event_id, creator_id, event_name, event_description, event_time, 
                           created_at, max_attendees, status
                    FROM events WHERE event_id = ?
                ''', (event_id,))
                return await cursor.fetchone()

    async def join_event(self, event_id: int, user_id: int, status: str = 'confirmed'):
        """Add a user to an event"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                try:
                    await cursor.execute('''
                        INSERT INTO event_attendees (event_id, user_id, status)
                        VALUES (?, ?, ?)
                    ''', (event_id, user_id, status))
                    await conn.commit()
                    return True
                except aiosqlite.IntegrityError:
                    # User already signed up
                    return False

    async def leave_event(self, event_id: int, user_id: int):
        """Remove a user from an event"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    DELETE FROM event_attendees 
                    WHERE event_id = ? AND user_id = ?
                ''', (event_id, user_id))
                await conn.commit()
                return cursor.rowcount > 0

    async def get_event_attendees(self, event_id: int):
        """Get all attendees for an event"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    SELECT user_id, joined_at, status
                    FROM event_attendees 
                    WHERE event_id = ?
                    ORDER BY joined_at ASC
                ''', (event_id,))
                return await cursor.fetchall()

    async def get_attendees_by_status(self, event_id: int, status: str = 'confirmed'):
        """Get attendees for an event by status"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    SELECT user_id, joined_at
                    FROM event_attendees 
                    WHERE event_id = ? AND status = ?
                    ORDER BY joined_at ASC
                ''', (event_id, status))
                return await cursor.fetchall()

    async def get_attendees_display_text(self, event_id: int):
        """Get formatted attendee text for embed display"""
        # Get confirmed attendees
        confirmed = await self.get_attendees_by_status(event_id, 'confirmed')
        alternates = await self.get_attendees_by_status(event_id, 'alternate')
        
        attendee_names = []
        alternate_names = []
        
        # Get confirmed attendee names
        for user_id, _ in confirmed:
            user = self.bot.get_user(user_id)
            name = user.display_name if user else f"User{user_id}"
            attendee_names.append(name)
        
        # Get alternate names
        for user_id, _ in alternates:
            user = self.bot.get_user(user_id)
            name = user.display_name if user else f"User{user_id}"
            alternate_names.append(f"{name}?")
        
        # Combine lists
        all_names = attendee_names + alternate_names
        
        if not all_names:
            return "None"
        
        # If too many attendees, truncate and show count
        if len(all_names) > 20:
            display_names = all_names[:15]
            remaining = len(all_names) - 15
            return f"{', '.join(display_names)}, +{remaining} more"
        else:
            return ', '.join(all_names)

    async def get_attendee_count(self, event_id: int):
        """Get the number of attendees for an event"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    SELECT COUNT(*) FROM event_attendees 
                    WHERE event_id = ? AND status = 'confirmed'
                ''', (event_id,))
                result = await cursor.fetchone()
                return result[0] if result else 0

    async def is_user_attending(self, event_id: int, user_id: int):
        """Check if a user is attending an event"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    SELECT 1 FROM event_attendees 
                    WHERE event_id = ? AND user_id = ?
                ''', (event_id, user_id))
                return await cursor.fetchone() is not None

    async def get_user_events(self, user_id: int):
        """Get all events a user is attending"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    SELECT e.event_id, e.event_name, e.event_time, e.creator_id
                    FROM events e
                    JOIN event_attendees ea ON e.event_id = ea.event_id
                    WHERE ea.user_id = ? AND e.status = 'active'
                    ORDER BY e.event_time ASC
                ''', (user_id,))
                return await cursor.fetchall()

    async def get_upcoming_events(self, limit: int = 10):
        """Get upcoming events"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    SELECT event_id, creator_id, event_name, event_description, event_time, 
                           created_at, max_attendees, status
                    FROM events 
                    WHERE status = 'active' AND event_time > datetime('now')
                    ORDER BY event_time ASC
                    LIMIT ?
                ''', (limit,))
                return await cursor.fetchall()
            
    async def update_event(self, event_id: int, name: str, description: str, event_time: str):
        """Update an existing event"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    UPDATE events
                    SET event_name = ?, event_description = ?, event_time = ?
                    WHERE event_id = ?
                ''', (name, description, event_time, event_id))
                await conn.commit()
                return cursor.rowcount > 0
            
    async def delete_event(self, event_id: int):
        """Delete an event by event_id"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    DELETE FROM events
                    WHERE event_id = ?
                ''', (event_id,))
                await conn.commit()
                return cursor.rowcount > 0

    @nextcord.slash_command(name="event", description="Create or manage events", guild_ids=[GUILD_ID])
    async def event_command(self, interaction: nextcord.Interaction):
        pass  # This will be the parent command

    @event_command.subcommand(name="create", description="Create a new event")
    async def create_event_command(self, interaction: nextcord.Interaction):
        """Create a new event using a modal"""
        modal = EventCreationModal(cog=self)
        await interaction.response.send_modal(modal)

    
    @event_command.subcommand(name="delete", description="Delete an event")
    async def delete_event_command(
        self, interaction: nextcord.Interaction, event_id: int
    ):
        """Delete an event"""
        await interaction.response.defer()

        # Check if the event exists
        event_data = await self.get_event(event_id)
        if not event_data:
            await interaction.followup.send("❌ This event does not exist!", ephemeral=True)
            return

        # Delete the event
        success = await self.delete_event(event_id)
        if success:
            await interaction.followup.send("✅ Event deleted successfully!", ephemeral=True)
        else:
            await interaction.followup.send("❌ Failed to delete the event!", ephemeral=True)

    @event_command.subcommand(name="edit", description="Edit an existing event")
    async def edit_event_command(
        self, interaction: nextcord.Interaction, event_id: int, name: str, description: str, event_time: str
    ):
        """Edit an existing event"""
        await interaction.response.defer()

        # Check if the event exists
        event_data = await self.get_event(event_id)
        if not event_data:
            await interaction.followup.send("❌ This event does not exist!", ephemeral=True)
            return

        # Update the event
        success = await self.update_event(event_id, name, description, event_time)
        if success:
            await interaction.followup.send("✅ Event updated successfully!", ephemeral=True)
        else:
            await interaction.followup.send("❌ Failed to update the event!", ephemeral=True)


    @event_command.subcommand(name="list", description="List all upcoming events")
    async def list_events_command(self, interaction: nextcord.Interaction):
        """List all upcoming events with dropdown selection"""
        await interaction.response.defer()

        events = await self.get_upcoming_events(limit=25)  # Get more events for dropdown
        if not events:
            await interaction.followup.send("❌ No upcoming events found!", ephemeral=True)
            return

        # Create dropdown view
        view = EventListView(events=events, cog=self)
        
        # Create initial embed
        embed = nextcord.Embed(
            title="📅 Upcoming Events",
            description="Select an event from the dropdown below to interact with it.",
            color=nextcord.Color.blurple()
        )
        embed.add_field(
            name="📋 Instructions",
            value="• Use the dropdown to select an event\n• Join, leave, or view attendees\n• Event details will be shown after selection",
            inline=False
        )
        embed.set_footer(text=f"Found {len(events)} upcoming events")

        await interaction.followup.send(embed=embed, view=view)

    def parse_datetime_string(self, datetime_str: str):
        """
        Parse flexible datetime strings like:
        - 6/29 11:00am PST
        - 12/25 14:30 EST
        - 2025/06/29 23:45 UTC
        - 06/29/2025 11am PDT
        """
        # Remove extra whitespace and normalize
        datetime_str = ' '.join(datetime_str.split())
        
        # Timezone mapping
        timezone_map = {
            'PST': 'US/Pacific', 'PDT': 'US/Pacific',
            'EST': 'US/Eastern', 'EDT': 'US/Eastern',
            'CST': 'US/Central', 'CDT': 'US/Central',
            'MST': 'US/Mountain', 'MDT': 'US/Mountain',
            'UTC': 'UTC', 'GMT': 'GMT'
        }
        
        # Extract timezone from end of string
        timezone_pattern = r'\b(PST|PDT|EST|EDT|CST|CDT|MST|MDT|UTC|GMT)\b$'
        tz_match = re.search(timezone_pattern, datetime_str, re.IGNORECASE)
        
        if tz_match:
            tz_abbr = tz_match.group(1).upper()
            tz_name = timezone_map[tz_abbr]
            datetime_str = datetime_str[:tz_match.start()].strip()
        else:
            tz_abbr = 'UTC'
            tz_name = 'UTC'
        
        # Parse time with AM/PM support
        time_patterns = [
            r'(\d{1,2}):(\d{2})\s*(am|pm|a\.m\.?|p\.m\.?)',  # 11:30am, 2:45 p.m.
            r'(\d{1,2})(am|pm|a\.m\.?|p\.m\.?)',             # 11am, 2pm
            r'(\d{1,2}):(\d{2})',                            # 14:30 (24hr)
            r'(\d{1,2})'                                     # 14 (assume :00)
        ]
        
        time_str = None
        date_str = None
        
        # Try to find time pattern
        for pattern in time_patterns:
            time_match = re.search(pattern, datetime_str, re.IGNORECASE)
            if time_match:
                time_str = time_match.group(0)
                date_str = datetime_str.replace(time_str, '').strip()
                break
        
        if not time_str:
            raise ValueError("No valid time found in input")
        
        # Parse the time
        hour, minute, is_pm = self.parse_time(time_str)
        
        # Parse the date
        year, month, day = self.parse_date(date_str)
        
        # Create datetime object
        naive_dt = datetime.datetime(year, month, day, hour, minute)
        
        # Localize to timezone
        tz = pytz.timezone(tz_name)
        localized_dt = tz.localize(naive_dt)
        
        # Convert to UTC
        utc_dt = localized_dt.astimezone(pytz.UTC)
        
        return utc_dt, tz_abbr, tz_name
    
    def parse_time(self, time_str: str):
        """Parse time string and return hour, minute, is_pm"""
        time_str = time_str.lower().strip()
        
        # Check for AM/PM
        is_pm = any(marker in time_str for marker in ['pm', 'p.m', 'p.m.'])
        is_am = any(marker in time_str for marker in ['am', 'a.m', 'a.m.'])
        
        # Remove AM/PM markers
        for marker in ['am', 'pm', 'a.m.', 'p.m.', 'a.m', 'p.m']:
            time_str = time_str.replace(marker, '').strip()
        
        # Parse hour and minute
        if ':' in time_str:
            hour_str, minute_str = time_str.split(':')
            hour = int(hour_str)
            minute = int(minute_str)
        else:
            hour = int(time_str)
            minute = 0
        
        # Convert 12-hour to 24-hour
        if is_pm and hour != 12:
            hour += 12
        elif is_am and hour == 12:
            hour = 0
        
        return hour, minute, is_pm
    
    def parse_date(self, date_str: str):
        """Parse date string and return year, month, day"""
        date_str = date_str.strip()
        current_year = nextcord.utils.utcnow().year
        
        # Date patterns: M/DD, MM/DD, MM/DD/YYYY, YYYY/MM/DD
        date_patterns = [
            r'^(\d{4})/(\d{1,2})/(\d{1,2})$',  # YYYY/MM/DD
            r'^(\d{1,2})/(\d{1,2})/(\d{4})$',  # MM/DD/YYYY
            r'^(\d{1,2})/(\d{1,2})$'           # M/DD or MM/DD
        ]
        
        for i, pattern in enumerate(date_patterns):
            match = re.match(pattern, date_str)
            if match:
                if i == 0:  # YYYY/MM/DD
                    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
                elif i == 1:  # MM/DD/YYYY
                    month, day, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
                else:  # M/DD or MM/DD (assume current year)
                    month, day = int(match.group(1)), int(match.group(2))
                    year = current_year
                    
                    # If the date is in the past this year, assume next year
                    test_date = datetime.date(year, month, day)
                    if test_date < nextcord.utils.utcnow().date():
                        year += 1
                
                return year, month, day
        
        raise ValueError(f"Invalid date format: {date_str}")


# Event UI View Class
class EventView(nextcord.ui.View):
    def __init__(self, event_id: int, cog):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.cog = cog

    @nextcord.ui.button(label="✅ Join Event", style=nextcord.ButtonStyle.green)
    async def join_event(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        """Handle user joining the event"""
        # Check if event exists and is active
        event_data = await self.cog.get_event(self.event_id)
        if not event_data:
            await interaction.response.send_message("❌ This event no longer exists!", ephemeral=True)
            return
        
        # Check if user is already attending
        if await self.cog.is_user_attending(self.event_id, interaction.user.id):
            await interaction.response.send_message("❌ You're already signed up for this event!", ephemeral=True)
            return
        
        # Check if event is full
        current_count = await self.cog.get_attendee_count(self.event_id)
        max_attendees = event_data[6]  # max_attendees column
        
        if max_attendees and current_count >= max_attendees:
            await interaction.response.send_message("❌ This event is full!", ephemeral=True)
            return
        
        # Join the event
        success = await self.cog.join_event(self.event_id, interaction.user.id)
        if success:
            # Update the embed with new attendee count
            await self.update_embed(interaction)
            await interaction.followup.send(f"✅ {interaction.user.mention} joined the event!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Failed to join the event!", ephemeral=True)

    @nextcord.ui.button(label="❌ Leave Event", style=nextcord.ButtonStyle.red)
    async def leave_event(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        """Handle user leaving the event"""
        # Check if user is attending
        if not await self.cog.is_user_attending(self.event_id, interaction.user.id):
            await interaction.response.send_message("❌ You're not signed up for this event!", ephemeral=True)
            return
        
        # Leave the event
        success = await self.cog.leave_event(self.event_id, interaction.user.id)
        if success:
            # Update the embed with new attendee count
            await self.update_embed(interaction)
            await interaction.followup.send(f"✅ {interaction.user.mention} left the event!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Failed to leave the event!", ephemeral=True)

    @nextcord.ui.button(label="👥 View Attendees", style=nextcord.ButtonStyle.blurple)
    async def view_attendees(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        """Show list of attendees"""
        attendees = await self.cog.get_event_attendees(self.event_id)
        
        if not attendees:
            await interaction.response.send_message("📭 No one has signed up for this event yet!", ephemeral=True)
            return
        
        # Create attendees list
        attendee_list = []
        for user_id, joined_at, status in attendees:
            user = self.cog.bot.get_user(user_id)
            name = user.display_name if user else f"User {user_id}"
            attendee_list.append(f"• {name}")
        
        embed = nextcord.Embed(
            title=f"👥 Event Attendees ({len(attendees)})",
            description="\n".join(attendee_list[:20]),  # Limit to first 20
            color=0x0099ff
        )
        
        if len(attendees) > 20:
            embed.set_footer(text=f"... and {len(attendees) - 20} more")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def update_embed(self, interaction: nextcord.Interaction):
        """Update the event embed with current attendee count"""
        try:
            # Get current attendee count
            count = await self.cog.get_attendee_count(self.event_id)
            
            # Get the original embed and update attendee count
            embed = interaction.message.embeds[0]
            
            # Find and update the attendees field
            for i, field in enumerate(embed.fields):
                if field.name == "👥 Attendees":
                    embed.set_field_at(i, name="👥 Attendees", value=str(count), inline=True)
                    break
            
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            print(f"Error updating embed: {e}")


# Event List View with Dropdown
class EventListView(nextcord.ui.View):
    def __init__(self, events, cog):
        super().__init__(timeout=300)
        self.events = events
        self.cog = cog
        self.selected_event_id = None
        
        # Add dropdown
        self.add_item(EventDropdown(events=events, view=self))
        
        # Add interaction buttons (initially disabled)
        self.join_button = nextcord.ui.Button(
            label="✅ Join Event", 
            style=nextcord.ButtonStyle.green, 
            disabled=True
        )
        self.join_button.callback = self.join_event
        self.add_item(self.join_button)
        
        self.join_alternate_button = nextcord.ui.Button(
            label="? Join as Alternate", 
            style=nextcord.ButtonStyle.secondary, 
            disabled=True
        )
        self.join_alternate_button.callback = self.join_alternate
        self.add_item(self.join_alternate_button)
        
        self.leave_button = nextcord.ui.Button(
            label="❌ Leave Event", 
            style=nextcord.ButtonStyle.red, 
            disabled=True
        )
        self.leave_button.callback = self.leave_event
        self.add_item(self.leave_button)
        
        # View attendees button (will be added conditionally)
        self.attendees_button = nextcord.ui.Button(
            label="👥 View Attendees", 
            style=nextcord.ButtonStyle.blurple, 
            disabled=True
        )
        self.attendees_button.callback = self.view_attendees
    
    async def update_for_selected_event(self, interaction: nextcord.Interaction, event_id: int):
        """Update the embed and enable buttons when an event is selected"""
        self.selected_event_id = event_id
        
        # Get event details
        event_data = await self.cog.get_event(event_id)
        if not event_data:
            await interaction.response.send_message("❌ Event not found!", ephemeral=True)
            return
        
        # Parse event data
        event_id, creator_id, event_name, event_description, event_time, created_at, max_attendees, status = event_data
        
        # Parse the event time for display
        event_datetime = datetime.datetime.fromisoformat(event_time.replace('Z', '+00:00'))
        attendee_count = await self.cog.get_attendee_count(event_id)
        attendees_text = await self.cog.get_attendees_display_text(event_id)
        
        # Create updated embed
        embed = nextcord.Embed(
            title=f"🎉 {event_name}",
            description=event_description,
            color=0x00ff00,
            timestamp=event_datetime
        )
        
        embed.add_field(
            name="📅 Event Time", 
            value=f"{nextcord.utils.format_dt(event_datetime, style='F')} ({nextcord.utils.format_dt(event_datetime, style='R')})", 
            inline=False
        )
        
        creator = self.cog.bot.get_user(creator_id)
        creator_mention = creator.mention if creator else f"User {creator_id}"
        
        embed.add_field(name="👤 Created by", value=creator_mention, inline=True)
        
        # Show attendees with names or use button for large lists
        if max_attendees and max_attendees > 20:
            embed.add_field(name="👥 Attendees", value=f"{attendee_count} attending", inline=True)
        else:
            embed.add_field(name="👥 Attendees", value=attendees_text, inline=False)
        
        if max_attendees:
            embed.add_field(name="📊 Max Attendees", value=str(max_attendees), inline=True)
        
        embed.set_footer(text=f"Event ID: {event_id}")
        
        # Enable buttons
        self.join_button.disabled = False
        self.join_alternate_button.disabled = False
        self.leave_button.disabled = False
        
        # Add view attendees button only for large events
        if max_attendees and max_attendees > 20:
            if self.attendees_button not in self.children:
                self.add_item(self.attendees_button)
            self.attendees_button.disabled = False
        else:
            # Remove button if it exists
            if self.attendees_button in self.children:
                self.remove_item(self.attendees_button)
        
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def join_event(self, interaction: nextcord.Interaction):
        """Handle joining the selected event"""
        if not self.selected_event_id:
            await interaction.response.send_message("❌ No event selected!", ephemeral=True)
            return
        
        # Check if user is already attending
        if await self.cog.is_user_attending(self.selected_event_id, interaction.user.id):
            await interaction.response.send_message("❌ You're already signed up for this event!", ephemeral=True)
            return
        
        # Check if event is full
        event_data = await self.cog.get_event(self.selected_event_id)
        current_count = await self.cog.get_attendee_count(self.selected_event_id)
        max_attendees = event_data[6] if event_data else None
        
        if max_attendees and current_count >= max_attendees:
            await interaction.response.send_message("❌ This event is full!", ephemeral=True)
            return
        
        # Join the event
        success = await self.cog.join_event(self.selected_event_id, interaction.user.id)
        if success:
            await self.refresh_event_display(interaction)
            await interaction.followup.send(f"✅ {interaction.user.mention} joined the event!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Failed to join the event!", ephemeral=True)
    
    async def join_alternate(self, interaction: nextcord.Interaction):
        """Handle joining the selected event as an alternate"""
        if not self.selected_event_id:
            await interaction.response.send_message("❌ No event selected!", ephemeral=True)
            return
        
        # Check if user is already attending
        if await self.cog.is_user_attending(self.selected_event_id, interaction.user.id):
            await interaction.response.send_message("❌ You're already signed up for this event!", ephemeral=True)
            return
        
        # Join the event as alternate
        success = await self.cog.join_event(self.selected_event_id, interaction.user.id, status='alternate')
        if success:
            await self.refresh_event_display(interaction)
            await interaction.followup.send(f"? {interaction.user.mention} joined as an alternate!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Failed to join the event!", ephemeral=True)
    
    async def leave_event(self, interaction: nextcord.Interaction):
        """Handle leaving the selected event"""
        if not self.selected_event_id:
            await interaction.response.send_message("❌ No event selected!", ephemeral=True)
            return
        
        # Check if user is attending
        if not await self.cog.is_user_attending(self.selected_event_id, interaction.user.id):
            await interaction.response.send_message("❌ You're not signed up for this event!", ephemeral=True)
            return
        
        # Leave the event
        success = await self.cog.leave_event(self.selected_event_id, interaction.user.id)
        if success:
            await self.refresh_event_display(interaction)
            await interaction.followup.send(f"✅ {interaction.user.mention} left the event!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Failed to leave the event!", ephemeral=True)
    
    async def view_attendees(self, interaction: nextcord.Interaction):
        """Show attendees for the selected event"""
        if not self.selected_event_id:
            await interaction.response.send_message("❌ No event selected!", ephemeral=True)
            return
        
        attendees = await self.cog.get_event_attendees(self.selected_event_id)
        
        if not attendees:
            await interaction.response.send_message("📭 No one has signed up for this event yet!", ephemeral=True)
            return
        
        # Create attendees list with status
        confirmed_list = []
        alternate_list = []
        
        for user_id, joined_at, status in attendees:
            user = self.cog.bot.get_user(user_id)
            name = user.display_name if user else f"User {user_id}"
            
            if status == 'confirmed':
                confirmed_list.append(f"• {name}")
            elif status == 'alternate':
                alternate_list.append(f"• {name}?")
        
        # Build description
        description_parts = []
        if confirmed_list:
            description_parts.append("**Confirmed:**\n" + "\n".join(confirmed_list[:15]))
        if alternate_list:
            description_parts.append("**Alternates:**\n" + "\n".join(alternate_list[:10]))
        
        embed = nextcord.Embed(
            title=f"👥 Event Attendees ({len(attendees)})",
            description="\n\n".join(description_parts) if description_parts else "No attendees",
            color=0x0099ff
        )
        
        total_shown = len(confirmed_list[:15]) + len(alternate_list[:10])
        if len(attendees) > total_shown:
            embed.set_footer(text=f"... and {len(attendees) - total_shown} more")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def refresh_event_display(self, interaction: nextcord.Interaction):
        """Refresh the event display after a change"""
        if self.selected_event_id:
            await self.update_for_selected_event(interaction, self.selected_event_id)


class EventDropdown(nextcord.ui.Select):
    def __init__(self, events, view):
        self.view_parent = view
        
        # Create options from events
        options = []
        for event in events[:25]:  # Discord limit of 25 options
            event_id, creator_id, event_name, event_description, event_time, created_at, max_attendees, status = event
            
            # Parse event time for display
            try:
                event_datetime = datetime.datetime.fromisoformat(event_time.replace('Z', '+00:00'))
                # Use simple MM/DD HH:MM format for dropdown (Discord doesn't render timestamp formatting)
                time_str = event_datetime.strftime("%m/%d")
            except:
                time_str = "Unknown time"
            
            # Truncate name and description if too long
            display_name = event_name[:100] if len(event_name) <= 100 else event_name[:97] + "..."
            description = f"{time_str}" if len(time_str) <= 100 else time_str[:97] + "..."
            
            options.append(nextcord.SelectOption(
                label=display_name,
                description=description,
                value=str(event_id),
                emoji="🎉"
            ))
        
        super().__init__(
            placeholder="Choose an event to interact with...",
            min_values=1,
            max_values=1,
            options=options
        )
    
    async def callback(self, interaction: nextcord.Interaction):
        event_id = int(self.values[0])
        await self.view_parent.update_for_selected_event(interaction, event_id)


# Event Creation Modal
class EventCreationModal(nextcord.ui.Modal):
    def __init__(self, cog):
        super().__init__(title="Create New Event", timeout=300)
        self.cog = cog
        
        self.event_name = nextcord.ui.TextInput(
            label="Event Name",
            placeholder="Enter the name of your event...",
            required=True,
            max_length=100
        )
        self.add_item(self.event_name)
        
        self.event_datetime = nextcord.ui.TextInput(
            label="Date & Time",
            placeholder="e.g., 6/29 11:00am PST, 12/25 14:30 EST, 2025/06/29 23:45 UTC",
            required=True,
            max_length=50
        )
        self.add_item(self.event_datetime)
        
        self.event_description = nextcord.ui.TextInput(
            label="Description",
            placeholder="Describe your event... (optional)",
            required=False,
            style=nextcord.TextInputStyle.paragraph,
            max_length=1000
        )
        self.add_item(self.event_description)
        
        self.max_attendees = nextcord.ui.TextInput(
            label="Max Attendees",
            placeholder="Leave blank for unlimited",
            required=False,
            max_length=10
        )
        self.add_item(self.max_attendees)
    
    async def callback(self, interaction: nextcord.Interaction):
        try:
            # Parse the datetime string
            event_datetime_utc, tz_abbr, tz_name = self.cog.parse_datetime_string(self.event_datetime.value)
            
            # Check if the event is in the future
            if event_datetime_utc <= nextcord.utils.utcnow():
                await interaction.response.send_message("❌ Event time must be in the future!", ephemeral=True)
                return
            
            # Parse max attendees
            max_attendees_val = None
            if self.max_attendees.value.strip():
                try:
                    max_attendees_val = int(self.max_attendees.value.strip())
                    if max_attendees_val <= 0:
                        await interaction.response.send_message("❌ Max attendees must be a positive number!", ephemeral=True)
                        return
                except ValueError:
                    await interaction.response.send_message("❌ Max attendees must be a valid number!", ephemeral=True)
                    return
            
            # Create the event
            event_id = await self.cog.create_event(
                creator_id=interaction.user.id,
                event_name=self.event_name.value,
                event_description=self.event_description.value or "No description provided",
                event_time=event_datetime_utc.isoformat(),
                max_attendees=max_attendees_val
            )
            
            # Create embed for the event
            embed = nextcord.Embed(
                title=f"🎉 {self.event_name.value}",
                description=self.event_description.value or "No description provided",
                color=0x00ff00,
                timestamp=event_datetime_utc
            )
            
            # Use nextcord's format_dt for better time display
            embed.add_field(
                name="📅 Event Time", 
                value=f"{nextcord.utils.format_dt(event_datetime_utc, style='F')}\n{nextcord.utils.format_dt(event_datetime_utc, style='R')}", 
                inline=False
            )
            embed.add_field(name="🌍 Timezone", value=f"{tz_abbr} ({tz_name})", inline=True)
            embed.add_field(name="👤 Created by", value=interaction.user.mention, inline=True)
            embed.add_field(name="👥 Attendees", value="0", inline=True)
            
            if max_attendees_val:
                embed.add_field(name="📊 Max Attendees", value=str(max_attendees_val), inline=True)
            
            embed.set_footer(text=f"Event ID: {event_id}")
            
            # Create view with buttons
            view = EventView(event_id=event_id, cog=self.cog)
            
            await interaction.response.send_message(embed=embed, view=view)
            
        except ValueError as e:
            await interaction.response.send_message(f"❌ Invalid date/time format: {str(e)}\n\nExamples: `6/29 11:00am PST`, `12/25 14:30 EST`, `2025/06/29 23:45 UTC`", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)

async def setup(bot):
    cog = Event(bot)
    await cog.create_tables()
    bot.add_cog(cog)

