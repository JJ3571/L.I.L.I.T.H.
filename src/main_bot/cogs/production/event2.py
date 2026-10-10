import nextcord
from nextcord.ext import commands
import os
import time, datetime
import pytz
import re
import asyncio
import asyncpg

from main_bot.guild_settings import is_bot_admin
from main_bot.server_configs.config import GUILD_ID
from main_bot.boot_log import boot_print
from main_bot.cog_log_mixin import CogLogMixin

_EV = "event"


def _to_timestamptz_arg(value: datetime.datetime | str) -> datetime.datetime:
    """asyncpg 0.30+ expects datetime for timestamptz parameters, not ISO strings."""
    if isinstance(value, datetime.datetime):
        return value
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(s)


def _dbg_print(cog, message: str) -> None:
    """Honors ``bot.full_debug_in_terminal`` (set in ``main_bot.main`` from ``FULL_DEBUG_IN_TERMINAL``)."""
    if getattr(cog.bot, "full_debug_in_terminal", False):
        cog.cog_print(message)


# Past this age, a still-active event is closed quietly so a restart does not
# ping people about events that started long ago.
_EVENT_NOTIFY_GRACE = datetime.timedelta(hours=12)
_EVENT_ID_FOOTER = re.compile(r"Event ID:\s*(\d+)")


def event_due_action(event_time: datetime.datetime, now: datetime.datetime) -> str:
    """Decide what to do once an event's start time can be compared to ``now``.

    Returns ``pending`` while the start is still in the future, ``notify`` when
    attendees should be pinged, or ``expire`` when the start is older than
    ``_EVENT_NOTIFY_GRACE`` and should be closed without a ping.
    """
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=datetime.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    if event_time > now:
        return "pending"
    if now - event_time > _EVENT_NOTIFY_GRACE:
        return "expire"
    return "notify"


def event_id_from_message(message) -> int | None:
    """Read the event id stored in an event embed footer."""
    embeds = getattr(message, "embeds", None) or []
    if not embeds:
        return None
    footer = getattr(embeds[0], "footer", None)
    text = getattr(footer, "text", None) if footer else None
    if not text:
        return None
    match = _EVENT_ID_FOOTER.search(text)
    if match is None:
        return None
    return int(match.group(1))


def _can_manage_event(interaction: nextcord.Interaction, creator_id: int) -> bool:
    if interaction.user.id == creator_id:
        return True
    user = interaction.user
    return isinstance(user, nextcord.Member) and is_bot_admin(user)


_TIMEZONE_NAMES = {
    "PST": "US/Pacific", "PDT": "US/Pacific", "PT": "US/Pacific",
    "EST": "US/Eastern", "EDT": "US/Eastern", "ET": "US/Eastern",
    "CST": "US/Central", "CDT": "US/Central", "CT": "US/Central",
    "MST": "US/Mountain", "MDT": "US/Mountain", "MT": "US/Mountain",
    "UTC": "UTC", "GMT": "GMT",
}


def format_time_for_edit(when: datetime.datetime | str, tz_abbr: str | None) -> str:
    """Wall-clock time in the timezone the user originally typed, for an edit form."""
    dt = _to_timestamptz_arg(when)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    abbr = (tz_abbr or "UTC").strip().upper()
    tz_name = _TIMEZONE_NAMES.get(abbr)
    if tz_name is None:
        abbr = "UTC"
        tz_name = "UTC"
    local = dt.astimezone(pytz.timezone(tz_name))
    hour = local.hour % 12 or 12
    ampm = "am" if local.hour < 12 else "pm"
    return f"{local.month}/{local.day}/{local.year} {hour}:{local.minute:02d}{ampm} {abbr}"


class Event(commands.Cog, CogLogMixin):
    def __init__(self, bot):
        self.bot = bot
        # Ids we already logged a failed notice for, so retries stay quiet.
        self._event_notify_failures: set[int] = set()
        self._reminder_notify_failures: set[int] = set()
        # Reminders ping the original channel and DM each subscriber.
        self.bot.loop.create_task(self.create_tables())
        self.bot.loop.create_task(self.start_reminder_check_task())
        self.bot.loop.create_task(self.start_event_check_task())

    async def create_tables(self):
        return

    async def create_event(
        self,
        creator_id: int,
        event_name: str,
        event_description: str,
        event_time: datetime.datetime | str,
        max_attendees: int = None,
        channel_id: int | None = None,
        timezone: str | None = None,
    ):
        """Create a new event and return the event_id"""
        event_time = _to_timestamptz_arg(event_time)
        async with self.bot.pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                f'''
                INSERT INTO "{_EV}".events (
                    creator_id, event_name, event_description, event_time, max_attendees, channel_id, timezone
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING event_id
                ''',
                creator_id,
                event_name,
                event_description,
                event_time,
                max_attendees,
                channel_id,
                timezone,
            )
            return row["event_id"]

    async def get_event(self, event_id: int):
        """Get event details by event_id"""
        async with self.bot.pg_pool.acquire() as conn:
            return await conn.fetchrow(
                f'''
                SELECT event_id, creator_id, event_name, event_description, event_time,
                       created_at, max_attendees, status, timezone
                FROM "{_EV}".events WHERE event_id = $1
                ''',
                event_id,
            )

    async def join_event(self, event_id: int, user_id: int, status: str = 'confirmed'):
        """Add a user to an event"""
        async with self.bot.pg_pool.acquire() as conn:
            try:
                await conn.execute(
                    f'''
                    INSERT INTO "{_EV}".event_attendees (event_id, user_id, status)
                    VALUES ($1, $2, $3)
                    ''',
                    event_id,
                    user_id,
                    status,
                )
                return True
            except asyncpg.UniqueViolationError:
                return False

    async def leave_event(self, event_id: int, user_id: int):
        """Remove a user from an event"""
        async with self.bot.pg_pool.acquire() as conn:
            tag = await conn.execute(
                f'''
                DELETE FROM "{_EV}".event_attendees
                WHERE event_id = $1 AND user_id = $2
                ''',
                event_id,
                user_id,
            )
            return tag != "DELETE 0"

    async def get_event_attendees(self, event_id: int):
        """Get all attendees for an event"""
        async with self.bot.pg_pool.acquire() as conn:
            return await conn.fetch(
                f'''
                SELECT user_id, joined_at, status
                FROM "{_EV}".event_attendees
                WHERE event_id = $1
                ORDER BY joined_at ASC
                ''',
                event_id,
            )

    async def get_attendees_by_status(self, event_id: int, status: str = 'confirmed'):
        """Get attendees for an event by status"""
        async with self.bot.pg_pool.acquire() as conn:
            return await conn.fetch(
                f'''
                SELECT user_id, joined_at
                FROM "{_EV}".event_attendees
                WHERE event_id = $1 AND status = $2
                ORDER BY joined_at ASC
                ''',
                event_id,
                status,
            )

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
        async with self.bot.pg_pool.acquire() as conn:
            val = await conn.fetchval(
                f'''
                SELECT COUNT(*) FROM "{_EV}".event_attendees
                WHERE event_id = $1 AND status = 'confirmed'
                ''',
                event_id,
            )
            return int(val or 0)

    async def is_user_attending(self, event_id: int, user_id: int):
        """Check if a user is attending an event"""
        async with self.bot.pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                f'''
                SELECT 1 FROM "{_EV}".event_attendees
                WHERE event_id = $1 AND user_id = $2
                ''',
                event_id,
                user_id,
            )
            return row is not None

    async def get_user_events(self, user_id: int):
        """Get all events a user is attending"""
        async with self.bot.pg_pool.acquire() as conn:
            return await conn.fetch(
                f'''
                SELECT e.event_id, e.event_name, e.event_time, e.creator_id
                FROM "{_EV}".events e
                JOIN "{_EV}".event_attendees ea ON e.event_id = ea.event_id
                WHERE ea.user_id = $1 AND e.status = 'active'
                ORDER BY e.event_time ASC
                ''',
                user_id,
            )

    async def get_upcoming_events(self, limit: int = 10):
        """Get upcoming events"""
        async with self.bot.pg_pool.acquire() as conn:
            return await conn.fetch(
                f'''
                SELECT event_id, creator_id, event_name, event_description, event_time,
                       created_at, max_attendees, status
                FROM "{_EV}".events
                WHERE status = 'active' AND event_time > CURRENT_TIMESTAMP
                ORDER BY event_time ASC
                LIMIT $1
                ''',
                limit,
            )

    async def update_event(
        self,
        event_id: int,
        name: str,
        description: str,
        event_time: datetime.datetime | str,
        max_attendees: int | None,
        timezone: str | None = None,
    ):
        """Update an existing event and mark it active so a new start time can notify again."""
        event_time = _to_timestamptz_arg(event_time)
        async with self.bot.pg_pool.acquire() as conn:
            tag = await conn.execute(
                f'''
                UPDATE "{_EV}".events
                SET event_name = $1, event_description = $2, event_time = $3,
                    max_attendees = $4, status = 'active', timezone = $5
                WHERE event_id = $6
                ''',
                name,
                description,
                event_time,
                max_attendees,
                timezone,
                event_id,
            )
            return tag != "UPDATE 0"

    async def get_event_post(self, event_id: int):
        """Channel and message where the event embed was posted."""
        async with self.bot.pg_pool.acquire() as conn:
            return await conn.fetchrow(
                f'''
                SELECT channel_id, message_id
                FROM "{_EV}".events
                WHERE event_id = $1
                ''',
                event_id,
            )

    async def build_event_embed(self, event_id: int) -> nextcord.Embed | None:
        """Build the public event embed from the current database row."""
        event = await self.get_event(event_id)
        if not event:
            return None
        name = event["event_name"]
        description = event["event_description"] or "No description provided"
        event_time = event["event_time"]
        if not isinstance(event_time, datetime.datetime):
            event_time = _to_timestamptz_arg(event_time)
        creator_id = event["creator_id"]
        max_attendees = event["max_attendees"]
        count = await self.get_attendee_count(event_id)

        embed = nextcord.Embed(
            title=f"🗓️ {name}",
            description=description,
            color=0x00FF00,
            timestamp=event_time,
        )
        embed.add_field(
            name="🕒 Event Time",
            value=(
                f"{nextcord.utils.format_dt(event_time, style='F')}\n"
                f"{nextcord.utils.format_dt(event_time, style='R')}"
            ),
            inline=False,
        )
        embed.add_field(name="Created by", value=f"<@{creator_id}>", inline=True)
        embed.add_field(name="Attendees", value=str(count), inline=True)
        if max_attendees:
            embed.add_field(name="Max Attendees", value=str(max_attendees), inline=True)
    
        embed.set_footer(text=f"Event ID: {event_id}")
        return embed

    async def refresh_event_message(self, event_id: int) -> bool:
        """Rewrite the posted event embed so it matches the database."""
        post = await self.get_event_post(event_id)
        if not post or not post["channel_id"] or not post["message_id"]:
            return False
        embed = await self.build_event_embed(event_id)
        if embed is None:
            return False
        channel = await self._resolve_channel(int(post["channel_id"]), f"event {event_id}")
        if channel is None:
            return False
        try:
            message = await channel.fetch_message(int(post["message_id"]))
            await message.edit(embed=embed, view=EventView(self))
            return True
        except Exception as e:
            self.cog_print(f"Could not refresh event {event_id} message: {e}")
            return False

    async def mark_event_message_deleted(
        self,
        event_id: int,
        event_name: str,
        channel_id: int | None,
        message_id: int | None,
    ) -> None:
        """Replace the public event post after the row is deleted."""
        if not channel_id or not message_id:
            return
        channel = await self._resolve_channel(int(channel_id), f"event {event_id}")
        if channel is None:
            return
        embed = nextcord.Embed(
            title="🗑️ Event deleted",
            description=event_name,
            color=nextcord.Color.red(),
        )
        embed.set_footer(text=f"Event ID: {event_id}")
        try:
            message = await channel.fetch_message(int(message_id))
            await message.edit(embed=embed, view=None)
        except Exception as e:
            self.cog_print(f"Could not update deleted event {event_id} message: {e}")

    async def delete_event(self, event_id: int):
        """Delete an event by event_id"""
        async with self.bot.pg_pool.acquire() as conn:
            tag = await conn.execute(
                f'''
                DELETE FROM "{_EV}".events
                WHERE event_id = $1
                ''',
                event_id,
            )
            return tag != "DELETE 0"

    @nextcord.slash_command(
        name="event",
        description="Create a new event, let people RSVP.",
        guild_ids=[GUILD_ID],
    )
    async def event_command(self, interaction: nextcord.Interaction):
        """Create a new event using a modal. Edit and delete live on the event post."""
        modal = EventCreationModal(cog=self)
        await interaction.response.send_modal(modal)

    @nextcord.slash_command(name="reminder", description="Creates a reminder post in a channel.", guild_ids=[GUILD_ID])
    async def remind_command(self, interaction: nextcord.Interaction):
        """Create a reminder using a modal"""
        modal = ReminderCreationModal(cog=self)
        await interaction.response.send_modal(modal)

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
        
        # Extract timezone from end of string (including shorthand versions)
        timezone_pattern = r'\b(PST|PDT|PT|EST|EDT|ET|CST|CDT|CT|MST|MDT|MT|UTC|GMT)\b$'
        tz_match = re.search(timezone_pattern, datetime_str, re.IGNORECASE)
        
        if tz_match:
            tz_abbr = tz_match.group(1).upper()
            tz_name = _TIMEZONE_NAMES[tz_abbr]
            datetime_str = datetime_str[:tz_match.start()].strip()
        else:
            # Default to PST if no timezone is specified
            tz_abbr = 'PST'
            tz_name = 'US/Pacific'
        
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
        
        # Parse the date (pass timezone for current day calculation)
        tz = pytz.timezone(tz_name)
        is_time_only = not date_str.strip()  # True if no date was provided (time-only input)
        year, month, day = self.parse_date(date_str, tz, is_time_only)
        
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
    
    def parse_date(self, date_str: str, tz=None, is_time_only=False):
        """Parse date string and return year, month, day"""
        date_str = date_str.strip()
        
        # If date_str is empty or only whitespace, return current day in the timezone
        if not date_str:
            if tz:
                now_in_tz = datetime.datetime.now(tz=tz)
                return now_in_tz.year, now_in_tz.month, now_in_tz.day
            else:
                now = nextcord.utils.utcnow()
                return now.year, now.month, now.day
        
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
                    
                    # Only bump to next year if user explicitly provided a date that's in the past
                    # Don't bump if this is from time-only input (defaulting to today)
                    if not is_time_only:
                        test_date = datetime.date(year, month, day)
                        # Compare against current date in the same timezone if provided
                        if tz:
                            current_date_in_tz = datetime.datetime.now(tz=tz).date()
                        else:
                            current_date_in_tz = nextcord.utils.utcnow().date()
                        
                        if test_date < current_date_in_tz:
                            year += 1
                
                return year, month, day
        
        raise ValueError(f"Invalid date format: {date_str}")

    # ============== REMINDER METHODS ==============
    
    async def create_reminder(
        self,
        creator_id: int,
        reminder_text: str,
        reminder_time: datetime.datetime | str,
        original_channel_id: int,
        message_id: int = None,
        timezone: str | None = None,
    ):
        """Create a new reminder and return the reminder_id"""
        reminder_time = _to_timestamptz_arg(reminder_time)
        async with self.bot.pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                f'''
                INSERT INTO "{_EV}".reminders (
                    creator_id, reminder_text, reminder_time, original_channel_id, message_id, timezone
                )
                VALUES ($1, $2, $3, $4, $5, $6) RETURNING reminder_id
                ''',
                creator_id,
                reminder_text,
                reminder_time,
                original_channel_id,
                message_id,
                timezone,
            )
            return row["reminder_id"]

    async def get_reminder(self, reminder_id: int):
        """Get reminder details by reminder_id"""
        async with self.bot.pg_pool.acquire() as conn:
            return await conn.fetchrow(
                f'''
                SELECT reminder_id, creator_id, reminder_text, reminder_time, original_channel_id, message_id, created_at, status, timezone
                FROM "{_EV}".reminders WHERE reminder_id = $1
                ''',
                reminder_id,
            )

    async def subscribe_to_reminder(self, reminder_id: int, user_id: int):
        """Subscribe a user to a reminder"""
        async with self.bot.pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                f'''
                INSERT INTO "{_EV}".reminder_subscribers (reminder_id, user_id)
                VALUES ($1, $2)
                ON CONFLICT (reminder_id, user_id) DO NOTHING
                RETURNING reminder_id
                ''',
                reminder_id,
                user_id,
            )
            return row is not None

    async def unsubscribe_from_reminder(self, reminder_id: int, user_id: int):
        """Unsubscribe a user from a reminder"""
        async with self.bot.pg_pool.acquire() as conn:
            tag = await conn.execute(
                f'''
                DELETE FROM "{_EV}".reminder_subscribers
                WHERE reminder_id = $1 AND user_id = $2
                ''',
                reminder_id,
                user_id,
            )
            return tag != "DELETE 0"

    async def get_reminder_subscribers(self, reminder_id: int):
        """Get all subscribers for a reminder"""
        async with self.bot.pg_pool.acquire() as conn:
            return await conn.fetch(
                f'''
                SELECT user_id, subscribed_at
                FROM "{_EV}".reminder_subscribers
                WHERE reminder_id = $1
                ORDER BY subscribed_at ASC
                ''',
                reminder_id,
            )

    async def is_user_subscribed(self, reminder_id: int, user_id: int):
        """Check if a user is subscribed to a reminder"""
        async with self.bot.pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                f'''
                SELECT 1 FROM "{_EV}".reminder_subscribers
                WHERE reminder_id = $1 AND user_id = $2
                ''',
                reminder_id,
                user_id,
            )
            return row is not None

    async def update_reminder(
        self,
        reminder_id: int,
        reminder_text: str,
        reminder_time: datetime.datetime | str,
        timezone: str | None = None,
    ):
        """Update an existing reminder"""
        reminder_time = _to_timestamptz_arg(reminder_time)
        async with self.bot.pg_pool.acquire() as conn:
            tag = await conn.execute(
                f'''
                UPDATE "{_EV}".reminders
                SET reminder_text = $1, reminder_time = $2, timezone = $3
                WHERE reminder_id = $4
                ''',
                reminder_text,
                reminder_time,
                timezone,
                reminder_id,
            )
            return tag != "UPDATE 0"

    async def delete_reminder(self, reminder_id: int):
        """Delete a reminder by reminder_id"""
        async with self.bot.pg_pool.acquire() as conn:
            tag = await conn.execute(
                f'''
                DELETE FROM "{_EV}".reminders
                WHERE reminder_id = $1
                ''',
                reminder_id,
            )
            return tag != "DELETE 0"

    async def get_due_reminders(self):
        """Get all reminders that are due now"""
        async with self.bot.pg_pool.acquire() as conn:
            current_time = nextcord.utils.utcnow()
            _dbg_print(self, f"[DEBUG] get_due_reminders() - Current time: {current_time.isoformat()}")

            results = await conn.fetch(
                f'''
                SELECT reminder_id, creator_id, reminder_text, reminder_time, original_channel_id, message_id, created_at, status
                FROM "{_EV}".reminders
                WHERE status = 'active' AND reminder_time <= $1
                ''',
                current_time,
            )

            _dbg_print(self, f"[DEBUG] get_due_reminders() - SQL query found {len(results)} results")
            for result in results:
                reminder_id = result["reminder_id"]
                rtime = result["reminder_time"]
                _dbg_print(self, f"[DEBUG]   -> Reminder ID {reminder_id} with time {rtime}")

            return results

    async def mark_reminder_completed(self, reminder_id: int):
        """Mark a reminder as completed"""
        async with self.bot.pg_pool.acquire() as conn:
            tag = await conn.execute(
                f'''
                UPDATE "{_EV}".reminders
                SET status = 'completed'
                WHERE reminder_id = $1
                ''',
                reminder_id,
            )
            return tag != "UPDATE 0"

    async def start_reminder_check_task(self):
        """Start the background task to check for due reminders"""
        await self.bot.wait_until_ready()
        self.cog_print("Reminder check task started - checking every minute for due reminders")
        while not self.bot.is_closed():
            try:
                await self.check_and_send_reminders()
            except Exception as e:
                self.cog_print(f"Error in reminder check task: {e}")
            await asyncio.sleep(30)  # Check every 30 seconds for debugging

    async def check_and_send_reminders(self):
        """Check for due reminders and send them"""
        current_time = nextcord.utils.utcnow()
        current_time_iso = current_time.isoformat()
        
        _dbg_print(self, f"[DEBUG] Checking for due reminders at {current_time_iso}")
        
        # First, let's see all active reminders in the database
        async with self.bot.pg_pool.acquire() as conn:
            all_active = await conn.fetch(
                f'''
                SELECT reminder_id, creator_id, reminder_text, reminder_time, status
                FROM "{_EV}".reminders
                WHERE status = 'active'
                ORDER BY reminder_time ASC
                '''
            )

            _dbg_print(self, f"[DEBUG] Found {len(all_active)} active reminders in database:")
            for reminder in all_active:
                reminder_id = reminder["reminder_id"]
                creator_id = reminder["creator_id"]
                reminder_text = reminder["reminder_text"]
                reminder_time = reminder["reminder_time"]
                status = reminder["status"]
                _dbg_print(self, f"[DEBUG]   ID {reminder_id}: '{reminder_text[:50]}...' due at {reminder_time} (status: {status})")

                rt_str = reminder_time.isoformat() if hasattr(reminder_time, "isoformat") else str(reminder_time)
                is_due = rt_str <= current_time_iso
                _dbg_print(self, f"[DEBUG]   -> Is due? {is_due} (reminder_time <= current_time: {rt_str} <= {current_time_iso})")
        
        due_reminders = await self.get_due_reminders()
        
        _dbg_print(self, f"[DEBUG] get_due_reminders() returned {len(due_reminders)} reminders")
        
        if due_reminders:
            _dbg_print(self, f"[DEBUG] Processing {len(due_reminders)} due reminders")
        else:
            _dbg_print(self, f"[DEBUG] No due reminders to process")
        
        for reminder_data in due_reminders:
            reminder_id, creator_id, reminder_text, reminder_time, original_channel_id, message_id, created_at, status = reminder_data
            
            _dbg_print(self, f"[DEBUG] Processing reminder ID {reminder_id}: '{reminder_text[:50]}...'")
            
            try:
                # Get subscribers
                subscribers = await self.get_reminder_subscribers(reminder_id)
                
                _dbg_print(self, f"[DEBUG] Reminder {reminder_id} has {len(subscribers)} subscribers")
                
                if not subscribers:
                    # No subscribers, just mark as completed
                    _dbg_print(self, f"[DEBUG] No subscribers for reminder {reminder_id}, marking as completed")
                    await self.mark_reminder_completed(reminder_id)
                    continue
                
                # Create mentions string
                mentions = []
                for user_id, _ in subscribers:
                    mentions.append(f"<@{user_id}>")
                    _dbg_print(self, f"[DEBUG] Will mention user {user_id}")
                
                mentions_text = " ".join(mentions)
                subscriber_ids = [user_id for user_id, _ in subscribers]
                
                _dbg_print(self, f"[DEBUG] Creating embed for reminder {reminder_id}")
                
                # Create reminder notification embed
                embed = nextcord.Embed(
                    title="⏰ Reminder",
                    description=reminder_text,
                    color=nextcord.Color.yellow(),
                    timestamp=nextcord.utils.utcnow()
                )
                
                creator = self.bot.get_user(creator_id)
                if creator:
                    embed.set_author(
                        name=creator.display_name,
                        icon_url=creator.display_avatar.url
                    )
                    _dbg_print(self, f"[DEBUG] Set embed author to {creator.display_name}")
                else:
                    embed.set_author(name=f"User {creator_id}")
                    _dbg_print(self, f"[DEBUG] Creator user {creator_id} not found, using fallback name")
                
                embed.set_footer(text=f"Reminder ID: {reminder_id}")

                delivered = await self._deliver_notice(
                    channel_id=original_channel_id,
                    mentions=mentions_text,
                    embed=embed,
                    user_ids=subscriber_ids,
                    label=f"reminder {reminder_id}",
                )
                if not delivered:
                    if reminder_id not in self._reminder_notify_failures:
                        self._reminder_notify_failures.add(reminder_id)
                        self.cog_print(f"Reminder {reminder_id} was not delivered; will retry")
                    continue

                self._reminder_notify_failures.discard(reminder_id)
                _dbg_print(self, f"[DEBUG] Marking reminder {reminder_id} as completed")
                await self.mark_reminder_completed(reminder_id)
                
            except Exception as e:
                _dbg_print(self, f"[DEBUG] ❌ Error processing reminder {reminder_id}: {e}")
                # Mark as completed to prevent infinite retries
                await self.mark_reminder_completed(reminder_id)

    async def set_event_message(self, event_id: int, channel_id: int, message_id: int):
        """Remember where the event embed was posted so the start ping can land there."""
        async with self.bot.pg_pool.acquire() as conn:
            tag = await conn.execute(
                f'''
                UPDATE "{_EV}".events
                SET channel_id = $1, message_id = $2
                WHERE event_id = $3
                ''',
                channel_id,
                message_id,
                event_id,
            )
            return tag != "UPDATE 0"

    async def get_due_events(self):
        """Get active events whose start time has passed."""
        async with self.bot.pg_pool.acquire() as conn:
            return await conn.fetch(
                f'''
                SELECT event_id, creator_id, event_name, event_description, event_time,
                       channel_id, message_id, status
                FROM "{_EV}".events
                WHERE status = 'active' AND event_time <= $1
                ORDER BY event_time ASC
                ''',
                nextcord.utils.utcnow(),
            )

    async def mark_event_completed(self, event_id: int):
        """Mark an event as completed so attendees are not pinged again."""
        async with self.bot.pg_pool.acquire() as conn:
            tag = await conn.execute(
                f'''
                UPDATE "{_EV}".events
                SET status = 'completed'
                WHERE event_id = $1 AND status = 'active'
                ''',
                event_id,
            )
            return tag != "UPDATE 0"

    def register_persistent_views(self):
        """Keep event buttons working across restarts.

        Discord only delivers component clicks after a process restart when every
        button has a stable ``custom_id``, ``timeout`` is ``None``, and the view
        is registered here. The event id is read from the embed footer so one
        view can serve every event post.
        """
        self._persistent_views = [
            EventView(self),
            EventManagementView(self),
            EventDeleteConfirmView(self),
        ]
        for view in self._persistent_views:
            self.bot.add_view(view)

    def cog_unload(self):
        for view in getattr(self, "_persistent_views", []):
            self.bot.remove_view(view)

    async def start_event_check_task(self):
        """Start the background task that pings attendees when an event starts."""
        await self.bot.wait_until_ready()
        self.register_persistent_views()
        self.cog_print("Event check task started - checking every 30 seconds for events that have started")
        while not self.bot.is_closed():
            try:
                await self.check_and_notify_events()
            except Exception as e:
                self.cog_print(f"Error in event check task: {e}")
            await asyncio.sleep(30)

    async def check_and_notify_events(self):
        """Ping attendees for events whose start time has elapsed."""
        now = nextcord.utils.utcnow()
        for event in await self.get_due_events():
            event_id = event["event_id"]
            action = event_due_action(event["event_time"], now)
            if action == "expire":
                self.cog_print(
                    f"Event {event_id} started more than {_EVENT_NOTIFY_GRACE} ago; "
                    "marking completed without notifying"
                )
                await self.mark_event_completed(event_id)
                continue
            if action != "notify":
                continue
            await self._notify_event_started(event)

    async def _resolve_channel(self, channel_id: int, label: str):
        channel = self.bot.get_channel(int(channel_id))
        if channel is not None:
            return channel
        try:
            return await self.bot.fetch_channel(int(channel_id))
        except Exception as e:
            self.cog_print(f"Could not fetch channel {channel_id} for {label}: {e}")
            return None

    async def _dm_users(self, user_ids: list[int], embed: nextcord.Embed, label: str) -> int:
        """DM each user the same embed. Returns how many sends succeeded."""
        delivered = 0
        for user_id in user_ids:
            try:
                user = self.bot.get_user(int(user_id))
                if user is None:
                    user = await self.bot.fetch_user(int(user_id))
                await user.send(embed=embed)
                delivered += 1
            except Exception as e:
                self.cog_print(f"Failed to DM user {user_id} for {label}: {e}")
        if delivered:
            self.cog_print(f"DM'd {delivered} user(s) for {label}")
        return delivered

    async def _deliver_notice(
        self,
        *,
        channel_id: int | None,
        mentions: str,
        embed: nextcord.Embed,
        user_ids: list[int],
        label: str,
    ) -> bool:
        """Ping the channel and DM each user. True if either path reaches someone."""
        channel_sent = False
        if channel_id:
            channel = await self._resolve_channel(int(channel_id), label)
            if channel is not None:
                try:
                    await channel.send(
                        content=mentions or None,
                        embed=embed,
                        allowed_mentions=nextcord.AllowedMentions(users=True),
                    )
                    channel_sent = True
                    self.cog_print(f"Posted {label} in channel {channel_id}")
                except Exception as e:
                    self.cog_print(f"Failed to post {label} in channel {channel_id}: {e}")

        dmed = await self._dm_users(user_ids, embed, label)
        return channel_sent or dmed > 0

    async def _notify_event_started(self, event):
        """Ping the event channel and DM every attendee."""
        event_id = event["event_id"]
        event_name = event["event_name"]
        description = event["event_description"] or "No description provided"
        event_time = event["event_time"]
        channel_id = event["channel_id"]

        attendees = await self.get_event_attendees(event_id)
        user_ids = [row["user_id"] for row in attendees]
        mentions = " ".join(f"<@{user_id}>" for user_id in user_ids)

        embed = nextcord.Embed(
            title=f"🗓️ {event_name} is starting",
            description=description,
            color=0x00FF00,
            timestamp=nextcord.utils.utcnow(),
        )
        if isinstance(event_time, datetime.datetime):
            embed.add_field(
                name="🕒 Event Time",
                value=nextcord.utils.format_dt(event_time, style="F"),
                inline=False,
            )
        embed.set_footer(text=f"Event ID: {event_id}")

        if not user_ids and not channel_id:
            self.cog_print(f"Event {event_id} started with no attendees and no channel; marking completed")
            await self.mark_event_completed(event_id)
            return

        sent = await self._deliver_notice(
            channel_id=channel_id,
            mentions=mentions,
            embed=embed,
            user_ids=user_ids,
            label=f"event {event_id}",
        )
        if sent:
            self._event_notify_failures.discard(event_id)
            await self.mark_event_completed(event_id)
            return

        if event_id not in self._event_notify_failures:
            self._event_notify_failures.add(event_id)
            self.cog_print(f"Event {event_id} start notice was not delivered; will retry")


# Event buttons stay valid after a restart: timeout is None, custom_ids are
# stable, and Event.register_persistent_views() registers one view for every post.
# The event id lives in the embed footer, not on the view instance.
class EventView(nextcord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def _event_id(self, interaction: nextcord.Interaction) -> int | None:
        event_id = event_id_from_message(interaction.message)
        if event_id is None:
            await interaction.response.send_message("❌ Couldn't tell which event this is.", ephemeral=True)
        return event_id

    @nextcord.ui.button(label="✅ Join Event", style=nextcord.ButtonStyle.green, custom_id="event_join")
    async def join_event(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        """Handle user joining the event"""
        event_id = await self._event_id(interaction)
        if event_id is None:
            return

        event_data = await self.cog.get_event(event_id)
        if not event_data:
            await interaction.response.send_message("❌ This event no longer exists!", ephemeral=True)
            return
        if event_data["status"] != "active":
            await interaction.response.send_message("❌ This event is no longer open.", ephemeral=True)
            return

        if await self.cog.is_user_attending(event_id, interaction.user.id):
            await interaction.response.send_message("❌ You're already signed up for this event!", ephemeral=True)
            return

        current_count = await self.cog.get_attendee_count(event_id)
        max_attendees = event_data["max_attendees"]
        if max_attendees and current_count >= max_attendees:
            await interaction.response.send_message("❌ This event is full!", ephemeral=True)
            return

        success = await self.cog.join_event(event_id, interaction.user.id)
        if success:
            await self.update_embed(interaction, event_id)
            notice = f"✅ {interaction.user.mention} joined the event!"
            if interaction.response.is_done():
                await interaction.followup.send(notice, ephemeral=True)
            else:
                await interaction.response.send_message(notice, ephemeral=True)
        else:
            await interaction.response.send_message("❌ Failed to join the event!", ephemeral=True)

    @nextcord.ui.button(label="❌ Leave Event", style=nextcord.ButtonStyle.red, custom_id="event_leave")
    async def leave_event(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        """Handle user leaving the event"""
        event_id = await self._event_id(interaction)
        if event_id is None:
            return

        if not await self.cog.is_user_attending(event_id, interaction.user.id):
            await interaction.response.send_message("❌ You're not signed up for this event!", ephemeral=True)
            return

        success = await self.cog.leave_event(event_id, interaction.user.id)
        if success:
            await self.update_embed(interaction, event_id)
            notice = f"✅ {interaction.user.mention} left the event!"
            if interaction.response.is_done():
                await interaction.followup.send(notice, ephemeral=True)
            else:
                await interaction.response.send_message(notice, ephemeral=True)
        else:
            await interaction.response.send_message("❌ Failed to leave the event!", ephemeral=True)

    @nextcord.ui.button(label="👥 View Attendees", style=nextcord.ButtonStyle.blurple, custom_id="event_attendees")
    async def view_attendees(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        """Show list of attendees"""
        event_id = await self._event_id(interaction)
        if event_id is None:
            return

        attendees = await self.cog.get_event_attendees(event_id)
        if not attendees:
            await interaction.response.send_message("📭 No one has signed up for this event yet!", ephemeral=True)
            return

        attendee_list = []
        for row in attendees:
            user_id = row["user_id"]
            user = self.cog.bot.get_user(user_id)
            name = user.display_name if user else f"User {user_id}"
            attendee_list.append(f"• {name}")

        embed = nextcord.Embed(
            title=f"👥 Event Attendees ({len(attendees)})",
            description="\n".join(attendee_list[:20]),
            color=0x0099FF,
        )
        if len(attendees) > 20:
            embed.set_footer(text=f"... and {len(attendees) - 20} more")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @nextcord.ui.button(label="⚙️", style=nextcord.ButtonStyle.secondary, custom_id="event_settings")
    async def manage_event(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        """Open edit and delete controls for the creator or a bot admin."""
        event_id = await self._event_id(interaction)
        if event_id is None:
            return

        event_data = await self.cog.get_event(event_id)
        if not event_data:
            await interaction.response.send_message("❌ This event no longer exists!", ephemeral=True)
            return
        if not _can_manage_event(interaction, event_data["creator_id"]):
            await interaction.response.send_message(
                "❌ Only the event creator or server admins can manage this event!",
                ephemeral=True,
            )
            return

        name = event_data["event_name"]
        embed = nextcord.Embed(
            title="⚙️ EDIT TIME!",
            description=f"**Event:** {name[:100]}{'...' if len(name) > 100 else ''}",
            color=nextcord.Color.orange(),
        )
        embed.add_field(name="✏️ Edit the event", value="Name, description, time, and max attendees", inline=False)
        embed.add_field(name="🗑️ Delete the event", value="Removes the event and its attendee list", inline=False)
        embed.set_footer(text=f"Event ID: {event_id}")
        await interaction.response.send_message(embed=embed, view=EventManagementView(self.cog), ephemeral=True)

    async def update_embed(self, interaction: nextcord.Interaction, event_id: int):
        """Update the event embed with the current attendee count."""
        try:
            count = await self.cog.get_attendee_count(event_id)
            embed = interaction.message.embeds[0]
            for i, field in enumerate(embed.fields):
                if field.name == "👥 Attendees":
                    embed.set_field_at(i, name="👥 Attendees", value=str(count), inline=True)
                    break
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            self.cog.cog_print(f"Error updating embed: {e}")


class EventManagementView(nextcord.ui.View):
    """Ephemeral edit/delete panel. Persistent so it does not expire while the bot is up."""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def _event_id(self, interaction: nextcord.Interaction) -> int | None:
        event_id = event_id_from_message(interaction.message)
        if event_id is None:
            await interaction.response.send_message("❌ Couldn't tell which event this is.", ephemeral=True)
        return event_id

    @nextcord.ui.button(label="✏️ Edit Event", style=nextcord.ButtonStyle.blurple, custom_id="event_manage_edit")
    async def edit_event(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        event_id = await self._event_id(interaction)
        if event_id is None:
            return
        event_data = await self.cog.get_event(event_id)
        if not event_data:
            await interaction.response.send_message("❌ This event no longer exists!", ephemeral=True)
            return
        if not _can_manage_event(interaction, event_data["creator_id"]):
            await interaction.response.send_message(
                "❌ Only the event creator or server admins can manage this event!",
                ephemeral=True,
            )
            return
        modal = EventEditModal(
            cog=self.cog,
            event_id=event_id,
            current_name=event_data["event_name"],
            current_description=event_data["event_description"] or "",
            current_time=format_time_for_edit(event_data["event_time"], event_data["timezone"]),
            current_max="" if event_data["max_attendees"] is None else str(event_data["max_attendees"]),
        )
        await interaction.response.send_modal(modal)

    @nextcord.ui.button(label="🗑️ Delete Event", style=nextcord.ButtonStyle.red, custom_id="event_manage_delete")
    async def delete_event(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        event_id = await self._event_id(interaction)
        if event_id is None:
            return
        embed = nextcord.Embed(
            title="⚠️ Confirm Deletion",
            description="Are you sure you want to delete this event?\n\n**This action cannot be undone!**",
            color=nextcord.Color.red(),
        )
        embed.set_footer(text=f"Event ID: {event_id}")
        await interaction.response.edit_message(embed=embed, view=EventDeleteConfirmView(self.cog))


class EventDeleteConfirmView(nextcord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def _event_id(self, interaction: nextcord.Interaction) -> int | None:
        event_id = event_id_from_message(interaction.message)
        if event_id is None:
            await interaction.response.send_message("❌ Couldn't tell which event this is.", ephemeral=True)
        return event_id

    @nextcord.ui.button(label="❌ Cancel", style=nextcord.ButtonStyle.secondary, custom_id="event_delete_cancel")
    async def cancel_delete(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        embed = nextcord.Embed(
            title="✅ Deletion Cancelled",
            description="The event was not deleted.",
            color=nextcord.Color.green(),
        )
        await interaction.response.edit_message(embed=embed, view=None)

    @nextcord.ui.button(label="🗑️ Confirm Delete", style=nextcord.ButtonStyle.red, custom_id="event_delete_confirm")
    async def confirm_delete(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        event_id = await self._event_id(interaction)
        if event_id is None:
            return
        event_data = await self.cog.get_event(event_id)
        if not event_data:
            await interaction.response.edit_message(
                embed=nextcord.Embed(
                    title="❌ Deletion Failed",
                    description="This event no longer exists.",
                    color=nextcord.Color.red(),
                ),
                view=None,
            )
            return
        if not _can_manage_event(interaction, event_data["creator_id"]):
            await interaction.response.send_message(
                "❌ Only the event creator or server admins can manage this event!",
                ephemeral=True,
            )
            return
        post = await self.cog.get_event_post(event_id)
        success = await self.cog.delete_event(event_id)
        if success:
            channel_id = post["channel_id"] if post else None
            message_id = post["message_id"] if post else None
            await self.cog.mark_event_message_deleted(
                event_id,
                event_data["event_name"],
                channel_id,
                message_id,
            )
            embed = nextcord.Embed(
                title="✅ Event Deleted",
                description="The event has been deleted.",
                color=nextcord.Color.green(),
            )
        else:
            embed = nextcord.Embed(
                title="❌ Deletion Failed",
                description="Failed to delete the event.",
                color=nextcord.Color.red(),
            )
        await interaction.response.edit_message(embed=embed, view=None)


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
            placeholder="(6/29 11:00am PST  |  12/25 14:30 EST  |  2025/06/29 23:45 UTC)",
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
                event_time=event_datetime_utc,
                max_attendees=max_attendees_val,
                channel_id=interaction.channel_id,
                timezone=tz_abbr,
            )
            
            embed = await self.cog.build_event_embed(event_id)
            if embed is None:
                await interaction.response.send_message("❌ Failed to load the new event.", ephemeral=True)
                return

            view = EventView(self.cog)
            
            await interaction.response.send_message(embed=embed, view=view)
            if interaction.channel_id:
                try:
                    posted = await interaction.original_message()
                    await self.cog.set_event_message(event_id, interaction.channel_id, posted.id)
                except Exception as e:
                    self.cog.cog_print(f"Saved event {event_id} without its message id: {e}")
            
        except ValueError as e:
            await interaction.response.send_message(f"❌ Invalid date/time format: {str(e)}\n\nExamples: `6/29 11:00am PST`, `12/25 14:30 EST`, `2025/06/29 23:45 UTC`", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)


class EventEditModal(nextcord.ui.Modal):
    def __init__(
        self,
        cog,
        event_id: int,
        current_name: str,
        current_description: str,
        current_time: str,
        current_max: str,
    ):
        super().__init__(title="Edit Event", timeout=300)
        self.cog = cog
        self.event_id = event_id

        self.event_name = nextcord.ui.TextInput(
            label="Event Name",
            placeholder="Enter the name of your event...",
            required=True,
            max_length=100,
            default_value=current_name,
        )
        self.add_item(self.event_name)

        self.event_datetime = nextcord.ui.TextInput(
            label="Date & Time",
            placeholder="(6/29 11:00am PST  |  12/25 14:30 EST  |  2025/06/29 23:45 UTC)",
            required=True,
            max_length=50,
            default_value=current_time,
        )
        self.add_item(self.event_datetime)

        self.event_description = nextcord.ui.TextInput(
            label="Description",
            placeholder="Describe your event... (optional)",
            required=False,
            style=nextcord.TextInputStyle.paragraph,
            max_length=1000,
            default_value=current_description,
        )
        self.add_item(self.event_description)

        self.max_attendees = nextcord.ui.TextInput(
            label="Max Attendees",
            placeholder="Leave blank for unlimited",
            required=False,
            max_length=10,
            default_value=current_max,
        )
        self.add_item(self.max_attendees)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            event_datetime_utc, tz_abbr, _tz_name = self.cog.parse_datetime_string(self.event_datetime.value)
            if event_datetime_utc <= nextcord.utils.utcnow():
                await interaction.response.send_message("❌ Event time must be in the future!", ephemeral=True)
                return

            max_attendees_val = None
            if self.max_attendees.value.strip():
                try:
                    max_attendees_val = int(self.max_attendees.value.strip())
                    if max_attendees_val <= 0:
                        await interaction.response.send_message(
                            "❌ Max attendees must be a positive number!",
                            ephemeral=True,
                        )
                        return
                except ValueError:
                    await interaction.response.send_message(
                        "❌ Max attendees must be a valid number!",
                        ephemeral=True,
                    )
                    return

            success = await self.cog.update_event(
                self.event_id,
                self.event_name.value,
                self.event_description.value or "No description provided",
                event_datetime_utc,
                max_attendees_val,
                tz_abbr,
            )
            if not success:
                await interaction.response.send_message("❌ Failed to update the event.", ephemeral=True)
                return

            refreshed = await self.cog.refresh_event_message(self.event_id)
            description = "The event has been updated."
            if not refreshed:
                description += " The original post could not be refreshed."
            embed = nextcord.Embed(
                title="✅ Event Updated",
                description=description,
                color=nextcord.Color.green(),
            )
            embed.add_field(name="📝 Name", value=self.event_name.value, inline=False)
            embed.add_field(
                name="📅 Time",
                value=(
                    f"{nextcord.utils.format_dt(event_datetime_utc, style='F')}\n"
                    f"{nextcord.utils.format_dt(event_datetime_utc, style='R')}"
                ),
                inline=False,
            )
            await interaction.response.edit_message(embed=embed, view=None)
        except ValueError as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ Invalid date/time format: {e}\n\nExamples: `6/29 11:00am PST`, `12/25 14:30 EST`, `2025/06/29 23:45 UTC`",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"❌ Invalid date/time format: {e}\n\nExamples: `6/29 11:00am PST`, `12/25 14:30 EST`, `2025/06/29 23:45 UTC`",
                    ephemeral=True,
                )
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ An error occurred: {e}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ An error occurred: {e}", ephemeral=True)


# ============== REMINDER UI COMPONENTS ==============

class ReminderView(nextcord.ui.View):
    def __init__(self, reminder_id: int, cog):
        super().__init__(timeout=None)
        self.reminder_id = reminder_id
        self.cog = cog

    @nextcord.ui.button(label="⏰ Remind me too", style=nextcord.ButtonStyle.blurple)
    async def subscribe_reminder(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        """Handle user subscribing to the reminder"""
        # Check if reminder exists and is active
        reminder_data = await self.cog.get_reminder(self.reminder_id)
        if not reminder_data:
            await interaction.response.send_message("❌ This reminder no longer exists!", ephemeral=True)
            return
        
        reminder_id, creator_id, reminder_text, reminder_time, original_channel_id, message_id, created_at, status, _tz = reminder_data
        
        if status != 'active':
            await interaction.response.send_message("❌ This reminder is no longer active!", ephemeral=True)
            return
        
        # asyncpg returns timestamptz as a datetime, not an ISO string.
        reminder_datetime = _to_timestamptz_arg(reminder_time)
        if reminder_datetime.tzinfo is None:
            reminder_datetime = reminder_datetime.replace(tzinfo=datetime.timezone.utc)
        if reminder_datetime <= nextcord.utils.utcnow():
            await interaction.response.send_message("❌ This reminder time has already passed!", ephemeral=True)
            return
        
        # Check if user is already subscribed
        if await self.cog.is_user_subscribed(self.reminder_id, interaction.user.id):
            await interaction.response.send_message("❌ You're already subscribed to this reminder!", ephemeral=True)
            return
        
        # Subscribe to the reminder
        success = await self.cog.subscribe_to_reminder(self.reminder_id, interaction.user.id)
        if success:
            await interaction.response.send_message(f"✅ {interaction.user.mention} subscribed to the reminder!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Failed to subscribe to the reminder!", ephemeral=True)

    @nextcord.ui.button(label="⚙️", style=nextcord.ButtonStyle.secondary)
    async def manage_reminder(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        """Handle reminder management (edit/delete)"""
        # Check if reminder exists
        reminder_data = await self.cog.get_reminder(self.reminder_id)
        if not reminder_data:
            await interaction.response.send_message("❌ This reminder no longer exists!", ephemeral=True)
            return
        
        reminder_id, creator_id, reminder_text, reminder_time, original_channel_id, message_id, created_at, status, _tz = reminder_data
        
        # Check if user has permission (creator or admin)
        if interaction.user.id != creator_id and not (isinstance(interaction.user, nextcord.Member) and is_bot_admin(interaction.user)):
            await interaction.response.send_message("❌ Only the reminder creator or server admins can manage this reminder!", ephemeral=True)
            return
        
        # Show management modal
        view = ReminderManagementView(reminder_id=self.reminder_id, cog=self.cog, reminder_data=reminder_data)
        
        embed = nextcord.Embed(
            title="⚙️ EDIT TIME!",
            description=f"**Reminder:** {reminder_text[:100]}{'...' if len(reminder_text) > 100 else ''}",
            color=nextcord.Color.orange()
        )

        embed.set_footer(text=f"Reminder ID: {reminder_id}")
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class ReminderManagementView(nextcord.ui.View):
    def __init__(self, reminder_id: int, cog, reminder_data):
        super().__init__(timeout=300)
        self.reminder_id = reminder_id
        self.cog = cog
        self.reminder_data = reminder_data

    @nextcord.ui.button(label="✏️ Edit Reminder", style=nextcord.ButtonStyle.blurple)
    async def edit_reminder(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        """Edit the reminder"""
        reminder_text = self.reminder_data["reminder_text"]
        modal = ReminderEditModal(
            cog=self.cog,
            reminder_id=self.reminder_id,
            current_text=reminder_text,
            current_time=format_time_for_edit(
                self.reminder_data["reminder_time"],
                self.reminder_data["timezone"],
            ),
        )
        await interaction.response.send_modal(modal)

    @nextcord.ui.button(label="🗑️ Delete Reminder", style=nextcord.ButtonStyle.red)
    async def delete_reminder(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        """Delete the reminder"""
        # Confirm deletion
        confirm_view = ReminderDeleteConfirmView(reminder_id=self.reminder_id, cog=self.cog)
        
        embed = nextcord.Embed(
            title="⚠️ Confirm Deletion",
            description="Are you sure you want to delete this reminder?\n\n**This action cannot be undone!**",
            color=nextcord.Color.red()
        )
        
        await interaction.response.edit_message(embed=embed, view=confirm_view)


class ReminderDeleteConfirmView(nextcord.ui.View):
    def __init__(self, reminder_id: int, cog):
        super().__init__(timeout=60)
        self.reminder_id = reminder_id
        self.cog = cog

    @nextcord.ui.button(label="❌ Cancel", style=nextcord.ButtonStyle.secondary)
    async def cancel_delete(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        """Cancel the deletion"""
        embed = nextcord.Embed(
            title="✅ Deletion Cancelled",
            description="The reminder was not deleted.",
            color=nextcord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    @nextcord.ui.button(label="🗑️ Confirm Delete", style=nextcord.ButtonStyle.red)
    async def confirm_delete(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        """Confirm the deletion"""
        success = await self.cog.delete_reminder(self.reminder_id)
        
        if success:
            embed = nextcord.Embed(
                title="✅ Reminder Deleted",
                description="The reminder has been successfully deleted.",
                color=nextcord.Color.green()
            )
        else:
            embed = nextcord.Embed(
                title="❌ Deletion Failed",
                description="Failed to delete the reminder.",
                color=nextcord.Color.red()
            )
        
        await interaction.response.edit_message(embed=embed, view=None)


class ReminderCreationModal(nextcord.ui.Modal):
    def __init__(self, cog):
        super().__init__(title="Create New Reminder", timeout=300)
        self.cog = cog
        
        self.reminder_text = nextcord.ui.TextInput(
            label="Reminder Text",
            placeholder="What would you like to be reminded about?",
            required=True,
            style=nextcord.TextInputStyle.paragraph,
            max_length=1000
        )
        self.add_item(self.reminder_text)
        
        self.reminder_datetime = nextcord.ui.TextInput(
            label="Reminder Date & Time",
            placeholder="(6/29 11:00am PST  |  12/25 14:30 EST  |  2025/06/29 23:45 UTC)",
            required=True,
            max_length=50
        )
        self.add_item(self.reminder_datetime)
    
    async def callback(self, interaction: nextcord.Interaction):
        try:
            # Parse the datetime string
            reminder_datetime_utc, tz_abbr, tz_name = self.cog.parse_datetime_string(self.reminder_datetime.value)
            
            # Check if the reminder is in the future
            if reminder_datetime_utc <= nextcord.utils.utcnow():
                await interaction.response.send_message("❌ Reminder time must be in the future!", ephemeral=True)
                return
            
            # Create the reminder
            reminder_id = await self.cog.create_reminder(
                creator_id=interaction.user.id,
                reminder_text=self.reminder_text.value,
                reminder_time=reminder_datetime_utc,
                original_channel_id=interaction.channel.id,
                timezone=tz_abbr,
            )
            
            # Create embed for the reminder
            embed = nextcord.Embed(
                title="⏰ Reminding this channel about...",
                description=self.reminder_text.value,
                color=nextcord.Color.blue(),
                timestamp=reminder_datetime_utc
            )
            
            embed.set_author(
                name=interaction.user.display_name,
                icon_url=interaction.user.display_avatar.url
            )
            
            # Use nextcord's format_dt for better time display
            embed.add_field(
                name="📅 When:", 
                value=f"{nextcord.utils.format_dt(reminder_datetime_utc, style='F')}\n{nextcord.utils.format_dt(reminder_datetime_utc, style='R')}", 
                inline=False
            )

            
            embed.set_footer(text=f"Reminder ID: {reminder_id}")
            
            # Create view with buttons
            view = ReminderView(reminder_id=reminder_id, cog=self.cog)
            
            message = await interaction.response.send_message(embed=embed, view=view)
            
            # Update the reminder with the message ID for future reference
            async with self.cog.bot.pg_pool.acquire() as conn:
                response_message = await interaction.original_message()
                await conn.execute(
                    f'''
                    UPDATE "{_EV}".reminders SET message_id = $1 WHERE reminder_id = $2
                    ''',
                    response_message.id,
                    reminder_id,
                )
            
        except ValueError as e:
            # Check if interaction was already responded to
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Invalid date/time format: {str(e)}\n\nExamples: `6/29 11:00am PST`, `12/25 14:30 EST`, `2025/06/29 23:45 UTC`", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Invalid date/time format: {str(e)}\n\nExamples: `6/29 11:00am PST`, `12/25 14:30 EST`, `2025/06/29 23:45 UTC`", ephemeral=True)
        except Exception as e:
            # Check if interaction was already responded to
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ An error occurred: {str(e)}", ephemeral=True)


class ReminderEditModal(nextcord.ui.Modal):
    def __init__(self, cog, reminder_id: int, current_text: str, current_time: str):
        super().__init__(title="Edit Reminder", timeout=300)
        self.cog = cog
        self.reminder_id = reminder_id
        
        # Pre-fill with current values
        self.reminder_text = nextcord.ui.TextInput(
            label="Reminder Text",
            placeholder="What would you like to be reminded about?",
            required=True,
            style=nextcord.TextInputStyle.paragraph,
            max_length=1000,
            default_value=current_text,
        )
        self.add_item(self.reminder_text)

        self.reminder_datetime = nextcord.ui.TextInput(
            label="Reminder Date & Time",
            placeholder="(6/29 11:00am PST  |  12/25 14:30 EST  |  2025/06/29 23:45 UTC)",
            required=True,
            max_length=50,
            default_value=current_time,
        )
        self.add_item(self.reminder_datetime)
    
    async def callback(self, interaction: nextcord.Interaction):
        try:
            # Parse the datetime string
            reminder_datetime_utc, tz_abbr, tz_name = self.cog.parse_datetime_string(self.reminder_datetime.value)
            
            # Check if the reminder is in the future
            if reminder_datetime_utc <= nextcord.utils.utcnow():
                await interaction.response.send_message("❌ Reminder time must be in the future!", ephemeral=True)
                return
            
            # Update the reminder
            success = await self.cog.update_reminder(
                reminder_id=self.reminder_id,
                reminder_text=self.reminder_text.value,
                reminder_time=reminder_datetime_utc,
                timezone=tz_abbr,
            )
            
            if success:
                embed = nextcord.Embed(
                    title="✅ Reminder Updated",
                    description="Reminder has been successfully updated!",
                    color=nextcord.Color.green()
                )
                embed.add_field(name="📝 New Text", value=self.reminder_text.value, inline=False)
                embed.add_field(
                    name="📅 New Time", 
                    value=f"{nextcord.utils.format_dt(reminder_datetime_utc, style='F')}\n{nextcord.utils.format_dt(reminder_datetime_utc, style='R')}", 
                    inline=False
                )
            else:
                embed = nextcord.Embed(
                    title="❌ Update Failed",
                    description="Failed to update the reminder.",
                    color=nextcord.Color.red()
                )
            
            await interaction.response.edit_message(embed=embed, view=None)
            
        except ValueError as e:
            # Check if interaction was already responded to
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Invalid date/time format: {str(e)}\n\nExamples: `6/29 11:00am PST`, `12/25 14:30 EST`, `2025/06/29 23:45 UTC`", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Invalid date/time format: {str(e)}\n\nExamples: `6/29 11:00am PST`, `12/25 14:30 EST`, `2025/06/29 23:45 UTC`", ephemeral=True)
        except Exception as e:
            # Check if interaction was already responded to
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ An error occurred: {str(e)}", ephemeral=True)

async def setup(bot):
    cog = Event(bot)
    await cog.create_tables()
    bot.add_cog(cog)
    boot_print("EventCog has been added to the bot.")

