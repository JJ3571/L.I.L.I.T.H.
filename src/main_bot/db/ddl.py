"""
PostgreSQL DDL: one database, one schema per former SQLite file.
Run after pool creation (e.g. from bot setup_hook).
"""

from __future__ import annotations

import asyncpg

from main_bot.server_configs.database_config import SCHEMA_KEYS


async def init_all_schemas(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        for key in SCHEMA_KEYS:
            await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{key}"')

        await _ddl_birthday(conn)
        await _ddl_buzzer(conn)
        await _ddl_counter(conn)
        await _ddl_coc(conn)
        await _ddl_economy(conn)
        await _ddl_event(conn)
        await _ddl_greek_gods(conn)
        await _ddl_pokemon(conn)
        await _ddl_powerups(conn)
        await _ddl_request(conn)
        await _ddl_wager(conn)
        await _ddl_waterboard(conn)
        await _ddl_tierlist(conn)
        await _ddl_trivia(conn)
        await _ddl_crafty_automation(conn)


async def _ddl_birthday(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "birthday".birthdays (
            user_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            birthday TEXT NOT NULL
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "birthday".birthday_messages (
            message_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            birthday TEXT NOT NULL
        )
        """
    )


async def _ddl_buzzer(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "buzzer".buzzer_entries (
            id BIGSERIAL PRIMARY KEY,
            message_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            username TEXT NOT NULL,
            buzz_time DOUBLE PRECISION NOT NULL
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "buzzer".buzzer_sessions (
            message_id BIGINT PRIMARY KEY,
            channel_id BIGINT NOT NULL,
            locked BOOLEAN NOT NULL DEFAULT FALSE,
            first_buzz_timestamp DOUBLE PRECISION DEFAULT NULL
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "buzzer".vote_sessions (
            message_id BIGINT PRIMARY KEY,
            channel_id BIGINT NOT NULL,
            num_options INTEGER NOT NULL,
            locked BOOLEAN NOT NULL DEFAULT FALSE
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "buzzer".votes (
            id BIGSERIAL PRIMARY KEY,
            message_id BIGINT NOT NULL,
            option_index INTEGER NOT NULL,
            user_id BIGINT NOT NULL,
            username TEXT NOT NULL,
            vote_time DOUBLE PRECISION NOT NULL
        )
        """
    )


async def _ddl_counter(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "counter".counters (
            user_id BIGINT PRIMARY KEY,
            current_count INTEGER NOT NULL DEFAULT 0,
            last_updated TEXT NOT NULL,
            created_at TEXT NOT NULL,
            category TEXT DEFAULT 'default'
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "counter".multi_counters (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            counter_name TEXT NOT NULL,
            option_labels TEXT NOT NULL,
            option_counts TEXT NOT NULL,
            last_updated TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (user_id, counter_name)
        )
        """
    )


async def _ddl_coc(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "coc".coc_usernames (
            account_id BIGSERIAL PRIMARY KEY,
            discord_user_id BIGINT NOT NULL,
            coc_username TEXT NOT NULL,
            town_hall_level TEXT,
            nickname TEXT,
            account_label TEXT
        )
        """
    )


async def _ddl_economy(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "economy".users (
            user_id BIGINT PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "economy".trust_fund (
            beneficiary_user_id BIGINT PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0
        )
        """
    )


async def _ddl_event(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "event".events (
            event_id BIGSERIAL PRIMARY KEY,
            creator_id BIGINT NOT NULL,
            event_name TEXT NOT NULL,
            event_description TEXT,
            event_time TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            max_attendees INTEGER,
            status TEXT DEFAULT 'active'
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "event".event_attendees (
            event_id BIGINT NOT NULL REFERENCES "event".events(event_id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL,
            joined_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'confirmed',
            PRIMARY KEY (event_id, user_id)
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "event".reminders (
            reminder_id BIGSERIAL PRIMARY KEY,
            creator_id BIGINT NOT NULL,
            reminder_text TEXT NOT NULL,
            reminder_time TIMESTAMPTZ NOT NULL,
            original_channel_id BIGINT NOT NULL,
            message_id BIGINT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active'
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "event".reminder_subscribers (
            reminder_id BIGINT NOT NULL REFERENCES "event".reminders(reminder_id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL,
            subscribed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (reminder_id, user_id)
        )
        """
    )


async def _ddl_greek_gods(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "greek_gods".god_results (
            user_id BIGINT PRIMARY KEY,
            god_name TEXT NOT NULL
        )
        """
    )


async def _ddl_pokemon(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "pokemon".friendcodes (
            discord_id BIGINT PRIMARY KEY,
            in_game_name TEXT NOT NULL,
            friend_code TEXT NOT NULL
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "pokemon".pokemon_teams (
            team_id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            team_name TEXT NOT NULL,
            description TEXT,
            generation_filter INTEGER,
            version_group_filter TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, team_name)
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "pokemon".team_members (
            member_id BIGSERIAL PRIMARY KEY,
            team_id BIGINT NOT NULL REFERENCES "pokemon".pokemon_teams(team_id) ON DELETE CASCADE,
            slot_number INTEGER NOT NULL CHECK (slot_number >= 1 AND slot_number <= 6),
            pokemon_id BIGINT NOT NULL,
            nickname TEXT,
            level INTEGER DEFAULT 50 CHECK (level >= 1 AND level <= 100),
            nature TEXT,
            ability TEXT,
            item TEXT,
            move1 TEXT,
            move2 TEXT,
            move3 TEXT,
            move4 TEXT,
            UNIQUE (team_id, slot_number)
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "pokemon".cached_pokemon_data (
            pokemon_id BIGINT PRIMARY KEY,
            name TEXT NOT NULL,
            species_name TEXT NOT NULL,
            generation INTEGER NOT NULL,
            primary_type TEXT NOT NULL,
            secondary_type TEXT,
            sprite_url TEXT,
            hp INTEGER NOT NULL,
            attack INTEGER NOT NULL,
            defense INTEGER NOT NULL,
            special_attack INTEGER NOT NULL,
            special_defense INTEGER NOT NULL,
            speed INTEGER NOT NULL,
            height INTEGER,
            weight INTEGER,
            abilities TEXT,
            cached_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "pokemon".cached_generations (
            generation_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            display_name TEXT NOT NULL,
            pokemon_species_count INTEGER,
            version_groups TEXT,
            cached_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "pokemon".cached_version_groups (
            version_group_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            display_name TEXT NOT NULL,
            generation_id INTEGER NOT NULL,
            versions TEXT,
            cached_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "pokemon".user_preferences (
            user_id BIGINT PRIMARY KEY,
            default_generation INTEGER,
            default_version_group TEXT,
            show_stats BOOLEAN DEFAULT TRUE,
            show_sprites BOOLEAN DEFAULT TRUE,
            preferred_team_size INTEGER DEFAULT 6 CHECK (preferred_team_size >= 1 AND preferred_team_size <= 6)
        )
        """
    )


async def _ddl_powerups(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "powerups".powerup_inventory (
            inventory_id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            powerup_type TEXT NOT NULL
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "powerups".active_powerups (
            user_id BIGINT NOT NULL,
            powerup_type TEXT NOT NULL,
            start_time BIGINT NOT NULL,
            end_time BIGINT NOT NULL,
            PRIMARY KEY (user_id, powerup_type)
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "powerups".daily_powerup_purchases (
            user_id BIGINT NOT NULL,
            powerup_type TEXT NOT NULL,
            purchase_date TEXT NOT NULL,
            PRIMARY KEY (user_id, powerup_type, purchase_date)
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "powerups".art_requests (
            request_id BIGSERIAL PRIMARY KEY,
            requester_user_id BIGINT NOT NULL,
            artist_user_id BIGINT NOT NULL,
            request_description TEXT NOT NULL,
            purchase_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            completion_date TEXT,
            rejection_reason TEXT,
            amount_paid INTEGER NOT NULL
        )
        """
    )


async def _ddl_request(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "request".requests (
            id BIGSERIAL PRIMARY KEY,
            type TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            requester_id BIGINT NOT NULL,
            requester_name TEXT NOT NULL,
            timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


async def _ddl_wager(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "wager".betting_events (
            event_id BIGSERIAL PRIMARY KEY,
            creator_user_id BIGINT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            message_id BIGINT,
            channel_id BIGINT,
            guild_id BIGINT,
            winning_outcome_id BIGINT,
            resolved_by_admin_id BIGINT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            closes_at TIMESTAMPTZ
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "wager".event_outcomes (
            outcome_id BIGSERIAL PRIMARY KEY,
            event_id BIGINT NOT NULL REFERENCES "wager".betting_events(event_id) ON DELETE CASCADE,
            outcome_text TEXT NOT NULL
        )
        """
    )
    await conn.execute(
        """
        ALTER TABLE "wager".betting_events
        DROP CONSTRAINT IF EXISTS betting_events_winning_outcome_id_fkey
        """
    )
    await conn.execute(
        """
        ALTER TABLE "wager".betting_events
        ADD CONSTRAINT betting_events_winning_outcome_id_fkey
        FOREIGN KEY (winning_outcome_id) REFERENCES "wager".event_outcomes(outcome_id)
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "wager".user_bets (
            bet_id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            event_id BIGINT NOT NULL REFERENCES "wager".betting_events(event_id) ON DELETE CASCADE,
            outcome_id BIGINT NOT NULL REFERENCES "wager".event_outcomes(outcome_id) ON DELETE CASCADE,
            amount INTEGER NOT NULL,
            placed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


async def _ddl_waterboard(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "waterboard".waterboarded_users (
            user_id BIGINT PRIMARY KEY,
            last_waterboarded_time DOUBLE PRECISION,
            usage_count INTEGER DEFAULT 0,
            total_waterboarded INTEGER DEFAULT 0,
            total_coins_spent INTEGER DEFAULT 0
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "waterboard".exempt_users (
            user_id BIGINT PRIMARY KEY,
            exempt_until DOUBLE PRECISION
        )
        """
    )


async def _ddl_tierlist(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "tierlist".tier_lists (
            list_id BIGSERIAL PRIMARY KEY,
            guild_id BIGINT NOT NULL,
            creator_id BIGINT NOT NULL,
            list_title TEXT NOT NULL,
            list_mode TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            duration_hours INTEGER DEFAULT 24,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            message_id BIGINT,
            channel_id BIGINT
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "tierlist".tier_options (
            option_id BIGSERIAL PRIMARY KEY,
            list_id BIGINT NOT NULL REFERENCES "tierlist".tier_lists(list_id),
            option_text TEXT NOT NULL,
            option_index INTEGER NOT NULL,
            image_url TEXT,
            local_image_path TEXT
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "tierlist".tier_votes (
            vote_id BIGSERIAL PRIMARY KEY,
            list_id BIGINT NOT NULL,
            option_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            tier_rank TEXT NOT NULL,
            tier_score INTEGER NOT NULL,
            voted_at TEXT NOT NULL,
            UNIQUE (list_id, option_id, user_id),
            FOREIGN KEY (list_id) REFERENCES "tierlist".tier_lists(list_id),
            FOREIGN KEY (option_id) REFERENCES "tierlist".tier_options(option_id)
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "tierlist".user_voting_progress (
            progress_id BIGSERIAL PRIMARY KEY,
            list_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            current_option_index INTEGER DEFAULT 0,
            is_complete INTEGER DEFAULT 0,
            UNIQUE (list_id, user_id),
            FOREIGN KEY (list_id) REFERENCES "tierlist".tier_lists(list_id)
        )
        """
    )


async def _ddl_trivia(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "trivia".trivia_scores (
            user_id BIGINT PRIMARY KEY,
            total_points INTEGER DEFAULT 0,
            questions_answered INTEGER DEFAULT 0,
            questions_correct INTEGER DEFAULT 0,
            last_played TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "trivia".trivia_history (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT,
            question TEXT,
            correct_answer TEXT,
            user_answer TEXT,
            is_correct BOOLEAN,
            difficulty TEXT,
            category TEXT,
            points_earned INTEGER,
            timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


async def _ddl_crafty_automation(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "crafty_automation".server_automation (
            server_id TEXT PRIMARY KEY,
            auto_shutdown_enabled BOOLEAN DEFAULT FALSE,
            idle_timeout_minutes INTEGER DEFAULT 10,
            always_online BOOLEAN DEFAULT FALSE,
            last_player_seen TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "crafty_automation".minecraft_whitelist_names (
            username TEXT PRIMARY KEY NOT NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS "crafty_automation".server_whitelist_ready (
            server_id TEXT PRIMARY KEY NOT NULL,
            whitelist_enabled_confirmed INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
