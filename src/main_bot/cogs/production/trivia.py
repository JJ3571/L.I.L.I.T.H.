import nextcord
from nextcord.ext import commands
import aiohttp
import asyncio
import random
import html
import time
from typing import Optional, Dict, List
from main_bot.boot_log import boot_print
from main_bot.cog_log_mixin import CogLogMixin

_TR = "trivia"

# Get the GUILD_ID from config
try:
    from main_bot.server_configs.config import GUILD_ID
except ImportError:
    GUILD_ID = None

class TriviaView(nextcord.ui.View):
    def __init__(self, question_data: dict, correct_answer: str, user_id: int, trivia_cog):
        super().__init__(timeout=30.0)  # 30 seconds to answer
        self.question_data = question_data
        self.correct_answer = correct_answer
        self.user_id = user_id
        self.trivia_cog = trivia_cog
        self.answered = False
        
        # Create buttons for all answers (shuffled)
        all_answers = [correct_answer] + question_data.get('incorrect_answers', [])
        random.shuffle(all_answers)
        
        for i, answer in enumerate(all_answers):
            button = nextcord.ui.Button(
                label=html.unescape(answer)[:80],  # Limit length and decode HTML
                style=nextcord.ButtonStyle.primary,
                custom_id=f"answer_{i}"
            )
            button.callback = self.answer_callback
            self.add_item(button)
    
    async def answer_callback(self, interaction: nextcord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your trivia question!", ephemeral=True)
            return
        
        if self.answered:
            await interaction.response.send_message("❌ You already answered this question!", ephemeral=True)
            return
        
        self.answered = True
        selected_answer = html.unescape(interaction.data['custom_id'])
        button_clicked = None
        
        # Find which button was clicked
        for item in self.children:
            if item.custom_id == interaction.data['custom_id']:
                button_clicked = item
                break
        
        selected_text = button_clicked.label if button_clicked else ""
        correct_text = html.unescape(self.correct_answer)
        
        # Disable all buttons and update colors
        for item in self.children:
            item.disabled = True
            if item.label == correct_text:
                item.style = nextcord.ButtonStyle.success  # Green for correct
            elif item == button_clicked and item.label != correct_text:
                item.style = nextcord.ButtonStyle.danger   # Red for wrong selection
        
        # Check if answer is correct
        is_correct = selected_text == correct_text
        
        # Update embed with result
        embed = interaction.message.embeds[0]
        if is_correct:
            embed.color = nextcord.Color.green()
            embed.add_field(name="✅ Correct!", value=f"Great job, {interaction.user.display_name}!", inline=False)
            # Award points
            await self.trivia_cog.add_trivia_points(interaction.user.id, self.get_points_for_difficulty())
        else:
            embed.color = nextcord.Color.red()
            embed.add_field(
                name="❌ Incorrect!", 
                value=f"The correct answer was: **{correct_text}**", 
                inline=False
            )
        
        await interaction.response.edit_message(embed=embed, view=self)
        
        # Stop the view
        self.stop()
    
    def get_points_for_difficulty(self) -> int:
        difficulty = self.question_data.get('difficulty', 'medium')
        points_map = {'easy': 10, 'medium': 20, 'hard': 30}
        return points_map.get(difficulty, 20)
    
    async def on_timeout(self):
        # Disable all buttons when timeout occurs
        for item in self.children:
            item.disabled = True
            if item.label == html.unescape(self.correct_answer):
                item.style = nextcord.ButtonStyle.success
        
        # The message should still be available to edit
        try:
            embed = nextcord.Embed(
                title="⏰ Time's Up!",
                description=f"The correct answer was: **{html.unescape(self.correct_answer)}**",
                color=nextcord.Color.orange()
            )
            # Note: We can't edit the message here directly since we don't have the interaction
            # The timeout will be handled by the command that created this view
        except:
            pass

class Trivia(commands.Cog, CogLogMixin):
    def __init__(self, bot):
        self.bot = bot
        self.session = None
        
        # OpenTDB API categories
        self.categories = {
            9: "General Knowledge",
            10: "Entertainment: Books",
            11: "Entertainment: Film", 
            12: "Entertainment: Music",
            13: "Entertainment: Musicals & Theatres",
            14: "Entertainment: Television",
            15: "Entertainment: Video Games",
            16: "Entertainment: Board Games",
            17: "Science & Nature",
            18: "Science: Computers",
            19: "Science: Mathematics",
            20: "Mythology",
            21: "Sports",
            22: "Geography",
            23: "History",
            24: "Politics",
            25: "Art",
            26: "Celebrities",
            27: "Animals",
            28: "Vehicles",
            29: "Entertainment: Comics",
            30: "Science: Gadgets",
            31: "Entertainment: Japanese Anime & Manga",
            32: "Entertainment: Cartoon & Animations"
        }
    
    async def cog_load(self):
        """Initialize database and HTTP session when cog loads"""
        await self.create_tables()
        try:
            self.session = aiohttp.ClientSession()
            self.cog_print("Trivia cog: HTTP session initialized")
        except Exception as e:
            self.cog_print(f"Trivia cog: Failed to initialize HTTP session: {e}")
            self.session = None
    
    def cog_unload(self):
        """Clean up when cog unloads"""
        if self.session and not self.session.closed:
            asyncio.create_task(self.session.close())
            self.cog_print("Trivia cog: HTTP session closed")
    
    async def create_tables(self):
        return

    async def ensure_tables_exist(self):
        return
    
    async def get_trivia_question(self, difficulty: str = "medium", category: Optional[int] = None) -> Optional[dict]:
        """Fetch trivia question from OpenTDB API"""
        base_url = "https://opentdb.com/api.php"
        params = {
            "amount": 1,
            "type": "multiple",  # Multiple choice questions
            "difficulty": difficulty
        }
        
        if category:
            params["category"] = category
        
        # Ensure session exists or create temporary one
        session_to_use = self.session
        use_temp_session = False
        
        if not session_to_use or session_to_use.closed:
            try:
                self.session = aiohttp.ClientSession()
                session_to_use = self.session
                self.cog_print("Trivia: Created new HTTP session")
            except:
                # Use temporary session as last resort
                session_to_use = aiohttp.ClientSession()
                use_temp_session = True
                self.cog_print("Trivia: Using temporary HTTP session")
        
        try:
            async with session_to_use.get(base_url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data["response_code"] == 0 and data["results"]:
                        return data["results"][0]
                    else:
                        self.cog_print(f"OpenTDB API returned response code: {data.get('response_code', 'unknown')}")
                        return None
                else:
                    self.cog_print(f"HTTP error: {response.status}")
                    return None
        except Exception as e:
            self.cog_print(f"Error fetching trivia question: {e}")
            return None
        finally:
            # Close temporary session if used
            if use_temp_session and session_to_use and not session_to_use.closed:
                await session_to_use.close()
    
    async def add_trivia_points(self, user_id: int, points: int):
        """Add points to user's trivia score"""
        await self.ensure_tables_exist()
        async with self.bot.pg_pool.acquire() as db:
            await db.execute(
                f'''
                INSERT INTO "{_TR}".trivia_scores AS ts (user_id, total_points, questions_answered, questions_correct, last_played)
                VALUES ($1, $2, 1, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE SET
                    total_points = ts.total_points + EXCLUDED.total_points,
                    questions_answered = ts.questions_answered + 1,
                    questions_correct = ts.questions_correct + 1,
                    last_played = CURRENT_TIMESTAMP
                ''',
                user_id,
                points,
            )

    async def record_wrong_answer(self, user_id: int):
        """Record a wrong answer (no points, but increment questions_answered)"""
        await self.ensure_tables_exist()
        async with self.bot.pg_pool.acquire() as db:
            await db.execute(
                f'''
                INSERT INTO "{_TR}".trivia_scores AS ts (user_id, total_points, questions_answered, questions_correct, last_played)
                VALUES ($1, 0, 1, 0, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE SET
                    total_points = ts.total_points,
                    questions_answered = ts.questions_answered + 1,
                    questions_correct = ts.questions_correct,
                    last_played = CURRENT_TIMESTAMP
                ''',
                user_id,
            )

    async def get_user_stats(self, user_id: int) -> Optional[dict]:
        """Get trivia statistics for a user"""
        await self.ensure_tables_exist()
        async with self.bot.pg_pool.acquire() as db:
            row = await db.fetchrow(
                f'''
                SELECT total_points, questions_answered, questions_correct FROM "{_TR}".trivia_scores WHERE user_id = $1
                ''',
                user_id,
            )
            if row:
                total_points = row["total_points"]
                questions_answered = row["questions_answered"]
                questions_correct = row["questions_correct"]
                accuracy = (questions_correct / questions_answered * 100) if questions_answered > 0 else 0
                return {
                    "total_points": total_points,
                    "questions_answered": questions_answered,
                    "questions_correct": questions_correct,
                    "accuracy": accuracy,
                }
            return None

    async def get_trivia_leaderboard(self, limit: int = 10) -> List[tuple]:
        """Get top trivia players"""
        await self.ensure_tables_exist()
        async with self.bot.pg_pool.acquire() as db:
            rows = await db.fetch(
                f'''
                SELECT user_id, total_points, questions_correct, questions_answered FROM "{_TR}".trivia_scores
                ORDER BY total_points DESC LIMIT $1
                ''',
                limit,
            )
            return [tuple(r) for r in rows]
    
    @nextcord.slash_command(name="trivia", description="Play trivia questions!", guild_ids=[GUILD_ID] if GUILD_ID else None)
    async def trivia_group(self, interaction: nextcord.Interaction):
        pass
    
    @trivia_group.subcommand(name="play", description="Play a trivia question")
    async def trivia_play(
        self, 
        interaction: nextcord.Interaction,
        difficulty: str = nextcord.SlashOption(
            name="difficulty",
            description="Choose difficulty level",
            choices=["easy", "medium", "hard"],
            default="medium"
        ),
        category: str = nextcord.SlashOption(
            name="category", 
            description="Choose a category",
            choices=[
                "General Knowledge", "Books", "Film", "Music", "TV", "Video Games",
                "Science & Nature", "Computers", "Mathematics", "Mythology", 
                "Sports", "Geography", "History", "Art", "Animals"
            ],
            required=False
        )
    ):
        """Play a trivia question"""
        await interaction.response.defer()
        
        # Map category name to ID
        category_id = None
        if category:
            category_map = {
                "General Knowledge": 9, "Books": 10, "Film": 11, "Music": 12,
                "TV": 14, "Video Games": 15, "Science & Nature": 17, 
                "Computers": 18, "Mathematics": 19, "Mythology": 20,
                "Sports": 21, "Geography": 22, "History": 23, "Art": 25, "Animals": 27
            }
            category_id = category_map.get(category)
        
        # Get question from API
        question_data = await self.get_trivia_question(difficulty, category_id)
        
        if not question_data:
            embed = nextcord.Embed(
                title="❌ Error",
                description="Sorry, I couldn't fetch a trivia question right now. Please try again!",
                color=nextcord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Create embed with question
        embed = nextcord.Embed(
            title="🧠 Trivia Time!",
            description=html.unescape(question_data['question']),
            color=nextcord.Color.blue()
        )
        
        difficulty_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}
        embed.add_field(
            name="Category", 
            value=html.unescape(question_data['category']), 
            inline=True
        )
        embed.add_field(
            name="Difficulty", 
            value=f"{difficulty_emoji.get(difficulty, '🟡')} {difficulty.title()}", 
            inline=True
        )
        embed.add_field(
            name="Points", 
            value=f"{'🟢10' if difficulty == 'easy' else '🟡20' if difficulty == 'medium' else '🔴30'}", 
            inline=True
        )
        
        embed.set_footer(text="You have 30 seconds to answer!")
        
        # Create view with answer buttons
        view = TriviaView(question_data, question_data['correct_answer'], interaction.user.id, self)
        
        await interaction.followup.send(embed=embed, view=view)
        
        # Wait for the view to finish
        await view.wait()
        
        # If timeout occurred, record as wrong answer
        if view.answered:
            # Points already recorded in the button callback
            pass
        else:
            await self.record_wrong_answer(interaction.user.id)
    
    @trivia_group.subcommand(name="stats", description="View your trivia statistics")
    async def trivia_stats(self, interaction: nextcord.Interaction):
        """Show user's trivia statistics"""
        try:
            stats = await self.get_user_stats(interaction.user.id)
        except Exception as e:
            self.cog_print(f"Error getting user stats: {e}")
            embed = nextcord.Embed(
                title="❌ Error",
                description="Sorry, I couldn't load your statistics right now. Please try again!",
                color=nextcord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        if not stats:
            embed = nextcord.Embed(
                title="📊 Your Trivia Stats",
                description="You haven't played any trivia yet! Use `/trivia play` to get started.",
                color=nextcord.Color.blue()
            )
        else:
            embed = nextcord.Embed(
                title=f"📊 {interaction.user.display_name}'s Trivia Stats",
                color=nextcord.Color.green()
            )
            embed.add_field(name="🏆 Total Points", value=f"{stats['total_points']:,}", inline=True)
            embed.add_field(name="❓ Questions Answered", value=f"{stats['questions_answered']:,}", inline=True)
            embed.add_field(name="✅ Correct Answers", value=f"{stats['questions_correct']:,}", inline=True)
            embed.add_field(name="🎯 Accuracy", value=f"{stats['accuracy']:.1f}%", inline=True)
            
            # Calculate rank
            all_users = await self.get_trivia_leaderboard(1000)  # Get many users to find rank
            user_rank = next((i + 1 for i, (user_id, _, _, _) in enumerate(all_users) if user_id == interaction.user.id), "Unranked")
            embed.add_field(name="🏅 Rank", value=f"#{user_rank}", inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @trivia_group.subcommand(name="leaderboard", description="View the trivia leaderboard")
    async def trivia_leaderboard(self, interaction: nextcord.Interaction):
        """Show trivia leaderboard"""
        try:
            leaderboard = await self.get_trivia_leaderboard(10)
        except Exception as e:
            self.cog_print(f"Error getting leaderboard: {e}")
            embed = nextcord.Embed(
                title="❌ Error",
                description="Sorry, I couldn't load the leaderboard right now. Please try again!",
                color=nextcord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        if not leaderboard:
            embed = nextcord.Embed(
                title="🏆 Trivia Leaderboard",
                description="No one has played trivia yet! Be the first with `/trivia play`",
                color=nextcord.Color.blue()
            )
        else:
            embed = nextcord.Embed(
                title="🏆 Trivia Leaderboard",
                description="Top trivia masters:",
                color=nextcord.Color.gold()
            )
            
            medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7  # Gold, silver, bronze, then generic medals
            
            for i, (user_id, total_points, questions_correct, questions_answered) in enumerate(leaderboard):
                user = self.bot.get_user(user_id)
                username = user.display_name if user else f"User {user_id}"
                accuracy = (questions_correct / questions_answered * 100) if questions_answered > 0 else 0
                
                embed.add_field(
                    name=f"{medals[i]} #{i+1} {username}",
                    value=f"**{total_points:,}** points • {accuracy:.1f}% accuracy • {questions_answered} questions",
                    inline=False
                )
        
        await interaction.response.send_message(embed=embed)

def setup(bot):
    bot.add_cog(Trivia(bot))
    boot_print("TriviaCog has been added to the bot.")