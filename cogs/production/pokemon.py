import aiohttp
import nextcord
from nextcord.ext import commands
import sqlite3
import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
import difflib

from server_configs.config import GUILD_ID
from server_configs.config import admin_user_ids
from server_configs.database_config import DATABASE_PATHS


pkgo_api_url = "https://pogoapi.net/api/v1/"
raid_bosses_key = "raid_bosses.json"

# PokeAPI configuration
POKEAPI_BASE_URL = "https://pokeapi.co/api/v2"
CACHE_EXPIRY_HOURS = 24  # Cache Pokemon data for 24 hours
MAX_CONCURRENT_REQUESTS = 10  # Limit concurrent API requests to be respectful

class FriendCodePaginationView(nextcord.ui.View):
    def __init__(self, users, bot, per_page=9):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.users = users
        self.bot = bot
        self.per_page = per_page
        self.current_page = 0
        self.max_pages = (len(users) - 1) // per_page + 1
        
        # Update button states
        self.update_buttons()
    
    def update_buttons(self):
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == self.max_pages - 1
        
        # Hide buttons if only one page
        if self.max_pages <= 1:
            self.previous_button.style = nextcord.ButtonStyle.gray
            self.next_button.style = nextcord.ButtonStyle.gray
            self.previous_button.disabled = True
            self.next_button.disabled = True
    
    def create_embed(self):
        start_idx = self.current_page * self.per_page
        end_idx = min(start_idx + self.per_page, len(self.users))
        page_users = self.users[start_idx:end_idx]
        
        embed = nextcord.Embed(
            title="🎮 Clan Friend Codes",
            description=f"Page {self.current_page + 1} of {self.max_pages}",
            color=nextcord.Color.red()
        )
        
        for discord_id, in_game_name, friend_code in page_users:
            # Format the friend code into 4-number chunks for display
            formatted_friend_code = " ".join([friend_code[i:i+4] for i in range(0, 12, 4)])
            
            # Create individual field for each user
            # Field name: IGN, Field value: Discord mention + friend code
            field_value = f"```{formatted_friend_code}```\n🔹<@{discord_id}>\n" + "_" * 24
            
            embed.add_field(
                name=f"♦️ IGN: {in_game_name}",
                value=field_value,
                inline=True
            )
        
        embed.set_footer(text=f"Total members: {len(self.users)}")
        
        return embed
    
    @nextcord.ui.button(label="◀", style=nextcord.ButtonStyle.primary)
    async def previous_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            embed = self.create_embed()
            await interaction.response.edit_message(embed=embed, view=self)
    
    @nextcord.ui.button(label="▶", style=nextcord.ButtonStyle.primary)
    async def next_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if self.current_page < self.max_pages - 1:
            self.current_page += 1
            self.update_buttons()
            embed = self.create_embed()
            await interaction.response.edit_message(embed=embed, view=self)
    
    async def on_timeout(self):
        # Disable all buttons when the view times out
        for item in self.children:
            item.disabled = True

class Pokemon(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = DATABASE_PATHS["pokemon"]
        self.create_tables()
        
        # Initialize Pokemon name cache for autocomplete
        self.pokemon_name_cache = {}  # {id: {'name': str, 'generation': int}}
        self.pokemon_name_list = []   # List of (name, id) tuples for fuzzy matching
        self.cache_last_updated = None
        self.cache_task = None

    def create_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Original friend codes table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS friendcodes (
                discord_id INT PRIMARY KEY,
                in_game_name TEXT NOT NULL,
                friend_code TEXT NOT NULL
            )
        ''')

        # Pokemon teams table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pokemon_teams (
                team_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                team_name TEXT NOT NULL,
                description TEXT,
                generation_filter INTEGER,
                version_group_filter TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, team_name)
            )
        ''')

        # Pokemon team members table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS team_members (
                member_id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                slot_number INTEGER NOT NULL CHECK(slot_number >= 1 AND slot_number <= 6),
                pokemon_id INTEGER NOT NULL,
                nickname TEXT,
                level INTEGER DEFAULT 50 CHECK(level >= 1 AND level <= 100),
                nature TEXT,
                ability TEXT,
                item TEXT,
                move1 TEXT,
                move2 TEXT,
                move3 TEXT,
                move4 TEXT,
                FOREIGN KEY(team_id) REFERENCES pokemon_teams(team_id) ON DELETE CASCADE,
                UNIQUE(team_id, slot_number)
            )
        ''')

        # Cached Pokemon data for performance
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cached_pokemon_data (
                pokemon_id INTEGER PRIMARY KEY,
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
                abilities TEXT, -- JSON array of abilities
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Generation data cache
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cached_generations (
                generation_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                display_name TEXT NOT NULL,
                pokemon_species_count INTEGER,
                version_groups TEXT, -- JSON array of version groups
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Version group data cache
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cached_version_groups (
                version_group_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                display_name TEXT NOT NULL,
                generation_id INTEGER NOT NULL,
                versions TEXT, -- JSON array of individual versions
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # User preferences for team building
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id INTEGER PRIMARY KEY,
                default_generation INTEGER,
                default_version_group TEXT,
                show_stats BOOLEAN DEFAULT 1,
                show_sprites BOOLEAN DEFAULT 1,
                preferred_team_size INTEGER DEFAULT 6 CHECK(preferred_team_size >= 1 AND preferred_team_size <= 6)
            )
        ''')

        conn.commit()
        conn.close()

    def add_user(self, discord_id, in_game_name, friend_code):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO friendcodes (discord_id, in_game_name, friend_code) VALUES (?, ?, ?)',
                       (discord_id, in_game_name, friend_code))
        conn.commit()
        conn.close()

    def get_user(self, discord_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT in_game_name, friend_code FROM friendcodes WHERE discord_id = ?', (discord_id,))
        user = cursor.fetchone()
        conn.close()
        return user

    def get_all_users(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT discord_id, in_game_name, friend_code FROM friendcodes')
        users = cursor.fetchall()
        conn.close()
        return users

    # --- PokeAPI Integration Methods ---
    
    async def fetch_from_pokeapi(self, endpoint: str, session: aiohttp.ClientSession = None) -> Optional[Dict]:
        """Fetch data from PokeAPI with error handling and respect for rate limits"""
        url = f"{POKEAPI_BASE_URL}/{endpoint.lstrip('/')}"
        
        if session:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 429:
                    # Rate limited, wait and retry once
                    await asyncio.sleep(1)
                    async with session.get(url) as retry_response:
                        if retry_response.status == 200:
                            return await retry_response.json()
                return None
        else:
            async with aiohttp.ClientSession() as temp_session:
                return await self.fetch_from_pokeapi(endpoint, temp_session)
    
    async def get_cached_pokemon_data(self, pokemon_id: int) -> Optional[Dict]:
        """Get Pokemon data from cache, or fetch from API if not cached/expired"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check if data exists and is fresh
        cursor.execute('''
            SELECT * FROM cached_pokemon_data 
            WHERE pokemon_id = ? AND datetime(cached_at, '+{} hours') > datetime('now')
        '''.format(CACHE_EXPIRY_HOURS), (pokemon_id,))
        
        cached_data = cursor.fetchone()
        conn.close()
        
        if cached_data:
            # Convert row to dictionary
            columns = ['pokemon_id', 'name', 'species_name', 'generation', 'primary_type', 'secondary_type', 
                      'sprite_url', 'hp', 'attack', 'defense', 'special_attack', 'special_defense', 'speed',
                      'height', 'weight', 'abilities', 'cached_at']
            pokemon_data = dict(zip(columns, cached_data))
            pokemon_data['abilities'] = json.loads(pokemon_data['abilities'])
            return pokemon_data
        
        # Fetch fresh data from API
        return await self.fetch_and_cache_pokemon_data(pokemon_id)
    
    async def fetch_and_cache_pokemon_data(self, pokemon_id: int) -> Optional[Dict]:
        """Fetch Pokemon data from PokeAPI and cache it"""
        async with aiohttp.ClientSession() as session:
            # Fetch Pokemon data
            pokemon_data = await self.fetch_from_pokeapi(f"pokemon/{pokemon_id}", session)
            if not pokemon_data:
                return None
            
            # Fetch species data for generation info
            species_data = await self.fetch_from_pokeapi(f"pokemon-species/{pokemon_id}", session)
            if not species_data:
                return None
            
            # Extract relevant information
            abilities = [ability['ability']['name'] for ability in pokemon_data['abilities']]
            
            # Get generation from species data
            generation_url = species_data['generation']['url']
            generation_id = int(generation_url.split('/')[-2])
            
            # Parse stats
            stats = {stat['stat']['name']: stat['base_stat'] for stat in pokemon_data['stats']}
            
            # Parse types
            types = [type_data['type']['name'] for type_data in pokemon_data['types']]
            primary_type = types[0] if types else None
            secondary_type = types[1] if len(types) > 1 else None
            
            # Get sprite URL
            sprite_url = pokemon_data['sprites']['front_default']
            
            # Prepare data for caching
            cache_data = {
                'pokemon_id': pokemon_id,
                'name': pokemon_data['name'],
                'species_name': species_data['name'],
                'generation': generation_id,
                'primary_type': primary_type,
                'secondary_type': secondary_type,
                'sprite_url': sprite_url,
                'hp': stats.get('hp', 0),
                'attack': stats.get('attack', 0),
                'defense': stats.get('defense', 0),
                'special_attack': stats.get('special-attack', 0),
                'special_defense': stats.get('special-defense', 0),
                'speed': stats.get('speed', 0),
                'height': pokemon_data['height'],
                'weight': pokemon_data['weight'],
                'abilities': abilities
            }
            
            # Cache the data
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO cached_pokemon_data 
                (pokemon_id, name, species_name, generation, primary_type, secondary_type,
                 sprite_url, hp, attack, defense, special_attack, special_defense, speed,
                 height, weight, abilities, cached_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ''', (
                cache_data['pokemon_id'], cache_data['name'], cache_data['species_name'],
                cache_data['generation'], cache_data['primary_type'], cache_data['secondary_type'],
                cache_data['sprite_url'], cache_data['hp'], cache_data['attack'], cache_data['defense'],
                cache_data['special_attack'], cache_data['special_defense'], cache_data['speed'],
                cache_data['height'], cache_data['weight'], json.dumps(cache_data['abilities'])
            ))
            conn.commit()
            conn.close()
            
            return cache_data
    
    async def get_generation_pokemon_list(self, generation_id: int) -> List[Dict]:
        """Get list of Pokemon available in a specific generation"""
        generation_data = await self.fetch_from_pokeapi(f"generation/{generation_id}")
        if not generation_data:
            return []
        
        pokemon_list = []
        for species in generation_data['pokemon_species']:
            # Extract Pokemon ID from URL
            pokemon_id = int(species['url'].split('/')[-2])
            pokemon_list.append({
                'id': pokemon_id,
                'name': species['name'],
                'display_name': species['name'].replace('-', ' ').title()
            })
        
        return sorted(pokemon_list, key=lambda x: x['id'])
    
    async def search_pokemon(self, query: str, generation_filter: Optional[int] = None, limit: int = 25) -> List[Dict]:
        """Search for Pokemon by name with optional generation filtering"""
        if generation_filter:
            # Get Pokemon list for specific generation
            generation_pokemon = await self.get_generation_pokemon_list(generation_filter)
            matching_pokemon = [
                p for p in generation_pokemon 
                if query.lower() in p['name'].lower() or query.lower() in p['display_name'].lower()
            ]
        else:
            # Search all Pokemon (this would need a different approach for efficiency)
            # For now, we'll implement a basic search by trying common Pokemon IDs
            matching_pokemon = []
            
            # This is a simplified approach - in production, you might want to 
            # cache all Pokemon names for better search functionality
            async with aiohttp.ClientSession() as session:
                for pokemon_id in range(1, min(1026, limit * 5)):  # Current max Pokemon ID
                    try:
                        pokemon_data = await self.fetch_from_pokeapi(f"pokemon-species/{pokemon_id}", session)
                        if pokemon_data and query.lower() in pokemon_data['name'].lower():
                            matching_pokemon.append({
                                'id': pokemon_id,
                                'name': pokemon_data['name'],
                                'display_name': pokemon_data['name'].replace('-', ' ').title()
                            })
                            if len(matching_pokemon) >= limit:
                                break
                    except:
                        continue
        
        return matching_pokemon[:limit]
    
    # --- Team Management Methods ---
    
    async def create_team(self, user_id: int, team_name: str, description: str = None, 
                         generation_filter: int = None, version_group_filter: str = None) -> int:
        """Create a new Pokemon team"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO pokemon_teams (user_id, team_name, description, generation_filter, version_group_filter)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, team_name, description, generation_filter, version_group_filter))
            team_id = cursor.lastrowid
            conn.commit()
            return team_id
        except sqlite3.IntegrityError:
            raise ValueError(f"Team '{team_name}' already exists for this user")
        finally:
            conn.close()
    
    async def get_user_teams(self, user_id: int) -> List[Dict]:
        """Get all teams for a user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT team_id, team_name, description, generation_filter, version_group_filter, 
                   created_at, updated_at
            FROM pokemon_teams 
            WHERE user_id = ? 
            ORDER BY updated_at DESC
        ''', (user_id,))
        
        teams = []
        for row in cursor.fetchall():
            team_data = {
                'team_id': row[0],
                'team_name': row[1],
                'description': row[2],
                'generation_filter': row[3],
                'version_group_filter': row[4],
                'created_at': row[5],
                'updated_at': row[6]
            }
            
            # Get team member count
            cursor.execute('SELECT COUNT(*) FROM team_members WHERE team_id = ?', (row[0],))
            team_data['member_count'] = cursor.fetchone()[0]
            
            teams.append(team_data)
        
        conn.close()
        return teams
    
    async def get_team_details(self, team_id: int, user_id: int = None) -> Optional[Dict]:
        """Get detailed information about a team"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get team info
        query = 'SELECT * FROM pokemon_teams WHERE team_id = ?'
        params = [team_id]
        if user_id:
            query += ' AND user_id = ?'
            params.append(user_id)
        
        cursor.execute(query, params)
        team_row = cursor.fetchone()
        
        if not team_row:
            conn.close()
            return None
        
        team_data = {
            'team_id': team_row[0],
            'user_id': team_row[1],
            'team_name': team_row[2],
            'description': team_row[3],
            'generation_filter': team_row[4],
            'version_group_filter': team_row[5],
            'created_at': team_row[6],
            'updated_at': team_row[7],
            'members': []
        }
        
        # Get team members
        cursor.execute('''
            SELECT slot_number, pokemon_id, nickname, level, nature, ability, item,
                   move1, move2, move3, move4
            FROM team_members 
            WHERE team_id = ? 
            ORDER BY slot_number
        ''', (team_id,))
        
        for member_row in cursor.fetchall():
            member_data = {
                'slot_number': member_row[0],
                'pokemon_id': member_row[1],
                'nickname': member_row[2],
                'level': member_row[3],
                'nature': member_row[4],
                'ability': member_row[5],
                'item': member_row[6],
                'moves': [member_row[7], member_row[8], member_row[9], member_row[10]]
            }
            
            # Filter out None moves
            member_data['moves'] = [move for move in member_data['moves'] if move]
            
            team_data['members'].append(member_data)
        
        conn.close()
        return team_data
    
    async def add_pokemon_to_team(self, team_id: int, pokemon_id: int, slot_number: int,
                                 nickname: str = None, level: int = 50, nature: str = None,
                                 ability: str = None, item: str = None, moves: List[str] = None) -> bool:
        """Add a Pokemon to a team slot"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Validate that the Pokemon exists (try to get its data)
        pokemon_data = await self.get_cached_pokemon_data(pokemon_id)
        if not pokemon_data:
            conn.close()
            return False
        
        # Prepare moves (up to 4)
        move_data = [None, None, None, None]
        if moves:
            for i, move in enumerate(moves[:4]):
                move_data[i] = move
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO team_members 
                (team_id, slot_number, pokemon_id, nickname, level, nature, ability, item,
                 move1, move2, move3, move4)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (team_id, slot_number, pokemon_id, nickname, level, nature, ability, item,
                  move_data[0], move_data[1], move_data[2], move_data[3]))
            
            # Update team's updated_at timestamp
            cursor.execute('''
                UPDATE pokemon_teams 
                SET updated_at = datetime('now') 
                WHERE team_id = ?
            ''', (team_id,))
            
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()
    
    async def remove_pokemon_from_team(self, team_id: int, slot_number: int) -> bool:
        """Remove a Pokemon from a team slot"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM team_members WHERE team_id = ? AND slot_number = ?', 
                      (team_id, slot_number))
        
        if cursor.rowcount > 0:
            # Update team's updated_at timestamp
            cursor.execute('''
                UPDATE pokemon_teams 
                SET updated_at = datetime('now') 
                WHERE team_id = ?
            ''', (team_id,))
            conn.commit()
            conn.close()
            return True
        
        conn.close()
        return False
    
    async def delete_team(self, team_id: int, user_id: int) -> bool:
        """Delete a team (only by owner)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM pokemon_teams WHERE team_id = ? AND user_id = ?', 
                      (team_id, user_id))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success

    # === Pokemon Name Cache Methods ===
    async def build_pokemon_name_cache(self):
        """Build comprehensive Pokemon name cache for autocomplete"""
        if self.cache_last_updated and datetime.now() - self.cache_last_updated < timedelta(hours=6):
            return  # Cache is still fresh
        
        print("Building Pokemon name cache...")
        self.pokemon_name_cache = {}
        self.pokemon_name_list = []
        
        try:
            async with aiohttp.ClientSession() as session:
                # Get all Pokemon species (up to generation 9 - around 1010 Pokemon)
                async with session.get(f"{POKEAPI_BASE_URL}/pokemon-species?limit=1010") as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Extract Pokemon names and IDs with generation info
                        for species in data['results']:
                            # Extract ID from URL
                            pokemon_id = int(species['url'].split('/')[-2])
                            name = species['name'].replace('-', ' ').title()
                            
                            # Get generation info (rough approximation based on ID ranges)
                            if pokemon_id <= 151:
                                generation = 1
                            elif pokemon_id <= 251:
                                generation = 2
                            elif pokemon_id <= 386:
                                generation = 3
                            elif pokemon_id <= 493:
                                generation = 4
                            elif pokemon_id <= 649:
                                generation = 5
                            elif pokemon_id <= 721:
                                generation = 6
                            elif pokemon_id <= 809:
                                generation = 7
                            elif pokemon_id <= 898:
                                generation = 8
                            else:
                                generation = 9
                            
                            # Store in cache
                            self.pokemon_name_cache[pokemon_id] = {
                                'name': name,
                                'original_name': species['name'],  # Keep original for API calls
                                'generation': generation
                            }
                            self.pokemon_name_list.append((name, pokemon_id))
                        
                        self.cache_last_updated = datetime.now()
                        print(f"Pokemon name cache built with {len(self.pokemon_name_cache)} Pokemon")
                    else:
                        print(f"Failed to build Pokemon cache: HTTP {response.status}")
        except Exception as e:
            print(f"Error building Pokemon name cache: {e}")

    async def get_pokemon_suggestions(self, current_input: str, generation: Optional[int] = None, limit: int = 25) -> List[Tuple[str, int]]:
        """Get Pokemon name suggestions for autocomplete"""
        if not self.pokemon_name_cache:
            await self.build_pokemon_name_cache()
        
        # Filter by generation if specified
        filtered_list = self.pokemon_name_list
        if generation:
            filtered_list = []
            for name, pokemon_id in self.pokemon_name_list:
                # Get generation info from name cache (faster than database lookup)
                if pokemon_id in self.pokemon_name_cache:
                    cached_gen = self.pokemon_name_cache[pokemon_id].get('generation', 9)
                    if cached_gen <= generation:
                        filtered_list.append((name, pokemon_id))
        
        if not current_input:
            # Return first few Pokemon if no input
            return filtered_list[:limit]
        
        current_input_lower = current_input.lower()
        suggestions = []
        
        # First, exact matches and starts-with matches
        for name, pokemon_id in filtered_list:
            name_lower = name.lower()
            if name_lower == current_input_lower:
                suggestions.insert(0, (name, pokemon_id))  # Exact match goes first
            elif name_lower.startswith(current_input_lower):
                suggestions.append((name, pokemon_id))
        
        # Then, contains matches
        if len(suggestions) < limit:
            for name, pokemon_id in filtered_list:
                name_lower = name.lower()
                if current_input_lower in name_lower and not name_lower.startswith(current_input_lower):
                    suggestions.append((name, pokemon_id))
                    if len(suggestions) >= limit:
                        break
        
        # Finally, fuzzy matches if we still need more
        if len(suggestions) < limit:
            remaining_names = [(name, pokemon_id) for name, pokemon_id in filtered_list 
                             if (name, pokemon_id) not in suggestions]
            fuzzy_matches = difflib.get_close_matches(
                current_input, 
                [name for name, _ in remaining_names], 
                n=limit - len(suggestions), 
                cutoff=0.4
            )
            for fuzzy_name in fuzzy_matches:
                for name, pokemon_id in remaining_names:
                    if name == fuzzy_name:
                        suggestions.append((name, pokemon_id))
                        break

        return suggestions[:limit]

    async def pokemon_autocomplete(self, interaction: nextcord.Interaction, current: str):
        """Autocomplete function for Pokemon names"""
        try:
            # Try to get generation filter from command options if available
            generation_filter = None
            if hasattr(interaction, 'data') and 'options' in interaction.data:
                for option in interaction.data['options']:
                    if option['name'] == 'generation' and 'value' in option:
                        generation_filter = option['value']
                        break
            
            suggestions = await self.get_pokemon_suggestions(current, generation_filter, limit=25)
            return [nextcord.SlashOption(name=f"{name} (#{pokemon_id})", value=str(pokemon_id)) 
                   for name, pokemon_id in suggestions]
        except Exception as e:
            print(f"Error in pokemon_autocomplete: {e}")
            return []

    @nextcord.slash_command(name="pkgo", description="Parent command for Pokemon Go related commands", guild_ids=[GUILD_ID])
    async def pkgo(self, interaction: nextcord.Interaction):
        pass  # This is the parent command, it won't do anything by itself

    @nextcord.slash_command(name="pokemon", description="Pokemon team building and management", guild_ids=[GUILD_ID])
    async def pokemon_command(self, interaction: nextcord.Interaction):
        pass  # This is the parent command, it won't do anything by itself

    # @pkgo.subcommand(name="raidboss", description="Fetch current raid bosses")
    # async def raidboss(self, interaction: nextcord.Interaction, name: str = None):
    #     await interaction.response.defer()
        
    #     async with aiohttp.ClientSession() as session:
    #         async with session.get(f"{pkgo_api_url+raid_bosses_key}") as response:
    #             raid_boss_data = await response.json()
    #             print(raid_boss_data)  # Debugging: Print the response data
        
    #     current_bosses = raid_boss_data.get('current', {})
    #     previous_bosses = raid_boss_data.get('previous', {})
    #     tiers_to_include = ['5', '6', 'mega']
    #     embeds = []

    #     inline_toggle = False

    #     def create_embed(boss):
    #         embed = nextcord.Embed(
    #             title=f"**{boss['name']}**",  # Bold the name
    #             color=nextcord.Color.red()
    #         )
    #         embed.add_field(name="**Type**", value=", ".join(boss['type']), inline=inline_toggle)
    #         embed.add_field(name="**Boosted Hundo**", value=boss['max_boosted_cp'], inline=inline_toggle)
    #         embed.add_field(name="**Normal Hundo**", value=boss['max_unboosted_cp'], inline=inline_toggle)
    #         return embed

    #     if name:
    #         found = False
    #         for tier, bosses in current_bosses.items():
    #             for boss in bosses:
    #                 if boss['name'].lower() == name.lower():
    #                     embeds.append(create_embed(boss))
    #                     found = True
    #                     break
    #             if found:
    #                 break

    #         if not found:
    #             for tier, bosses in previous_bosses.items():
    #                 for boss in bosses:
    #                     if boss['name'].lower() == name.lower():
    #                         embeds.append(create_embed(boss))
    #                         found = True
    #                         break
    #                 if found:
    #                     break

    #         if not found:
    #             await interaction.followup.send(f"No raid boss found with the name {name}.")
    #             return
    #     else:
    #         for tier in tiers_to_include:
    #             bosses = current_bosses.get(tier, [])
    #             for boss in bosses:
    #                 embeds.append(create_embed(boss))
        
    #     for embed in embeds:
    #         await interaction.followup.send(embed=embed)


    @pkgo.subcommand(name="add-friendcode", description="Add yourself to the Clan friendcode roster!")
    async def adduser(self, interaction: nextcord.Interaction, in_game_name: str, friend_code: str):
        # Remove spaces from the input
        sanitized_friend_code = friend_code.replace(" ", "")

        # Validate that the friend code contains only digits and is exactly 12 characters long
        if not sanitized_friend_code.isdigit() or len(sanitized_friend_code) != 12:
            await interaction.response.send_message(
                "Invalid friend code! Please ensure it contains exactly 12 digits and no letters or special characters.",
                ephemeral=True
            )
            return

        # Store the sanitized friend code (without spaces) in the database
        discord_id = str(interaction.user.id)
        self.add_user(discord_id, in_game_name, sanitized_friend_code)

        # Format the friend code into 4-number chunks for display
        formatted_friend_code = " ".join([sanitized_friend_code[i:i+4] for i in range(0, 12, 4)])

        await interaction.response.send_message(
            f"User {interaction.user.mention} added with in-game name {in_game_name} and friend code `{formatted_friend_code}`"
        )

    @pkgo.subcommand(name="friendcode", description="Displays the IGN and friend code of a user")
    async def user(self, interaction: nextcord.Interaction, user: nextcord.User):
        discord_id = str(user.id)
        user_data = self.get_user(discord_id)
        if user_data:
            in_game_name, friend_code = user_data

            # Format the friend code into 4-number chunks for display
            formatted_friend_code = " ".join([friend_code[i:i+4] for i in range(0, 12, 4)])

            embed = nextcord.Embed(title=f"{user.display_name}'s Friend Code", color=nextcord.Color.red())
            embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
            embed.add_field(name="In-Game Name", value=in_game_name, inline=True)
            embed.add_field(name="Friend Code", value=f"```{formatted_friend_code}```", inline=True)
            await interaction.response.send_message(embed=embed)

        else:
            await interaction.response.send_message(f"No data found for {user.mention}")

    @pkgo.subcommand(name="clan-friendcodes", description="Get a list of all friend codes for the Clan!")
    async def allusers(self, interaction: nextcord.Interaction):
        await interaction.response.defer()
        users = self.get_all_users()
        
        if not users:
            await interaction.followup.send("No users found in the clan roster.")
            return

        # Sort users alphabetically by in-game name (case-insensitive)
        users.sort(key=lambda user: user[1].lower())  # user[1] is the in_game_name

        # Create paginated view
        view = FriendCodePaginationView(users, self.bot)
        embed = view.create_embed()
        
        await interaction.followup.send(embed=embed, view=view)

    # --- Pokemon Team Commands ---
    
    @pokemon_command.subcommand(name="team-create", description="Create a new Pokemon team")
    async def team_create(self, interaction: nextcord.Interaction, 
                         team_name: str,
                         description: str = None,
                         generation: int = nextcord.SlashOption(description="Filter Pokemon to specific generation (1-9)", 
                                                              required=False, min_value=1, max_value=9)):
        """Create a new Pokemon team"""
        await interaction.response.defer()
        
        try:
            team_id = await self.create_team(
                user_id=interaction.user.id,
                team_name=team_name,
                description=description,
                generation_filter=generation
            )
            
            embed = nextcord.Embed(
                title="✅ Team Created!",
                description=f"Successfully created team **{team_name}**",
                color=nextcord.Color.green()
            )
            embed.add_field(name="Team ID", value=str(team_id), inline=True)
            if description:
                embed.add_field(name="Description", value=description, inline=False)
            if generation:
                embed.add_field(name="Generation Filter", value=f"Generation {generation}", inline=True)
            
            embed.set_footer(text="Use /pokemon team-add to add Pokemon to your team!")
            
            await interaction.followup.send(embed=embed)
            
        except ValueError as e:
            embed = nextcord.Embed(
                title="❌ Error",
                description=str(e),
                color=nextcord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @pokemon_command.subcommand(name="team-list", description="View all your Pokemon teams")
    async def team_list(self, interaction: nextcord.Interaction):
        """List all teams for the user"""
        await interaction.response.defer()
        
        teams = await self.get_user_teams(interaction.user.id)
        
        if not teams:
            embed = nextcord.Embed(
                title="📋 Your Pokemon Teams",
                description="You haven't created any teams yet!\nUse `/pokemon team-create` to get started.",
                color=nextcord.Color.blue()
            )
            await interaction.followup.send(embed=embed)
            return
        
        embed = nextcord.Embed(
            title=f"📋 {interaction.user.display_name}'s Pokemon Teams",
            color=nextcord.Color.blue()
        )
        
        for team in teams:
            field_value = f"**Members:** {team['member_count']}/6\n"
            if team['description']:
                field_value += f"**Description:** {team['description']}\n"
            if team['generation_filter']:
                field_value += f"**Generation:** {team['generation_filter']}\n"
            field_value += f"**Created:** <t:{int(datetime.fromisoformat(team['created_at']).timestamp())}:R>"
            
            embed.add_field(
                name=f"🎮 {team['team_name']} (ID: {team['team_id']})",
                value=field_value,
                inline=False
            )
        
        embed.set_footer(text="Use /pokemon team-view <team_id> to see team details")
        await interaction.followup.send(embed=embed)
    
    @pokemon_command.subcommand(name="team-view", description="View details of a specific team")
    async def team_view(self, interaction: nextcord.Interaction, 
                       team_id: int):
        """View detailed information about a team"""
        await interaction.response.defer()
        
        team_data = await self.get_team_details(team_id, interaction.user.id)
        
        if not team_data:
            embed = nextcord.Embed(
                title="❌ Team Not Found",
                description="Team not found or you don't have permission to view it.",
                color=nextcord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        embed = nextcord.Embed(
            title=f"🎮 {team_data['team_name']}",
            color=nextcord.Color.blue()
        )
        
        if team_data['description']:
            embed.description = team_data['description']
        
        # Add team info
        info_text = f"**Team ID:** {team_data['team_id']}\n"
        info_text += f"**Members:** {len(team_data['members'])}/6\n"
        if team_data['generation_filter']:
            info_text += f"**Generation Filter:** {team_data['generation_filter']}\n"
        info_text += f"**Created:** <t:{int(datetime.fromisoformat(team_data['created_at']).timestamp())}:R>"
        
        embed.add_field(name="📊 Team Info", value=info_text, inline=False)
        
        # Add team members
        if team_data['members']:
            for member in team_data['members']:
                # Get Pokemon data for display
                pokemon_data = await self.get_cached_pokemon_data(member['pokemon_id'])
                if pokemon_data:
                    pokemon_name = member['nickname'] or pokemon_data['name'].title()
                    
                    member_text = f"**Species:** {pokemon_data['name'].title()}\n"
                    member_text += f"**Level:** {member['level']}\n"
                    member_text += f"**Type:** {pokemon_data['primary_type'].title()}"
                    if pokemon_data['secondary_type']:
                        member_text += f"/{pokemon_data['secondary_type'].title()}"
                    member_text += "\n"
                    
                    if member['nature']:
                        member_text += f"**Nature:** {member['nature'].title()}\n"
                    if member['ability']:
                        member_text += f"**Ability:** {member['ability'].title()}\n"
                    if member['item']:
                        member_text += f"**Item:** {member['item'].title()}\n"
                    if member['moves']:
                        member_text += f"**Moves:** {', '.join([move.title() for move in member['moves']])}"
                    
                    embed.add_field(
                        name=f"#{member['slot_number']} {pokemon_name}",
                        value=member_text,
                        inline=True
                    )
        else:
            embed.add_field(
                name="👥 Team Members",
                value="No Pokemon added yet!\nUse `/pokemon team-add` to add Pokemon to this team.",
                inline=False
            )
        
        await interaction.followup.send(embed=embed)
    
    @pokemon_command.subcommand(name="team-add", description="Add a Pokemon to your team")
    async def team_add(self, interaction: nextcord.Interaction,
                      team_id: int,
                      slot: int = nextcord.SlashOption(description="Team slot (1-6)", min_value=1, max_value=6),
                      pokemon: str = nextcord.SlashOption(description="Pokemon name or ID", autocomplete=True),
                      nickname: str = None,
                      level: int = nextcord.SlashOption(description="Pokemon level", default=50, min_value=1, max_value=100),
                      nature: str = None,
                      ability: str = None,
                      item: str = None):
        """Add a Pokemon to a team"""
        await interaction.response.defer()
        
        # Verify team ownership
        team_data = await self.get_team_details(team_id, interaction.user.id)
        if not team_data:
            embed = nextcord.Embed(
                title="❌ Team Not Found",
                description="Team not found or you don't have permission to edit it.",
                color=nextcord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Try to parse Pokemon ID or search by name
        pokemon_id = None
        if pokemon.isdigit():
            pokemon_id = int(pokemon)
        else:
            # Search for Pokemon by name
            search_results = await self.search_pokemon(pokemon, team_data['generation_filter'], limit=1)
            if search_results:
                pokemon_id = search_results[0]['id']
        
        if not pokemon_id:
            embed = nextcord.Embed(
                title="❌ Pokemon Not Found",
                description=f"Could not find Pokemon '{pokemon}'. Try using the Pokemon's name or Pokedex number.",
                color=nextcord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Check generation filter
        if team_data['generation_filter']:
            pokemon_data = await self.get_cached_pokemon_data(pokemon_id)
            if pokemon_data and pokemon_data['generation'] > team_data['generation_filter']:
                embed = nextcord.Embed(
                    title="❌ Generation Restriction",
                    description=f"This Pokemon is from Generation {pokemon_data['generation']}, but your team is limited to Generation {team_data['generation_filter']}.",
                    color=nextcord.Color.red()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
        
        # Add Pokemon to team
        success = await self.add_pokemon_to_team(
            team_id=team_id,
            pokemon_id=pokemon_id,
            slot_number=slot,
            nickname=nickname,
            level=level,
            nature=nature,
            ability=ability,
            item=item,
            moves=[]  # We'll add move selection in a future enhancement
        )
        
        if success:
            pokemon_data = await self.get_cached_pokemon_data(pokemon_id)
            display_name = nickname or pokemon_data['name'].title()
            
            embed = nextcord.Embed(
                title="✅ Pokemon Added!",
                description=f"Successfully added **{display_name}** to slot #{slot} of team **{team_data['team_name']}**",
                color=nextcord.Color.green()
            )
            
            if pokemon_data:
                embed.add_field(name="Species", value=pokemon_data['name'].title(), inline=True)
                embed.add_field(name="Level", value=str(level), inline=True)
                embed.add_field(name="Type", value=f"{pokemon_data['primary_type'].title()}" + 
                               (f"/{pokemon_data['secondary_type'].title()}" if pokemon_data['secondary_type'] else ""), inline=True)
                
                if pokemon_data['sprite_url']:
                    embed.set_thumbnail(url=pokemon_data['sprite_url'])
            
            await interaction.followup.send(embed=embed)
        else:
            embed = nextcord.Embed(
                title="❌ Failed to Add Pokemon",
                description="Could not add Pokemon to team. The Pokemon might not exist or there was a database error.",
                color=nextcord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @team_add.on_autocomplete("pokemon")
    async def team_add_pokemon_autocomplete(self, interaction: nextcord.Interaction, current: str):
        """Autocomplete callback for Pokemon parameter in team_add"""
        return await self.pokemon_autocomplete(interaction, current)
    
    @pokemon_command.subcommand(name="team-remove", description="Remove a Pokemon from your team")
    async def team_remove(self, interaction: nextcord.Interaction,
                         team_id: int,
                         slot: int = nextcord.SlashOption(description="Team slot to remove (1-6)", min_value=1, max_value=6)):
        """Remove a Pokemon from a team slot"""
        await interaction.response.defer()
        
        # Verify team ownership
        team_data = await self.get_team_details(team_id, interaction.user.id)
        if not team_data:
            embed = nextcord.Embed(
                title="❌ Team Not Found",
                description="Team not found or you don't have permission to edit it.",
                color=nextcord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Check if slot has a Pokemon
        member_in_slot = None
        for member in team_data['members']:
            if member['slot_number'] == slot:
                member_in_slot = member
                break
        
        if not member_in_slot:
            embed = nextcord.Embed(
                title="❌ Empty Slot",
                description=f"Slot #{slot} is already empty.",
                color=nextcord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Remove Pokemon from team
        success = await self.remove_pokemon_from_team(team_id, slot)
        
        if success:
            pokemon_data = await self.get_cached_pokemon_data(member_in_slot['pokemon_id'])
            display_name = member_in_slot['nickname'] or (pokemon_data['name'].title() if pokemon_data else "Unknown Pokemon")
            
            embed = nextcord.Embed(
                title="✅ Pokemon Removed",
                description=f"Successfully removed **{display_name}** from slot #{slot} of team **{team_data['team_name']}**",
                color=nextcord.Color.green()
            )
            await interaction.followup.send(embed=embed)
        else:
            embed = nextcord.Embed(
                title="❌ Failed to Remove Pokemon",
                description="Could not remove Pokemon from team. There was a database error.",
                color=nextcord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @pokemon_command.subcommand(name="team-delete", description="Delete one of your teams")
    async def team_delete(self, interaction: nextcord.Interaction, team_id: int):
        """Delete a team"""
        await interaction.response.defer()
        
        # Get team data to show confirmation
        team_data = await self.get_team_details(team_id, interaction.user.id)
        if not team_data:
            embed = nextcord.Embed(
                title="❌ Team Not Found",
                description="Team not found or you don't have permission to delete it.",
                color=nextcord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Create confirmation view
        view = TeamDeleteConfirmView(self, team_id, interaction.user.id, team_data['team_name'])
        
        embed = nextcord.Embed(
            title="⚠️ Confirm Team Deletion",
            description=f"Are you sure you want to delete team **{team_data['team_name']}**?\n\n"
                       f"This team has {len(team_data['members'])} Pokemon and cannot be recovered after deletion.",
            color=nextcord.Color.orange()
        )
        
        await interaction.followup.send(embed=embed, view=view)
    
    @pokemon_command.subcommand(name="search", description="Search for Pokemon by name")
    async def pokemon_search(self, interaction: nextcord.Interaction, 
                            pokemon_name: str = nextcord.SlashOption(description="Pokemon name", autocomplete=True),
                            generation: int = nextcord.SlashOption(description="Filter to specific generation", 
                                                                 required=False, min_value=1, max_value=9)):
        """Search for Pokemon by name"""
        await interaction.response.defer()
        
        search_results = await self.search_pokemon(pokemon_name, generation, limit=10)
        
        if not search_results:
            embed = nextcord.Embed(
                title="❌ No Pokemon Found",
                description=f"No Pokemon found matching '{pokemon_name}'" + 
                           (f" in Generation {generation}" if generation else ""),
                color=nextcord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        embed = nextcord.Embed(
            title=f"🔍 Pokemon Search Results",
            description=f"Found {len(search_results)} Pokemon matching '{pokemon_name}'" +
                       (f" in Generation {generation}" if generation else ""),
            color=nextcord.Color.blue()
        )
        
        for pokemon in search_results[:5]:  # Show top 5 results
            # Get cached data for more details
            pokemon_data = await self.get_cached_pokemon_data(pokemon['id'])
            if pokemon_data:
                field_value = f"**ID:** {pokemon['id']}\n"
                field_value += f"**Generation:** {pokemon_data['generation']}\n"
                field_value += f"**Type:** {pokemon_data['primary_type'].title()}"
                if pokemon_data['secondary_type']:
                    field_value += f"/{pokemon_data['secondary_type'].title()}"
                
                embed.add_field(
                    name=f"#{pokemon['id']} {pokemon['display_name']}",
                    value=field_value,
                    inline=True
                )
        
        if len(search_results) > 5:
            embed.set_footer(text=f"Showing top 5 of {len(search_results)} results")
        
        await interaction.followup.send(embed=embed)
    
    @pokemon_search.on_autocomplete("pokemon_name")
    async def pokemon_search_autocomplete(self, interaction: nextcord.Interaction, current: str):
        """Autocomplete callback for Pokemon name parameter in search"""
        return await self.pokemon_autocomplete(interaction, current)
    
    @pokemon_command.subcommand(name="info", description="Get detailed information about a Pokemon")
    async def pokemon_info(self, interaction: nextcord.Interaction, 
                          pokemon: str = nextcord.SlashOption(description="Pokemon name or ID", autocomplete=True)):
        """Get detailed information about a Pokemon"""
        await interaction.response.defer()
        
        # Try to parse Pokemon ID or search by name
        pokemon_id = None
        if pokemon.isdigit():
            pokemon_id = int(pokemon)
        else:
            # Search for Pokemon by name
            search_results = await self.search_pokemon(pokemon, limit=1)
            if search_results:
                pokemon_id = search_results[0]['id']
        
        if not pokemon_id:
            embed = nextcord.Embed(
                title="❌ Pokemon Not Found",
                description=f"Could not find Pokemon '{pokemon}'. Try using the Pokemon's name or Pokedex number.",
                color=nextcord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        pokemon_data = await self.get_cached_pokemon_data(pokemon_id)
        if not pokemon_data:
            embed = nextcord.Embed(
                title="❌ Pokemon Data Unavailable",
                description=f"Could not retrieve data for Pokemon ID {pokemon_id}.",
                color=nextcord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Create detailed info embed
        embed = nextcord.Embed(
            title=f"#{pokemon_data['pokemon_id']} {pokemon_data['name'].title()}",
            color=nextcord.Color.blue()
        )
        
        if pokemon_data['sprite_url']:
            embed.set_thumbnail(url=pokemon_data['sprite_url'])
        
        # Basic info
        embed.add_field(name="Generation", value=str(pokemon_data['generation']), inline=True)
        
        # Type info
        type_text = pokemon_data['primary_type'].title()
        if pokemon_data['secondary_type']:
            type_text += f"/{pokemon_data['secondary_type'].title()}"
        embed.add_field(name="Type", value=type_text, inline=True)
        
        # Physical stats
        embed.add_field(name="Height", value=f"{pokemon_data['height']/10:.1f} m", inline=True)
        embed.add_field(name="Weight", value=f"{pokemon_data['weight']/10:.1f} kg", inline=True)
        
        # Base stats
        stats_text = f"**HP:** {pokemon_data['hp']}\n"
        stats_text += f"**Attack:** {pokemon_data['attack']}\n"
        stats_text += f"**Defense:** {pokemon_data['defense']}\n"
        stats_text += f"**Sp. Attack:** {pokemon_data['special_attack']}\n"
        stats_text += f"**Sp. Defense:** {pokemon_data['special_defense']}\n"
        stats_text += f"**Speed:** {pokemon_data['speed']}\n"
        
        total_stats = (pokemon_data['hp'] + pokemon_data['attack'] + pokemon_data['defense'] + 
                      pokemon_data['special_attack'] + pokemon_data['special_defense'] + pokemon_data['speed'])
        stats_text += f"**Total:** {total_stats}"
        
        embed.add_field(name="Base Stats", value=stats_text, inline=True)
        
        # Abilities
        if pokemon_data['abilities']:
            abilities_text = ", ".join([ability.replace('-', ' ').title() for ability in pokemon_data['abilities']])
            embed.add_field(name="Abilities", value=abilities_text, inline=True)
        
        await interaction.followup.send(embed=embed)
    
    @pokemon_info.on_autocomplete("pokemon")
    async def pokemon_info_autocomplete(self, interaction: nextcord.Interaction, current: str):
        """Autocomplete callback for Pokemon parameter in info"""
        return await self.pokemon_autocomplete(interaction, current)

    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize Pokemon name cache when bot is ready"""
        if not self.cache_task:
            print("Initializing Pokemon name cache...")
            self.cache_task = asyncio.create_task(self.build_pokemon_name_cache())

    @pokemon_command.subcommand(name="team-add-menu", description="Add a Pokemon to your team using an interactive menu")
    async def team_add_menu(self, interaction: nextcord.Interaction,
                           team_id: int,
                           slot: int = nextcord.SlashOption(description="Team slot (1-6)", min_value=1, max_value=6),
                           search_term: str = nextcord.SlashOption(description="Search for Pokemon (optional)", required=False),
                           generation: int = nextcord.SlashOption(description="Filter by generation", required=False, min_value=1, max_value=9)):
        """Add a Pokemon to a team using interactive dropdown menu"""
        await interaction.response.defer()
        
        # Verify team ownership
        team_data = await self.get_team_details(team_id, interaction.user.id)
        if not team_data:
            embed = nextcord.Embed(
                title="❌ Team Not Found",
                description="Team not found or you don't have permission to edit it.",
                color=nextcord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Check if slot is already occupied
        for member in team_data['members']:
            if member['slot_number'] == slot:
                embed = nextcord.Embed(
                    title="⚠️ Slot Occupied",
                    description=f"Slot #{slot} already has a Pokemon. Use `/pokemon team-remove` first or choose a different slot.",
                    color=nextcord.Color.orange()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
        
        # Search for Pokemon
        search_results = []
        if search_term:
            search_results = await self.search_pokemon(search_term, generation or team_data['generation_filter'], limit=25)
        else:
            # Show popular Pokemon if no search term
            popular_pokemon_ids = [25, 6, 9, 3, 1, 4, 7, 150, 151, 249, 250, 384, 385, 386, 483, 484, 487]  # Pikachu, Charizard, etc.
            for pokemon_id in popular_pokemon_ids:
                pokemon_data = await self.get_cached_pokemon_data(pokemon_id)
                if pokemon_data:
                    # Check generation filter
                    if not generation and not team_data['generation_filter'] or \
                       (generation and pokemon_data['generation'] <= generation) or \
                       (team_data['generation_filter'] and pokemon_data['generation'] <= team_data['generation_filter']):
                        search_results.append({
                            'id': pokemon_id,
                            'display_name': pokemon_data['name'].title(),
                            'generation': pokemon_data['generation'],
                            'primary_type': pokemon_data['primary_type'],
                            'secondary_type': pokemon_data['secondary_type']
                        })
        
        if not search_results:
            embed = nextcord.Embed(
                title="❌ No Pokemon Found",
                description="No Pokemon found matching your criteria. Try a different search term or generation filter.",
                color=nextcord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Create selection embed
        embed = nextcord.Embed(
            title="🔍 Select a Pokemon",
            description=f"Choose a Pokemon to add to slot #{slot} of team **{team_data['team_name']}**\n\n" +
                       (f"**Search:** {search_term}\n" if search_term else "") +
                       (f"**Generation Filter:** {generation}\n" if generation else "") +
                       f"**Found:** {len(search_results)} Pokemon",
            color=nextcord.Color.blue()
        )
        
        # Create dropdown view
        view = PokemonSelectView(
            self, 
            search_results, 
            "add_to_team",
            team_id=team_id,
            slot=slot
        )
        
        await interaction.followup.send(embed=embed, view=view)

    # Admin Command
    # @pkgo.subcommand(name="admin-add", description="Admin-only: Add a friend code for another user.")
    # async def admin_add(self, interaction: nextcord.Interaction, user: nextcord.User, in_game_name: str, friend_code: str):
    #     # Check if the user is an admin
    #     if interaction.user.id not in admin_user_ids:
    #         await interaction.response.send_message(
    #             "You do not have permission to use this command.", ephemeral=True
    #         )
    #         return

    #     # Remove spaces from the input
    #     sanitized_friend_code = friend_code.replace(" ", "")

    #     # Validate that the friend code contains only digits and is exactly 12 characters long
    #     if not sanitized_friend_code.isdigit() or len(sanitized_friend_code) != 12:
    #         await interaction.response.send_message(
    #             "Invalid friend code! Please ensure it contains exactly 12 digits and no letters or special characters.",
    #             ephemeral=True
    #         )
    #         return

    #     # Store the sanitized friend code (without spaces) in the database
    #     discord_id = str(user.id)
    #     self.add_user(discord_id, in_game_name, sanitized_friend_code)

    #     # Format the friend code into 4-number chunks for display
    #     formatted_friend_code = " ".join([sanitized_friend_code[i:i+4] for i in range(0, 12, 4)])

    #     await interaction.response.send_message(
    #         f"Admin {interaction.user.mention} added {user.mention} with in-game name {in_game_name} and friend code `{formatted_friend_code}`"
    #     )
# --- UI Views for Team Management ---

class PokemonSelectView(nextcord.ui.View):
    """Interactive Pokemon selection dropdown"""
    
    def __init__(self, cog, pokemon_list: List[Dict], callback_action: str, **callback_data):
        super().__init__(timeout=300)
        self.cog = cog
        self.callback_action = callback_action
        self.callback_data = callback_data
        
        # Create select menu with Pokemon options
        options = []
        for pokemon in pokemon_list[:25]:  # Discord limit is 25 options
            # Format the label with Pokemon name and ID
            label = f"#{pokemon['id']} {pokemon['display_name']}"
            if len(label) > 100:  # Discord label limit
                label = label[:97] + "..."
            
            # Add generation info to description if available
            description = f"Generation {pokemon.get('generation', '?')}"
            if pokemon.get('primary_type'):
                description += f" • {pokemon['primary_type'].title()}"
                if pokemon.get('secondary_type'):
                    description += f"/{pokemon['secondary_type'].title()}"
            
            options.append(nextcord.SelectOption(
                label=label,
                value=str(pokemon['id']),
                description=description[:100]  # Discord description limit
            ))
        
        if options:
            self.add_item(PokemonSelect(options, self.handle_selection))
    
    async def handle_selection(self, interaction: nextcord.Interaction, pokemon_id: str):
        """Handle Pokemon selection"""
        if self.callback_action == "add_to_team":
            # Extract team data
            team_id = self.callback_data['team_id']
            slot = self.callback_data['slot']
            user_id = interaction.user.id
            
            # Add Pokemon to team (simplified version)
            success = await self.cog.add_pokemon_to_team(
                team_id, user_id, slot, int(pokemon_id)
            )
            
            if success:
                # Get Pokemon data for confirmation
                pokemon_data = await self.cog.get_cached_pokemon_data(int(pokemon_id))
                embed = nextcord.Embed(
                    title="✅ Pokemon Added!",
                    description=f"Successfully added **{pokemon_data['name'].title()}** to your team!",
                    color=nextcord.Color.green()
                )
                if pokemon_data['sprite_url']:
                    embed.set_thumbnail(url=pokemon_data['sprite_url'])
            else:
                embed = nextcord.Embed(
                    title="❌ Failed to Add Pokemon",
                    description="Could not add Pokemon to team.",
                    color=nextcord.Color.red()
                )
            
            await interaction.response.edit_message(embed=embed, view=None)
        
        # Add more callback actions here as needed

class PokemonSelect(nextcord.ui.Select):
    """Pokemon selection dropdown"""
    
    def __init__(self, options: List[nextcord.SelectOption], callback_func):
        super().__init__(
            placeholder="Choose a Pokemon...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.callback_func = callback_func
    
    async def callback(self, interaction: nextcord.Interaction):
        await self.callback_func(interaction, self.values[0])

class TeamDeleteConfirmView(nextcord.ui.View):
    def __init__(self, cog, team_id: int, user_id: int, team_name: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.team_id = team_id
        self.user_id = user_id
        self.team_name = team_name
    
    @nextcord.ui.button(label="✅ Confirm Delete", style=nextcord.ButtonStyle.danger)
    async def confirm_delete(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You can only delete your own teams.", ephemeral=True)
            return
        
        success = await self.cog.delete_team(self.team_id, self.user_id)
        
        if success:
            embed = nextcord.Embed(
                title="✅ Team Deleted",
                description=f"Team **{self.team_name}** has been permanently deleted.",
                color=nextcord.Color.green()
            )
        else:
            embed = nextcord.Embed(
                title="❌ Deletion Failed",
                description="Failed to delete team. It may have already been deleted.",
                color=nextcord.Color.red()
            )
        
        # Disable all buttons
        for item in self.children:
            item.disabled = True
        
        await interaction.response.edit_message(embed=embed, view=self)
    
    @nextcord.ui.button(label="❌ Cancel", style=nextcord.ButtonStyle.secondary)
    async def cancel_delete(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You can only cancel your own deletion requests.", ephemeral=True)
            return
        
        embed = nextcord.Embed(
            title="❌ Deletion Cancelled",
            description=f"Team **{self.team_name}** was not deleted.",
            color=nextcord.Color.blue()
        )
        
        # Disable all buttons
        for item in self.children:
            item.disabled = True
        
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def on_timeout(self):
        embed = nextcord.Embed(
            title="⏰ Timeout",
            description="Team deletion cancelled due to timeout.",
            color=nextcord.Color.grey()
        )
        
        # Disable all buttons
        for item in self.children:
            item.disabled = True
        
        # Note: This will only work if the original interaction is still valid
        try:
            await self.message.edit(embed=embed, view=self)
        except:
            pass

def setup(bot):
    bot.add_cog(Pokemon(bot))
    print("PokemonCog has been added to the bot.")