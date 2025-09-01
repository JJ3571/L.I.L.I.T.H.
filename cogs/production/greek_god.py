import nextcord
from nextcord.ext import commands
from nextcord import Interaction, ButtonStyle, Embed, Color
from nextcord.ui import View, Button
import aiosqlite
import logging
from typing import Optional, Dict, Any, List

from server_configs.config import GUILD_ID
from server_configs.database_config import DATABASE_PATHS

DB_PATH = DATABASE_PATHS["greek_gods"]

# --- Logging Setup ---
logger = logging.getLogger(__name__)

# --- God Data ---
# Storing the descriptions and image links for each god.
GOD_DATA = {
    "Zeus": {
        "description": "King of the gods, you rule with thunderous authority and unshakable confidence. A natural leader, you're bold, decisive, and thrive on power. Your charisma draws followers, but your temper sparks lightning when crossed. You take charge effortlessly and revel in the spotlight.",
        "color": Color.gold(),
        "image_url": "https://media.discordapp.net/attachments/1385279602141958164/1385279683116929216/zeus.png?ex=68557dbd&is=68542c3d&hm=7863f4140dd3cecc93b2ee81913161700541693364ae861d37d2946f828e3393&=&format=webp&quality=lossless&width=1216&height=1216"
    },
    "Hera": {
        "description": "Queen of the gods, you are a fierce guardian of marriage and family, radiating regal strength. Loyal to a fault, you are unwavering in your commitments—yet your wrath is legendary when betrayed. You prize fidelity and protect your inner circle fiercely.",
        "color": Color.dark_red(),
        "image_url": "https://media.discordapp.net/attachments/1385279602141958164/1385279682370474064/hera.png?ex=68557dbd&is=68542c3d&hm=a9406874b8802cd5d1347cc471f08397466d060cb63745dcf81bf1a1db09fd42&=&format=webp&quality=lossless&width=1216&height=1216"
    },
    "Poseidon": {
        "description": "Lord of the seas, you are a tempestuous force—wild, unpredictable, and fiercely independent. Your moods shift like the tides, calm one moment, raging the next. You're drawn to adventure, crave untamed spaces, and let your emotions run deep.",
        "color": Color.blue(),
        "image_url": "https://media.discordapp.net/attachments/1385279602141958164/1385279681573687337/poseidon.png?ex=68557dbd&is=68542c3d&hm=bfff63415fcd71cd147a4213e736fb73291882d63aa0e8be6f7b68003d56d16f&=&format=webp&quality=lossless&width=1216&height=1216"
    },
    "Athena": {
        "description": "Goddess of wisdom and war, you blend sharp intellect with cool-headed strategy. The ultimate planner—logical, composed, and always three steps ahead. You solve problems with precision and outsmart rather than outshout.",
        "color": Color.light_grey(),
        "image_url": "https://media.discordapp.net/attachments/1385279602141958164/1385279687877595280/athena.png?ex=68557dbe&is=68542c3e&hm=b02fd7345a750de2d02b5ec7167cb6a6a7b1f51cc7e5799611b7ab3d8c39f05f&=&format=webp&quality=lossless&width=1216&height=1216"
    },
    "Apollo": {
        "description": "God of prophecy, music, and the sun, you shine with radiant charm and rational grace. A poet and healer, you are inspired by beauty and truth. You seek meaning in patterns, and your artistry uplifts souls.",
        "color": Color.orange(),
        "image_url": "https://media.discordapp.net/attachments/1385279602141958164/1385279687013564518/apollo.png?ex=68557dbe&is=68542c3e&hm=6a8cd31623f727d7396ba8c6602cf6fcc453995713a8c5e40b2a584481f9c276&=&format=webp&quality=lossless&width=1216&height=1216"
    },
    "Artemis": {
        "description": "Goddess of the hunt and wilderness, you roam free with fierce independence. A protector of nature, you are untamed, self-reliant, and shun crowds for solitude. You guard your freedom and stand firm on your own.",
        "color": Color.green(),
        "image_url": "https://media.discordapp.net/attachments/1385279602141958164/1385279686183092306/artemis.png?ex=68557dbe&is=68542c3e&hm=3c761113ae551559e29d56526710977c360eb62ca459fc886f40dd9fdc1e76b8&=&format=webp&quality=lossless&width=1216&height=1216"
    },
    "Ares": {
        "description": "God of war, you are raw aggression and unbridled passion. You charge into battle with reckless abandon, thriving on conflict and chaos. Hot-tempered and fearless, you are driven by instinct over strategy.",
        "color": Color.red(),
        "image_url": "https://media.discordapp.net/attachments/1385279602141958164/1385279685511876739/ares.png?ex=68557dbe&is=68542c3e&hm=89d4b2245d4a5b7eab364a0aa9a1b38a2ba7c32671bfea24a601be8a8ae4f41d&=&format=webp&quality=lossless&width=1216&height=1216"
    },
    "Aphrodite": {
        "description": "Goddess of love and beauty, you enchant with effortless allure. Playful, magnetic, and irresistibly charming, you weave romance and desire wherever you go. You revel in flirtation and see life through a rosy lens.",
        "color": Color.magenta(),
        "image_url": "https://media.discordapp.net/attachments/1385279602141958164/1385279684698312806/aphrodite.png?ex=68557dbe&is=68542c3e&hm=4c5651259dd046c08e2f41baf7e4533a44a23f85caed01fcdd1b1f5a5c68380a&=&format=webp&quality=lossless&width=1216&height=1216"
    },
    "Hephaestus": {
        "description": "God of the forge, you are a quiet craftsman of unmatched skill. Steady and reserved, you pour your soul into creating—tools, art, or solutions. You value hard work over praise and find peace in solitude.",
        "color": Color.dark_grey(),
        "image_url": "https://media.discordapp.net/attachments/1385279602141958164/1385279683922235533/hephaestus.png?ex=68557dbd&is=68542c3d&hm=1129b4c43f92a4c54957b5faf51c958b65f6c6e35623bf9af7b1c8e94b102bbb&=&format=webp&quality=lossless&width=1216&height=1216"
    },
    "Hermes": {
        "description": "God of trickery and travel, you dance through life with sly wit and restless energy. A messenger and thief, you're quick, adaptable, and always one step ahead. You outsmart challenges and crave adventure.",
        "color": Color.teal(),
        "image_url": "https://media.discordapp.net/attachments/1385279602141958164/1385280401961910293/hermes.png?ex=68557e69&is=68542ce9&hm=759240592169c5ff237763e9b642daa48565335a75587f23fe5246b7f975da1e&=&format=webp&quality=lossless&width=1216&height=1216"
    },
    "Demeter": {
        "description": "Goddess of the harvest, you nurture life with steadfast warmth. Fiercely devoted, your care runs deep as the earth. Patient and grounded, you find joy in growth and community, prioritizing others' well-being.",
        "color": Color.dark_green(),
        "image_url": "https://media.discordapp.net/attachments/1385279602141958164/1385280400976380014/demeter.png?ex=68557e68&is=68542ce8&hm=150e126e528d836c27d6abafa725cdc91c4018143a2eb674f77b083dbcc937ac&=&format=webp&quality=lossless&width=1216&height=1216"
    },
    "Dionysus": {
        "description": "God of wine and revelry, you are chaos wrapped in joy. Wild, carefree, and rule-breaking, you live for the thrill of the moment—parties, ecstasy, or rebellion. You chase fun and ignite the night.",
        "color": Color.purple(),
        "image_url": "https://media.discordapp.net/attachments/1385279602141958164/1385280403165810828/dionysus.png?ex=68557e69&is=68542ce9&hm=5c510b97bdb0ab98450b16870f3a23394d2cede6a20654b90ba05dc96e4e2f2d&=&format=webp&quality=lossless&width=1216&height=1216"
    },
}

# --- Quiz Questions ---
# Each question has 4 answers, each pointing to a specific god.
QUESTIONS = [
    {
        "question": "When facing a major challenge, you are most likely to:",
        "answers": {
            "Take command and lead the charge.": "Zeus", # 
            "Develop a meticulous, step-by-step plan.": "Athena", 
            "Follow your gut and act on impulse.": "Ares",
            "Find a creative, unconventional solution.": "Hermes",
        }
    },
    {
        "question": "How do you prefer to spend a free day?",
        "answers": {
            "Out in nature, far from civilization.": "Artemis", # 
            "At a lively party or social gathering.": "Dionysus",
            "Working on a personal project or hobby.": "Hephaestus",
            "With your closest family and loved ones.": "Hera",
        }
    },
    {
        "question": "What guides your decisions most?",
        "answers": {
            "Logic and reason.": "Athena", # 
            "Passion and emotion.": "Aphrodite",
            "Duty and responsibility.": "Hera",
            "Freedom and independence.": "Poseidon",
        }
    },
    {
        "question": "You are at your best when you are:",
        "answers": {
            "Creating something beautiful.": "Apollo", # 
            "Defending your beliefs or friends.": "Ares",
            "Exploring new places and ideas.": "Hermes",
            "Caring for and nurturing others.": "Demeter",
        }
    },
    {
        "question": "Which of these flaws do you relate to most?",
        "answers": {
            "A fiery temper.": "Poseidon", # 
            "A tendency to be manipulative.": "Hermes",
            "Being too proud or arrogant.": "Zeus",
            "A vengeful streak.": "Hera",
        }
    },
        {
        "question": "What do you value most in others?",
        "answers": {
            "Intellect and wit.": "Athena",
            "Loyalty and devotion.": "Hera",
            "Artistic talent and grace.": "Apollo", # 
            "Spontaneity and a love for life.": "Dionysus",
        }
    },
]

# --- Database Manager ---
class DatabaseManager:
    """Handles all database operations for the cog."""
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def initialize(self):
        """Create the database table if it doesn't exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS god_results (
                    user_id INTEGER PRIMARY KEY,
                    god_name TEXT NOT NULL
                )
            """)
            await db.commit()
        logger.info("Database initialized for GreekGodTest.")

    async def get_user_result(self, user_id: int) -> Optional[str]:
        """Fetches the stored result for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT god_name FROM god_results WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def save_user_result(self, user_id: int, god_name: str):
        """Saves or updates a user's test result."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO god_results (user_id, god_name) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET god_name = excluded.god_name
            """, (user_id, god_name))
            await db.commit()
        logger.info(f"Saved result for user {user_id}: {god_name}")
        
    async def delete_user_result(self, user_id: int):
        """Deletes a user's test result."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM god_results WHERE user_id = ?", (user_id,))
            await db.commit()
        logger.info(f"Deleted result for user {user_id}")


# --- UI Views ---

class StartTestView(View):
    """View with a button to start the test."""
    def __init__(self, owner_id: int, cog: 'GreekGodTest'):
        super().__init__(timeout=300) # 5 minute timeout
        self.owner_id = owner_id
        self.cog = cog

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This isn't your test to start!", ephemeral=True)
            return False
        return True

    @nextcord.ui.button(label="Begin the Test", style=ButtonStyle.primary)
    async def start_button(self, button: nextcord.ui.Button, interaction: Interaction):
        """Starts the personality test."""
        test_view = GodTestView(owner_id=self.owner_id, cog=self.cog)
        await test_view.send_question(interaction)
        self.stop()

class GodTestView(View):
    """The main view for the personality test questions."""
    def __init__(self, owner_id: int, cog: 'GreekGodTest'):
        super().__init__(timeout=300) # 5 minute timeout per question
        self.owner_id = owner_id
        self.cog = cog
        self.question_index = 0
        self.scores: Dict[str, int] = {god: 0 for god in GOD_DATA.keys()}

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("You can't answer for someone else!", ephemeral=True)
            return False
        return True

    async def send_question(self, interaction: Interaction):
        """Sends the current question to the user by editing the existing message."""
        self.clear_items()
        
        question_data = QUESTIONS[self.question_index]
        embed = Embed(
            title=f"Question {self.question_index + 1}/{len(QUESTIONS)}",
            description=question_data["question"],
            color=Color.blurple()
        )
        embed.set_footer(text=f"Test for {interaction.user.display_name}")

        for answer_text, god_name in question_data["answers"].items():
            button = Button(label=answer_text, style=ButtonStyle.secondary, custom_id=god_name)
            button.callback = self.process_answer
            self.add_item(button)
        
        await interaction.response.edit_message(embed=embed, view=self)

    async def process_answer(self, interaction: Interaction):
        """Processes the user's answer and moves to the next question or shows results."""
        god_name = interaction.data['custom_id']
        self.scores[god_name] += 1
        self.question_index += 1

        if self.question_index < len(QUESTIONS):
            await self.send_question(interaction)
        else:
            await self.show_results(interaction)
            self.stop()

    async def show_results(self, interaction: Interaction):
        """Calculates the final result and displays it."""
        final_god = max(self.scores, key=self.scores.get)
        await self.cog.db_manager.save_user_result(self.owner_id, final_god)
        
        result_view = ResultView(owner_id=self.owner_id, cog=self.cog)
        embed = self.cog.create_god_embed(interaction.user, final_god)

        await interaction.response.edit_message(embed=embed, view=result_view)

class ResultView(View):
    """View displayed with the final result, offering a retake option."""
    def __init__(self, owner_id: int, cog: 'GreekGodTest'):
        super().__init__(timeout=None) # This view doesn't time out
        self.owner_id = owner_id
        self.cog = cog

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This isn't your result!", ephemeral=True)
            return False
        return True

    @nextcord.ui.button(label="Retake Test", style=ButtonStyle.danger)
    async def retake_button(self, button: nextcord.ui.Button, interaction: Interaction):
        """Allows the user to retake the test."""
        await self.cog.db_manager.delete_user_result(self.owner_id)
        
        start_view = StartTestView(owner_id=self.owner_id, cog=self.cog)
        embed = Embed(
            title="Which Greek God Are You?",
            description="Your previous result has been cleared. Press the button below to start a new personality test and discover your divine alter ego!",
            color=Color.dark_gold()
        )
        await interaction.response.edit_message(embed=embed, view=start_view)
        self.stop()


# --- Main Cog Class ---

class GreekGodTest(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_manager = DatabaseManager(DB_PATH)

    async def cog_load(self):
        """Initialize database when the cog is loaded."""
        await self.db_manager.initialize()

    def create_god_embed(self, user: nextcord.Member, god_name: str) -> Embed:
        """Helper function to create the result embed."""
        data = GOD_DATA[god_name]
        embed = Embed(
            title=f"You are {god_name}!",
            description=data["description"],
            color=data["color"]
        )
        embed.set_author(name=f"{user.display_name}'s Divine Personality", icon_url=user.display_avatar.url)
        if data["image_url"]:
            embed.set_thumbnail(url=data["image_url"])
        embed.set_footer(text="You can retake the test at any time.")
        return embed

    @nextcord.slash_command(
        name="divine_personality",
        description="Discover which Greek God you are most like.",
        guild_ids=[GUILD_ID]
    )
    async def divine_personality(self, interaction: Interaction):
        """The main slash command to start the personality test."""
        await interaction.response.defer()
        
        user_id = interaction.user.id
        existing_result = await self.db_manager.get_user_result(user_id)

        if existing_result:
            # User has a result, display it
            embed = self.create_god_embed(interaction.user, existing_result)
            view = ResultView(owner_id=user_id, cog=self)
            await interaction.followup.send(embed=embed, view=view)
        else:
            # User has no result, start the test
            embed = Embed(
                title="Which Greek God Are You?",
                description="Welcome, mortal! Answer a few questions to reveal your divine inner self. Press the button below to begin your journey to Olympus.",
                color=Color.dark_gold()
            )
            view = StartTestView(owner_id=user_id, cog=self)
            await interaction.followup.send(embed=embed, view=view)


# --- Setup Function ---
async def setup(bot):
    """Loads the cog and ensures async setup is complete."""
    cog = GreekGodTest(bot)
    await cog.cog_load()
    bot.add_cog(cog)
    logger.info("GreekGodTest cog has been loaded and database is ready.")
    