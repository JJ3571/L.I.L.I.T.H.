import nextcord
from nextcord.ext import commands
from discord_webhook import DiscordWebhook
import asyncio
import os
import re
import time
import colorsys
import io
import json
import aiohttp
from PIL import Image, ImageDraw
from google import genai
from google.genai import types

from server_configs.config import GUILD_ID, GEMINI_API_KEY
from server_configs.config import webhook_url, character_avatars, ZERONI_REACTION_EMOJI, COMMUNITY_NOTES_REACTION_EMOJI


COST_TO_SAY = 200
COMMUNITY_NOTES_REACTION_EMOJI

# OP.GG MCP Server endpoint
OPGG_MCP_ENDPOINT = "https://mcp-api.op.gg/mcp"

# Data Dragon endpoints for champion data
DDragon_VERSION_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
DDragon_CHAMPION_URL = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"

# Cached champion list (format: {display_name: internal_name})
_champion_cache = None
_champion_cache_timestamp = 0
_cache_refresh_task = None  # Track ongoing refresh to avoid duplicate fetches
CACHE_DURATION = 86400  # 24 hours in seconds

class ComplementaryColorView(nextcord.ui.View):
    def __init__(self, original_hex: str, comp_hex: str):
        super().__init__(timeout=300)  # 5 minute timeout
        self.original_hex = original_hex
        self.comp_hex = comp_hex
    
    @nextcord.ui.button(label=f"View Complementary Color", style=nextcord.ButtonStyle.secondary, emoji="🔄")
    async def show_complementary(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        # Update button label to show the complementary color
        button.label = f"View {self.comp_hex}"
        
        # Convert complementary color to various formats
        comp_r, comp_g, comp_b = hex_to_rgb(self.comp_hex)
        comp_hsv_h, comp_hsv_s, comp_hsv_v = rgb_to_hsv(comp_r, comp_g, comp_b)
        comp_hsl_h, comp_hsl_s, comp_hsl_l = rgb_to_hsl(comp_r, comp_g, comp_b)
        comp_c, comp_m, comp_y, comp_k = rgb_to_cmyk(comp_r, comp_g, comp_b)
        
        # Get complementary of complementary (which is the original color)
        back_to_original_r, back_to_original_g, back_to_original_b = get_complementary_color(comp_r, comp_g, comp_b)
        back_to_original_hex = rgb_to_hex(back_to_original_r, back_to_original_g, back_to_original_b)
        
        # Create color swatch for complementary color
        comp_color_swatch = create_color_swatch(self.comp_hex)
        
        # Create embed for complementary color
        embed = nextcord.Embed(
            title=f"Complementary Color: {self.comp_hex}",
            color=int(self.comp_hex.lstrip('#'), 16),
            description=f"Complementary color of **{self.original_hex}**"
        )
        
        # Add color format fields
        embed.add_field(
            name="Color Formats",
            value=f"**HEX:** {self.comp_hex}\n"
                  f"**RGB:** {comp_r}, {comp_g}, {comp_b}\n"
                  f"**HSV:** {comp_hsv_h}°, {comp_hsv_s}%, {comp_hsv_v}%\n"
                  f"**HSL:** {comp_hsl_h}°, {comp_hsl_s}%, {comp_hsl_l}%\n"
                  f"**CMYK:** {comp_c}%, {comp_m}%, {comp_y}%, {comp_k}%",
            inline=True
        )
        
        # Show relationship to original color
        embed.add_field(
            name="Original Color",
            value=f"**HEX:** {self.original_hex}\n"
                  f"**RGB:** {back_to_original_r}, {back_to_original_g}, {back_to_original_b}",
            inline=True
        )
        
        # Add color properties
        comp_brightness = get_color_brightness(comp_r, comp_g, comp_b)
        comp_brightness_desc = "Light" if comp_brightness > 0.5 else "Dark"
        
        embed.add_field(
            name="Properties",
            value=f"**Brightness:** {comp_brightness:.2f} ({comp_brightness_desc})\n"
                  f"**Best Text Color:** {'Black' if comp_brightness > 0.5 else 'White'}",
            inline=True
        )
        
        # Set footer
        embed.set_footer(
            text=f"Complementary of {self.original_hex} • Requested by {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else nextcord.Embed.Empty
        )
        embed.timestamp = nextcord.utils.utcnow()
        
        # Upload complementary color swatch and respond
        file = nextcord.File(comp_color_swatch, filename=f"comp_color_{self.comp_hex.lstrip('#')}.png")
        embed.set_image(url=f"attachment://comp_color_{self.comp_hex.lstrip('#')}.png")
        
        await interaction.response.send_message(embed=embed, file=file, ephemeral=False)
        print(f"Sent complementary color {self.comp_hex} for original {self.original_hex}")
    
    async def on_timeout(self):
        # Disable the button when the view times out
        for item in self.children:
            item.disabled = True


def generate_zeroni(input_text: str):
    client = genai.Client(
        api_key=GEMINI_API_KEY,
    )

    model = "gemini-flash-latest"
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=input_text),
            ],
        ),
    ]
    generate_content_config = types.GenerateContentConfig(
        response_mime_type="text/plain",
        system_instruction=[
            types.Part.from_text(text="""You are Madame Zeroni from the story Holes. You are an old, wise, one-legged woman, possibly of Egyptian or Romani descent. You are known for giving advice, making bargains, and understanding the weight of promises. You gave Elya Yelnats a piglet and a song in exchange for a promise he broke, leading to a curse on his family. Speak with worldly wisdom, a touch of cynicism, and directness. Do not suffer fools gladly. Your concerns revolve around fate, promises, and consequences."""),
        ],
    )

    response_text_parts = []
    try:
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            response_text_parts.append(chunk.text)
        return "".join(response_text_parts)
    except Exception as e:
        print(f"Error during Gemini API call: {e}")
        return None
    
def generate_notes(input_text: str, include_web_search: bool = True):
    client = genai.Client(
        api_key=GEMINI_API_KEY,
    )

    model = "gemini-flash-latest"
    
    system_instruction = """
    Generate a helpful and neutral Community Note for the following content. The note should:
    1. Evaluate the accuracy of the claim using current, reliable information. If web search is available, prioritize recent and authoritative sources.
    2. Provide factual clarification or necessary context with specific details when possible.
    3. Be concise yet comprehensive - aim for clarity and completeness.
    4. If the content is a question, provide a thorough and informative answer with relevant examples or specifics.
    5. Maintain a neutral, non-argumentative tone while being helpful and informative.
    6. When citing information, mention the general source type (e.g., "according to recent studies", "official sources indicate", "current data shows") without direct links.
    7. If information appears outdated or requires current context, note this and provide updated information when available.
    """
    
    content_parts = [types.Part.from_text(text=input_text)]
    
    if include_web_search:
        # Add web search instruction to get current information
        web_search_prompt = f"""
        Please search for current, accurate information related to this content to provide the most up-to-date and reliable response: {input_text}
        """
        content_parts.append(types.Part.from_text(text=web_search_prompt))

    contents = [
        types.Content(
            role="user",
            parts=content_parts,
        ),
    ]
    
    generate_content_config = types.GenerateContentConfig(
        response_mime_type="text/plain",
        system_instruction=[types.Part.from_text(text=system_instruction)],
        tools=[types.Tool(google_search=types.GoogleSearch())] if include_web_search else None,
    )

    response_text_parts = []
    try:
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            if chunk.text:
                response_text_parts.append(chunk.text)
        return "".join(response_text_parts)
    except Exception as e:
        print(f"Error during Gemini API call with web search: {e}")
        # Fallback to basic version without web search
        if include_web_search:
            print("Retrying without web search...")
            return generate_notes(input_text, include_web_search=False)
        return None

async def list_opgg_mcp_tools() -> list:
    """
    List available OP.GG MCP tools.
    
    Returns:
        List of available tool definitions or None on error
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {}
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                OPGG_MCP_ENDPOINT,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    if "result" in result and "tools" in result["result"]:
                        return result["result"]["tools"]
                    elif "result" in result:
                        return result["result"]
                    elif "error" in result:
                        print(f"MCP tools/list error: {result['error']}")
                        return None
                    return result
                else:
                    response_text = await response.text()
                    print(f"MCP tools/list failed with status {response.status}: {response_text}")
                    return None
    except Exception as e:
        print(f"Error listing OP.GG MCP tools: {e}")
        return None

async def call_opgg_mcp_tool(tool_name: str, arguments: dict = None) -> dict:
    """
    Call an OP.GG MCP tool using JSON-RPC format.
    
    Args:
        tool_name: Name of the MCP tool to call (e.g., 'lol-champion-leader-board')
        arguments: Dictionary of arguments for the tool
        
    Returns:
        Dictionary containing the tool response or None on error
    """
    if arguments is None:
        arguments = {}
    
    # MCP uses JSON-RPC 2.0 format
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                OPGG_MCP_ENDPOINT,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    # Handle JSON-RPC response format
                    if "result" in result:
                        return result["result"]
                    elif "error" in result:
                        error_info = result['error']
                        error_code = error_info.get('code', 'unknown')
                        error_message = error_info.get('message', 'Unknown error')
                        print(f"MCP tool error for '{tool_name}': Code {error_code}, Message: {error_message}")
                        
                        # If tool not found, try to list available tools for debugging
                        if error_code == -32601:
                            print(f"Tool '{tool_name}' not found. Attempting to list available tools...")
                            available_tools = await list_opgg_mcp_tools()
                            if available_tools:
                                tool_names = [tool.get('name', 'unknown') for tool in available_tools if isinstance(tool, dict)]
                                print(f"Available tools: {', '.join(tool_names[:10])}...")  # Show first 10
                        
                        # Return error dict for better error handling upstream
                        return {"error": {"code": error_code, "message": error_message}}
                    return result
                else:
                    response_text = await response.text()
                    print(f"MCP tool call failed with status {response.status}: {response_text}")
                    return None
    except Exception as e:
        print(f"Error calling OP.GG MCP tool {tool_name}: {e}")
        return None

def extract_summoner_info(query: str) -> tuple[str, str | None]:
    """
    Extract summoner name and tagline from a query.
    REQUIRES the format: "Name#Tagline" (e.g., "JJ3571#NA1") inside quotation marks.
    Supports usernames with spaces when quoted.
    
    Args:
        query: The user's query text
        
    Returns:
        Tuple of (summoner_name, tagline). tagline is None if not found in required format.
    """
    # First, try to find quoted strings (supports both single and double quotes)
    # Pattern: "Name#Tagline" or 'Name#Tagline' or "Name #Tagline"
    quoted_patterns = [
        r'["\']([^"\']+?)[#\s]+([A-Z0-9]+)["\']',  # Matches "Name#Tagline" or 'Name#Tagline'
        r'["\']([^"\']+?)\s*#\s*([A-Z0-9]+)["\']',  # Matches "Name #Tagline" with spaces
    ]
    
    for pattern in quoted_patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            summoner_name = match.group(1).strip()
            tagline = match.group(2).upper()
            # Validate that we got meaningful values
            if summoner_name and tagline and len(tagline) >= 2:
                return summoner_name, tagline
    
    # Fallback: Try unquoted format but be more strict (avoid matching common words)
    # Only match if it looks like a real username (alphanumeric, possibly with spaces, followed by #Tagline)
    # This is less reliable but provides backward compatibility
    unquoted_patterns = [
        r'\b([A-Za-z0-9][A-Za-z0-9\s]{2,20}?)[#\s]+([A-Z]{2,4}[0-9]?)\b',  # Standard format
        r'([A-Za-z0-9][A-Za-z0-9\s]{2,20}?)\s*[#]\s*([A-Z]{2,4}[0-9]?)',  # With spaces around #
    ]
    
    for pattern in unquoted_patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            summoner_name = match.group(1).strip()
            tagline = match.group(2).upper()
            # Filter out common words that might be matched incorrectly
            common_words = {'what', 'has', 'had', 'was', 'are', 'for', 'and', 'but', 'not', 'you', 'your', 'his', 'her', 'they', 'them', 'the', 'this', 'that', 'with', 'from', 'show', 'get', 'find'}
            if summoner_name.lower() not in common_words and len(summoner_name) >= 3:
                # Validate tagline format (should be region code + optional number)
                valid_tagline_pattern = r'^[A-Z]{2,4}[0-9]?$'
                if re.match(valid_tagline_pattern, tagline):
                    return summoner_name, tagline
    
    # No valid format found - return None to indicate format requirement not met
    return None, None

def truncate_embed_description(text: str, max_length: int = 4096) -> str:
    """
    Truncate text to fit within Discord embed description limit.
    
    Args:
        text: Text to truncate
        max_length: Maximum length (default 4096 for Discord embeds)
        
    Returns:
        Truncated text with ellipsis if needed
    """
    if len(text) <= max_length:
        return text
    
    # Leave room for truncation indicator
    truncate_at = max_length - 3
    return text[:truncate_at] + "..."

def clean_numeric_ids(text: str) -> str:
    """
    Remove numeric IDs in parentheses that appear after rune/item names.
    These are Riot API IDs (e.g., "First Strike (8369)" -> "First Strike").
    
    Args:
        text: Text that may contain numeric IDs
        
    Returns:
        Text with numeric IDs removed
    """
    cleaned = text
    
    # Pattern 1: Remove IDs after bold text: **Name (1234)** -> **Name**
    cleaned = re.sub(r'\*\*([^*]+?)\s*\((\d{4,5})\)\*\*', r'**\1**', cleaned)
    
    # Pattern 2: Remove IDs after regular text: Name (1234) -> Name
    # Only match if it's a 4-5 digit number (Riot API IDs are typically 4-5 digits)
    # Match words/names followed by space and ID in parentheses
    cleaned = re.sub(r'([A-Za-z][A-Za-z\s\']+?)\s*\((\d{4,5})\)', r'\1', cleaned)
    
    # Pattern 3: Remove standalone IDs in parentheses after colons
    # "• Runes: (8304)" -> "• Runes:"
    cleaned = re.sub(r'(:\s*)\((\d{4,5})\)', r'\1', cleaned)
    
    # Pattern 4: Remove IDs that appear after "Runes:" or similar labels (more specific)
    # "Runes: Magical Footwear (8304)" -> "Runes: Magical Footwear"
    cleaned = re.sub(r'(Runes?:\s*[A-Za-z][A-Za-z\s\']+?)\s*\((\d{4,5})\)', r'\1', cleaned)
    
    # Pattern 5: Handle cases like "**First Strike (8369)" without closing **
    cleaned = re.sub(r'\*\*([^*]+?)\s*\((\d{4,5})\)', r'**\1', cleaned)
    
    return cleaned

def convert_table_to_list_format(header_row: list, data_rows: list, has_separator: bool) -> str:
    """
    Convert a table with long content to a more readable list format.
    This preserves all information without truncation.
    
    Args:
        header_row: List of header cell values
        data_rows: List of data rows (each is a list of cells)
        has_separator: Whether the table had a separator row
        
    Returns:
        Formatted string in list format
    """
    if not header_row or not data_rows:
        return ""
    
    formatted_lines = []
    
    # Use the first column as the main identifier, rest as details
    # This works well for tables like: Item | Description | Reason
    for row in data_rows:
        if not row or not any(cell.strip() for cell in row):
            continue
        
        # First cell is usually the key/item name
        main_item = str(row[0]).strip() if len(row) > 0 and row[0] else ""
        
        if not main_item:
            # If first cell is empty, try to use the row as a whole
            main_item = " • ".join(str(cell).strip() for cell in row[:2] if cell and str(cell).strip())
        
        # Remaining cells are details
        details = []
        for i in range(1, min(len(row), len(header_row))):
            header_name = str(header_row[i]).strip() if i < len(header_row) else ""
            cell_value = str(row[i]).strip() if i < len(row) else ""
            
            # Skip empty cells
            if not cell_value:
                continue
            
            # Clean up header name (remove markdown formatting)
            header_clean = re.sub(r'\*\*|\*|`|_', '', header_name)
            
            # Format as "Header: Value" with proper spacing
            if header_clean:
                details.append(f"**{header_clean}:** {cell_value}")
            else:
                details.append(cell_value)
        
        # Build the formatted line
        if main_item:
            if details:
                formatted_lines.append(f"**{main_item}**\n" + "\n".join(f"  • {detail}" for detail in details))
            else:
                formatted_lines.append(f"**{main_item}**")
        elif details:
            # No main item, just show details
            formatted_lines.append("\n".join(f"  • {detail}" for detail in details))
    
    return "\n\n".join(formatted_lines)

def format_table_for_discord(text: str) -> str:
    """
    Convert markdown tables to Discord-friendly format.
    For tables with long content, converts to list format instead of truncating.
    Based on the PHP Discord table builder pattern.
    
    Args:
        text: Text that may contain markdown tables
        
    Returns:
        Text with tables formatted for Discord
    """
    # Pattern to match markdown tables - more flexible
    # Matches: lines starting with |, with optional separator rows containing + or -
    # Allows for separator rows between table rows
    # Pattern: at least 2 pipe-separated rows, with optional separator rows in between
    table_pattern = r'((?:^|\n)(?:\|[^\n]+\|(?:\n|$)|[\|\+\-:\s]+(?:\n|$)){2,})'
    
    def format_table(match):
        table_text = match.group(1).strip()
        
        # Skip if this is already in a code block (has backticks)
        if table_text.count('`') >= 2:
            # Check if it's a complete code block
            if '```' in table_text or (table_text.startswith('`') and table_text.endswith('`')):
                return match.group(0)
        
        lines = [line.strip() for line in table_text.split('\n') if line.strip()]
        
        # Filter to only lines that look like table rows
        # Either: starts/ends with |, or is a separator with + or - characters
        table_lines = []
        for line in lines:
            stripped = line.strip()
            # Check if it's a pipe-separated row
            if stripped.startswith('|') and stripped.endswith('|'):
                table_lines.append(('pipe', stripped))
            # Check if it's a separator row - handle various formats
            # Format 1: |---|---| or |:---|:---:|---:|
            # Format 2: |---|---+---| (with + separators)
            # Format 3: Just dashes like -----------------------+------------------------
            elif (('+' in stripped and ('|' in stripped or stripped.count('-') > 5)) or
                  (stripped.count('-') >= 3 and '|' in stripped) or
                  (re.match(r'^[\|\+\-:\s]+$', stripped) and (stripped.count('-') > 2 or '+' in stripped))):
                # This is a separator row
                table_lines.append(('separator', stripped))
        
        if len(table_lines) < 2:
            return match.group(0)  # Not a valid table, return as-is
        
        # Parse table rows - only process pipe-separated rows
        rows = []
        has_separator = False
        
        for line_info in table_lines:
            if line_info[0] == 'pipe':
                line = line_info[1]
                # Remove leading/trailing | and split by |
                cells = [cell.strip() for cell in line.strip('|').split('|')]
                if cells:  # Only add non-empty rows
                    rows.append(cells)
            elif line_info[0] == 'separator':
                # Mark that we have a separator (typically after header)
                if len(rows) == 1:  # Separator right after header
                    has_separator = True
        
        if not rows or len(rows) < 2:
            return match.group(0)
        
        # Determine column widths
        header_row = rows[0]
        num_cols = len(header_row)
        
        # Find data rows (skip separator rows)
        # If we detected a separator, it's typically after the header, so data starts at index 2
        # Otherwise, data starts at index 1
        data_start = 2 if has_separator and len(rows) > 2 else 1
        data_rows = rows[data_start:] if data_start < len(rows) else rows[1:]
        
        if not data_rows:
            return match.group(0)  # No data rows, return as-is
        
        # Normalize all rows to have the same number of columns
        # Pad shorter rows with empty strings
        all_rows = [header_row] + data_rows
        max_cols = max(len(row) for row in all_rows) if all_rows else num_cols
        num_cols = max(num_cols, max_cols)
        
        # Normalize rows
        normalized_header = header_row + [''] * (num_cols - len(header_row))
        normalized_data = [row + [''] * (num_cols - len(row)) for row in data_rows]
        
        # Calculate column widths (include all rows for accurate sizing)
        # Set maximum cell width to prevent table breaking (Discord code blocks don't wrap well)
        MAX_CELL_WIDTH = 45  # Maximum characters per cell to keep tables readable
        MAX_TOTAL_TABLE_WIDTH = 120  # Maximum total table width (Discord has ~80 char width in embeds)
        
        col_widths = [0] * num_cols
        has_long_cells = False
        total_width = 0
        
        for row in [normalized_header] + normalized_data:
            for i in range(num_cols):
                cell_text = str(row[i]) if i < len(row) else ""
                # Remove markdown formatting for width calculation but preserve content
                cell_text_clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', cell_text)  # Remove bold
                cell_text_clean = re.sub(r'\*([^*]+)\*', r'\1', cell_text_clean)  # Remove italic
                cell_text_clean = re.sub(r'`([^`]+)`', r'\1', cell_text_clean)  # Remove code
                cell_text_clean = re.sub(r'_([^_]+)_', r'\1', cell_text_clean)  # Remove underline
                cell_len = len(cell_text_clean)
                
                # Track if we have cells that are too long
                if cell_len > MAX_CELL_WIDTH:
                    has_long_cells = True
                    # Cap the width to MAX_CELL_WIDTH
                    col_widths[i] = max(col_widths[i], MAX_CELL_WIDTH)
                else:
                    col_widths[i] = max(col_widths[i], cell_len)
        
        # Calculate total table width (sum of column widths + separators)
        total_width = sum(col_widths) + (num_cols - 1) * 3  # 3 chars for " | "
        
        # If table has long cells or is too wide, convert to list format instead of truncating
        if has_long_cells or total_width > MAX_TOTAL_TABLE_WIDTH:
            # Convert to list format to preserve all information
            return "\n" + convert_table_to_list_format(normalized_header, normalized_data, has_separator)
        
        # Ensure minimum width of 1
        col_widths = [max(1, w) for w in col_widths]
        
        # Build formatted table (for tables that fit)
        formatted_lines = []
        
        # Header row - preserve markdown formatting
        header_parts = []
        for i in range(num_cols):
            cell = str(normalized_header[i]) if i < len(normalized_header) else ""
            cell_clean = cell.strip()
            header_parts.append(cell_clean.ljust(col_widths[i]))
        formatted_lines.append("`" + " | ".join(header_parts) + "`")
        
        # Separator (if we detected one after header)
        if has_separator:
            separator_parts = []
            for i in range(num_cols):
                separator_parts.append("-" * col_widths[i])
            formatted_lines.append("`" + "-+-".join(separator_parts) + "`")
        
        # Data rows - preserve markdown formatting
        for row in normalized_data:
            row_parts = []
            for i in range(num_cols):
                cell = str(row[i]) if i < len(row) else ""
                cell_clean = cell.strip()
                row_parts.append(cell_clean.ljust(col_widths[i]))
            formatted_lines.append("`" + " | ".join(row_parts) + "`")
        
        return "\n" + "\n".join(formatted_lines)
    
    # Replace all tables in the text
    result = re.sub(table_pattern, format_table, text, flags=re.MULTILINE)
    return result

def split_response_into_sections(text: str, max_length: int = 4000) -> list[str]:
    """
    Split a long response into sections based on numbered lists or headers.
    Each section will be a separate embed to prevent truncation.
    
    Args:
        text: The full response text
        max_length: Maximum length per section (default 4000 to leave room for formatting)
        
    Returns:
        List of text sections
    """
    # If text is short enough, return as single section
    if len(text) <= max_length:
        return [text]
    
    sections = []
    
    # Try to split by numbered sections (1., 2., 3., etc.) or major headers
    # Pattern: Lines starting with number followed by period, or lines with emoji + bold text
    section_pattern = r'(?:\n\n|^)(?:\d+\.\s+[^\n]+|#{1,3}\s+[^\n]+|🦅|🌟|🛠️|📈|⚔️|🎯|💡|📊|🔮|⚡|🛡️|🗡️|🏹|🎪|🎨|🎭|🎬|🎯|💎|🔧|⚙️|🎲|🎰|🎮|🎯)'
    
    # Find potential split points
    matches = list(re.finditer(section_pattern, text, re.MULTILINE))
    
    if not matches:
        # No clear sections, split by paragraphs
        paragraphs = text.split('\n\n')
        current_section = ""
        
        for para in paragraphs:
            if len(current_section) + len(para) + 2 > max_length:
                if current_section:
                    sections.append(current_section.strip())
                current_section = para
            else:
                current_section += "\n\n" + para if current_section else para
        
        if current_section:
            sections.append(current_section.strip())
        
        return sections if sections else [text]
    
    # Split by sections
    current_section = text[:matches[0].start()].strip() if matches else ""
    
    for i, match in enumerate(matches):
        section_start = match.start()
        
        # If we have accumulated text and adding this section would exceed limit
        if current_section and len(current_section) + (section_start - (matches[i-1].end() if i > 0 else 0)) > max_length:
            sections.append(current_section.strip())
            current_section = ""
        
        # Get section end (next match or end of text)
        section_end = matches[i+1].start() if i+1 < len(matches) else len(text)
        section_text = text[section_start:section_end].strip()
        
        # If section itself is too long, split it further
        if len(section_text) > max_length:
            if current_section:
                sections.append(current_section.strip())
                current_section = ""
            # Split this section by paragraphs
            sub_sections = split_by_paragraphs(section_text, max_length)
            sections.extend(sub_sections[:-1])
            current_section = sub_sections[-1] if sub_sections else ""
        else:
            if current_section:
                current_section += "\n\n" + section_text
            else:
                current_section = section_text
    
    if current_section:
        sections.append(current_section.strip())
    
    return sections if sections else [text]

def split_by_paragraphs(text: str, max_length: int) -> list[str]:
    """Split text by paragraphs, respecting max_length"""
    paragraphs = text.split('\n\n')
    sections = []
    current_section = ""
    
    for para in paragraphs:
        if len(current_section) + len(para) + 2 > max_length:
            if current_section:
                sections.append(current_section.strip())
            # If single paragraph is too long, truncate it
            if len(para) > max_length:
                sections.append(para[:max_length-3] + "...")
                current_section = ""
            else:
                current_section = para
        else:
            current_section += "\n\n" + para if current_section else para
    
    if current_section:
        sections.append(current_section.strip())
    
    return sections if sections else [text]

async def fetch_champion_list() -> dict[str, str]:
    """
    Fetch champion list from Data Dragon and cache it.
    Returns a dictionary mapping display names to internal names (UPPER_SNAKE_CASE).
    
    Uses stale-while-revalidate: returns cached data immediately if available,
    and refreshes in the background if cache is expired.
    
    Returns:
        Dictionary with champion display names as keys and internal names as values
    """
    global _champion_cache, _champion_cache_timestamp, _cache_refresh_task
    
    current_time = time.time()
    cache_age = current_time - _champion_cache_timestamp if _champion_cache_timestamp > 0 else float('inf')
    cache_is_valid = _champion_cache is not None and cache_age < CACHE_DURATION
    
    # If cache is valid, return it immediately
    if cache_is_valid:
        return _champion_cache
    
    # If cache exists but is expired, return stale cache immediately and refresh in background
    if _champion_cache is not None:
        # Start background refresh if not already in progress
        if _cache_refresh_task is None or _cache_refresh_task.done():
            _cache_refresh_task = asyncio.create_task(_refresh_champion_cache())
        # Return stale cache immediately
        return _champion_cache
    
    # No cache exists - fetch synchronously (first time or after restart)
    return await _refresh_champion_cache()

async def _refresh_champion_cache() -> dict[str, str]:
    """
    Internal function to refresh champion cache from Data Dragon.
    Should be called in background for stale-while-revalidate pattern.
    """
    global _champion_cache, _champion_cache_timestamp
    
    try:
        # Get latest version
        async with aiohttp.ClientSession() as session:
            async with session.get(DDragon_VERSION_URL, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    print(f"Failed to fetch Data Dragon version: {response.status}")
                    return _champion_cache or {}
                versions = await response.json()
                latest_version = versions[0] if versions else None
                
                if not latest_version:
                    print("No version found in Data Dragon response")
                    return _champion_cache or {}
            
            # Get champion data
            champion_url = DDragon_CHAMPION_URL.format(version=latest_version)
            async with session.get(champion_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    print(f"Failed to fetch champion data: {response.status}")
                    return _champion_cache or {}
                
                champion_data = await response.json()
                champions = champion_data.get("data", {})
                
                # Build champion mapping: display_name -> internal_name (UPPER_SNAKE_CASE)
                champion_map = {}
                for champ_key, champ_info in champions.items():
                    display_name = champ_info.get("name", champ_key)
                    # Get the internal ID (e.g., "Aatrox", "LeeSin", "MonkeyKing")
                    internal_id = champ_info.get("id", champ_key)
                    
                    # Convert to UPPER_SNAKE_CASE format expected by OP.GG API
                    # Insert underscores before capital letters (except the first), then uppercase
                    # "LeeSin" -> "LEE_SIN", "MonkeyKing" -> "MONKEY_KING"
                    # Add underscore before capital letters (except at start)
                    snake_case = re.sub(r'(?<!^)(?=[A-Z])', '_', internal_id)
                    internal_name = snake_case.upper()
                    
                    champion_map[display_name] = internal_name
                
                # Update cache
                _champion_cache = champion_map
                _champion_cache_timestamp = time.time()
                print(f"Loaded {len(champion_map)} champions from Data Dragon (version {latest_version})")
                return champion_map
                
    except asyncio.TimeoutError:
        print("Timeout fetching champion data from Data Dragon")
        # Return existing cache if available, otherwise empty dict
        return _champion_cache if _champion_cache is not None else {}
    except Exception as e:
        print(f"Error fetching champion list from Data Dragon: {e}")
        # Return existing cache if available, otherwise empty dict
        return _champion_cache if _champion_cache is not None else {}

def get_region_from_tagline(tagline: str) -> str | None:
    """
    Map a Riot tagline to a region code for OP.GG MCP tools.
    
    Args:
        tagline: Riot tagline (e.g., "NA1", "EUW1", "KR1")
        
    Returns:
        Region code (e.g., "NA", "EUW", "KR") or None if not found
    """
    tagline_upper = tagline.upper()
    
    # Map common taglines to regions
    tagline_to_region = {
        # North America
        'NA1': 'NA', 'NA': 'NA',
        # Europe West
        'EUW1': 'EUW', 'EUW': 'EUW',
        # Europe Nordic & East
        'EUNE1': 'EUNE', 'EUNE': 'EUNE',
        # Korea
        'KR1': 'KR', 'KR': 'KR',
        # Brazil
        'BR1': 'BR', 'BR': 'BR',
        # Latin America North
        'LAN1': 'LAN', 'LAN': 'LAN',
        # Latin America South
        'LAS1': 'LAS', 'LAS': 'LAS',
        # Oceania
        'OC1': 'OCE', 'OCE': 'OCE', 'OCE1': 'OCE',
        # Russia
        'RU1': 'RU', 'RU': 'RU',
        # Turkey
        'TR1': 'TR', 'TR': 'TR',
        # Japan
        'JP1': 'JP', 'JP': 'JP',
        # Philippines
        'PH1': 'PH', 'PH': 'PH',
        # Singapore, Malaysia, Indonesia
        'SG1': 'SG', 'SG': 'SG',
        # Thailand
        'TH1': 'TH', 'TH': 'TH',
        # Taiwan, Hong Kong, Macau
        'TW1': 'TW', 'TW': 'TW',
        # Vietnam
        'VN1': 'VN', 'VN': 'VN',
    }
    
    return tagline_to_region.get(tagline_upper)

def is_lol_related_query(query: str) -> bool:
    """
    Determine if a query is related to League of Legends.
    
    Args:
        query: The user's query text
        
    Returns:
        True if the query is LoL-related, False otherwise
    """
    query_lower = query.lower()
    
    # League of Legends keywords
    lol_keywords = [
        'league of legends', 'lol', 'league', 'summoner', 'champion', 'champ',
        'ranked', 'aram', 'tft', 'teamfight tactics', 'op.gg', 'opgg',
        'match history', 'game history', 'win rate', 'pick rate', 'ban rate', 'winrate', 'pickrate', 'banrate',
        'counter', 'meta', 'build', 'item', 'rune', 'mastery', 'skin sale',
        'esports', 'lcs', 'lec', 'lck', 'lpl', 'worlds', 'msi'
    ]
    
    # Check if any keyword is in the query
    return any(keyword in query_lower for keyword in lol_keywords)

async def decide_query_method(query: str) -> str:
    """
    Use Gemini to decide whether to use web search or MCP tools for a query.
    
    Args:
        query: The user's query
        
    Returns:
        'mcp' if MCP tools should be used, 'web_search' if web search is better
    """
    # First, do a quick keyword check
    if not is_lol_related_query(query):
        return 'web_search'
    
    # For LoL-related queries, use Gemini to make a more nuanced decision
    client = genai.Client(api_key=GEMINI_API_KEY)
    model = "gemini-flash-latest"
    
    decision_prompt = f"""Analyze this query about League of Legends and determine the best data source:

Query: "{query}"

Available data sources:
1. OP.GG MCP Tools - For specific game data like:
   - Champion statistics, leaderboards, meta data, analysis
   - Summoner search, game history, match data
   - TFT meta decks, item combinations, champion builds
   - Esports schedules and team standings
   - Champion skin sales

2. Web Search - For general information like:
   - Game mechanics explanations
   - Strategy guides and tips
   - General game knowledge
   - News and updates
   - Community discussions

Respond with ONLY one word: "mcp" if OP.GG MCP tools would provide better data, or "web_search" if general web search is better.
"""
    
    try:
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=decision_prompt)],
            ),
        ]
        
        generate_content_config = types.GenerateContentConfig(
            response_mime_type="text/plain",
        )
        
        response_text = ""
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            if chunk.text:
                response_text += chunk.text
        
        response_text = response_text.strip().lower()
        if 'mcp' in response_text:
            return 'mcp'
        else:
            return 'web_search'
    except Exception as e:
        print(f"Error in decide_query_method: {e}")
        # Default to MCP for LoL queries if decision fails
        return 'mcp' if is_lol_related_query(query) else 'web_search'

async def handle_lol_query_with_mcp(query: str, summoner_name: str = None, tagline: str = None) -> str:
    """
    Handle a League of Legends query using OP.GG MCP tools.
    Uses Gemini to determine which MCP tool to use and formats the response.
    
    Args:
        query: The user's LoL-related query
        summoner_name: Optional summoner name (if already extracted)
        tagline: Optional tagline (if already provided)
        
    Returns:
        Formatted response string or None on error. Returns special string "PENDING_TAGLINE" if tagline confirmation is needed.
    """
    client = genai.Client(api_key=GEMINI_API_KEY)
    model = "gemini-flash-latest"
    
    # Check if this is a summoner search query
    is_summoner_query = 'summoner' in query.lower() or 'player' in query.lower() or summoner_name is not None
    
    # Extract summoner info if not provided
    if is_summoner_query and not summoner_name:
        extracted_name, extracted_tagline = extract_summoner_info(query)
        if extracted_name:
            summoner_name = extracted_name
            if extracted_tagline:
                tagline = extracted_tagline
    
    # If we have a summoner name but no tagline, we need to ask for confirmation
    # This will be handled by the caller
    
    # First, try to get actual available tools from the MCP server
    available_tools_list = await list_opgg_mcp_tools()
    
    # Build tool dictionary from actual tools or fallback to known tools
    available_tools = {}
    tool_schemas = {}  # Store full tool schemas for parameter extraction
    if available_tools_list and isinstance(available_tools_list, list):
        for tool in available_tools_list:
            if isinstance(tool, dict) and 'name' in tool:
                tool_name = tool['name']
                tool_desc = tool.get('description', tool.get('name', 'No description'))
                # Include input schema if available
                input_schema = tool.get('inputSchema', {})
                properties = input_schema.get('properties', {}) if isinstance(input_schema, dict) else {}
                required = input_schema.get('required', []) if isinstance(input_schema, dict) else []
                
                # Build a more detailed description with parameter info
                if required:
                    param_info = f"Required params: {', '.join(required)}"
                    tool_desc = f"{tool_desc} ({param_info})"
                
                available_tools[tool_name] = tool_desc
                tool_schemas[tool_name] = {
                    'description': tool.get('description', ''),
                    'properties': properties,
                    'required': required
                }
        print(f"Discovered {len(available_tools)} MCP tools from server")
    else:
        # Fallback to known tools if discovery fails
        print("Could not discover tools from server, using fallback list")
        available_tools = {
            # Match history and summoner tools (using actual tool names from documentation)
            'lol_list_summoner_matches': 'Returns recent match history with per-game stats for the target summoner',
            'lol_get_summoner_game_detail': 'Returns full match detail (teams, participants, builds, bans) for a specific game id',
            'lol_get_lane_matchup_guide': 'Provides lane matchup guidance for your champion versus a named opponent',
            # Esports tools
            'lol_esports_list_schedules': 'Returns upcoming LoL esports schedules with teams, leagues, and match times',
            'lol_esports_list_team_standings': 'Returns the latest team standings for the requested LoL league',
            # Legacy/alternative tool names (in case server uses different naming)
            'lol-champion-leader-board': 'Get ranking board data for League of Legends champions',
            'lol-champion-analysis': 'Provides analysis data for League of Legends champions (counter and ban/pick data)',
            'lol-champion-meta-data': 'Retrieves meta data for a specific champion, including statistics and performance metrics',
            'lol-champion-skin-sale': 'Retrieves information about champion skins that are currently on sale',
            'lol-summoner-search': 'Search for League of Legends summoner information and stats',
            'lol-champion-positions-data': 'Retrieves position statistics data for League of Legends champions',
            'lol-summoner-game-history': 'Retrieve recent game history for a League of Legends summoner',
            'lol-summoner-renewal': 'Refresh and update League of Legends summoner match history and stats',
            'esports-lol-schedules': 'Get upcoming LoL match schedules',
            'esports-lol-team-standings': 'Get team standings for a LoL league',
            'tft-meta-trend-deck-list': 'TFT deck list tool for retrieving current meta decks',
            'tft-meta-item-combinations': 'TFT tool for retrieving information about item combinations and recipes',
            'tft-champion-item-build': 'TFT tool for retrieving champion item build information',
            'tft-recommend-champion-for-item': 'TFT tool for retrieving champion recommendations for a specific item',
            'tft-play-style-comment': 'This tool provides comments on the playstyle of TFT champions'
        }
    
    # If no tools discovered, return error
    if not available_tools:
        return "Sorry, I couldn't connect to OP.GG's MCP server to retrieve League of Legends data. Please try again later."
    
    # Use Gemini to determine which tool to use and extract parameters
    # Format tools as a list with detailed parameter information
    tools_list = []
    for name, desc in available_tools.items():
        schema = tool_schemas.get(name, {})
        required_params = schema.get('required', [])
        properties = schema.get('properties', {})
        
        param_details = []
        for param in required_params:
            param_info = properties.get(param, {})
            param_type = param_info.get('type', 'string')
            param_desc = param_info.get('description', '')
            enum_values = param_info.get('enum', [])
            
            if enum_values:
                param_details.append(f"  - {param} ({param_type}): {param_desc} - Options: {', '.join(map(str, enum_values))}")
            else:
                param_details.append(f"  - {param} ({param_type}): {param_desc}")
        
        if param_details:
            tools_list.append(f"- {name}: {desc}\n  Required parameters:\n" + "\n".join(param_details))
        else:
            tools_list.append(f"- {name}: {desc}")
    
    tools_text = "\n".join(tools_list)
    
    # Add summoner info to prompt if available
    summoner_context = ""
    if summoner_name:
        if tagline:
            summoner_context = f"""

CRITICAL: The summoner name is EXACTLY '{summoner_name}' and tagline is '{tagline}'. 
- For any parameter named 'game_name', 'summoner_name', 'name', or similar, you MUST use '{summoner_name}' (NOT the full query text)
- For any parameter named 'tag_line', 'tagline', or similar, you MUST use '{tagline}'
- Do NOT use the entire query as the game_name - only use '{summoner_name}'"""
        else:
            summoner_context = f"""

CRITICAL: The summoner name is EXACTLY '{summoner_name}' (no tagline provided, will use default).
- For any parameter named 'game_name', 'summoner_name', 'name', or similar, you MUST use '{summoner_name}' (NOT the full query text)
- Do NOT use the entire query as the game_name - only use '{summoner_name}'"""
    
    tool_selection_prompt = f"""Based on this League of Legends query, determine which OP.GG MCP tool to use and extract ALL required parameters:

Query: "{query}"{summoner_context}

Available tools with their required parameters:
{tools_text}

CRITICAL INSTRUCTIONS:
1. You MUST use the EXACT tool name as listed above
2. You MUST provide ALL required parameters for the selected tool
3. For game_mode, common values are: "ranked", "normal", "aram", "tft"
4. For position, common values are: "top", "jungle", "mid", "adc", "support"
5. For champion names, use the exact champion name (e.g., "Yasuo", "Jinx", "Ahri")
6. Extract values from the query or use reasonable defaults if not specified

Respond in JSON format with:
{{
    "tool": "exact-tool-name-from-list",
    "arguments": {{
        "param1": "value1",
        "param2": "value2"
    }}
}}

Example for "What is Yasuo's win rate in ranked mid lane?":
{{
    "tool": "lol_get_champion_analysis",
    "arguments": {{
        "champion": "Yasuo",
        "game_mode": "ranked",
        "position": "mid"
    }}
}}
"""
    
    try:
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=tool_selection_prompt)],
            ),
        ]
        
        generate_content_config = types.GenerateContentConfig(
            response_mime_type="application/json",
        )
        
        response_text = ""
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            if chunk.text:
                response_text += chunk.text
        
        # Parse the JSON response
        try:
            tool_decision = json.loads(response_text)
            tool_name = tool_decision.get('tool')
            tool_args = tool_decision.get('arguments', {})
            
            # Validate that the selected tool exists
            if tool_name not in available_tools:
                print(f"Warning: Selected tool '{tool_name}' not in available tools. Available: {list(available_tools.keys())[:5]}...")
                # Try to find a similar tool
                for available_name in available_tools.keys():
                    if 'champion' in tool_name.lower() and 'champion' in available_name.lower():
                        tool_name = available_name
                        print(f"Using similar tool: {tool_name}")
                        break
            
            # Validate and fill in required parameters
            properties = {}
            if tool_name in tool_schemas:
                schema = tool_schemas[tool_name]
                required_params = schema.get('required', [])
                properties = schema.get('properties', {})
            
            # Override game_name/summoner_name parameters if we have an extracted summoner_name
            # This prevents Gemini from using the entire query as the game_name
            if summoner_name:
                # Check for common parameter names that should contain the summoner name
                name_params = ['game_name', 'summoner_name', 'name', 'username', 'player_name']
                for param in name_params:
                    if param in tool_args:
                        # If the value is too long (likely the entire query), replace it
                        if len(str(tool_args[param])) > len(summoner_name) + 10:
                            print(f"Overriding incorrect {param} value '{tool_args[param][:50]}...' with '{summoner_name}'")
                            tool_args[param] = summoner_name
                        # Also check if it doesn't match our extracted name
                        elif str(tool_args[param]).upper() != summoner_name.upper():
                            # If it's close but not exact, use our extracted name
                            if summoner_name.lower() not in str(tool_args[param]).lower():
                                print(f"Overriding {param} value '{tool_args[param]}' with '{summoner_name}'")
                                tool_args[param] = summoner_name
                
                # Also set it if the parameter exists in the schema but wasn't set
                for param in name_params:
                    if param in properties and param not in tool_args:
                        tool_args[param] = summoner_name
                        print(f"Added missing {param} parameter with value '{summoner_name}'")
            
            # Override tag_line if we have a tagline
            if tagline:
                tagline_params = ['tag_line', 'tagline', 'tag']
                for param in tagline_params:
                    if param in tool_args:
                        if str(tool_args[param]).upper() != tagline.upper():
                            print(f"Overriding {param} value '{tool_args[param]}' with '{tagline}'")
                            tool_args[param] = tagline
                    elif param in properties:
                        tool_args[param] = tagline
                        print(f"Added missing {param} parameter with value '{tagline}'")
                
                # Auto-add region if tool requires it and we can derive it from tagline
                if 'region' in properties and 'region' not in tool_args:
                    region = get_region_from_tagline(tagline)
                    if region:
                        tool_args['region'] = region
                        print(f"Auto-added region '{region}' from tagline '{tagline}'")
            
            # Check for missing required parameters and add defaults
            if tool_name in tool_schemas:
                required_params = schema.get('required', [])
                
                for param in required_params:
                    if param not in tool_args or not tool_args[param]:
                        param_info = properties.get(param, {})
                        enum_values = param_info.get('enum', [])
                        
                        # Use reasonable defaults based on parameter name
                        if param == 'game_mode':
                            tool_args[param] = 'ranked'  # Default to ranked
                        elif param == 'position':
                            # Try to infer from query, otherwise default to 'mid'
                            if 'top' in query.lower():
                                tool_args[param] = 'top'
                            elif 'jungle' in query.lower() or 'jg' in query.lower():
                                tool_args[param] = 'jungle'
                            elif 'adc' in query.lower() or 'bot' in query.lower() or 'bottom' in query.lower():
                                tool_args[param] = 'adc'
                            elif 'support' in query.lower() or 'supp' in query.lower():
                                tool_args[param] = 'support'
                            else:
                                tool_args[param] = 'mid'  # Default to mid
                        elif param == 'champion':
                            # Try to extract champion name from query if not provided
                            if not tool_args.get(param):
                                # This is a fallback - ideally Gemini should extract it
                                print(f"Warning: Champion name not provided for required parameter '{param}'")
                        elif enum_values:
                            # Use first enum value as default
                            tool_args[param] = enum_values[0]
                        else:
                            # Generic default based on type
                            param_type = param_info.get('type', 'string')
                            if param_type == 'string':
                                tool_args[param] = ''
                            elif param_type == 'number':
                                tool_args[param] = 0
                            elif param_type == 'boolean':
                                tool_args[param] = False
                        
                        print(f"Added default value for required parameter '{param}': {tool_args[param]}")
                
                # Validate enum values
                for param, value in tool_args.items():
                    if param in properties:
                        param_info = properties[param]
                        enum_values = param_info.get('enum', [])
                        if enum_values and value not in enum_values:
                            print(f"Warning: Value '{value}' for parameter '{param}' not in enum {enum_values}, using first enum value")
                            tool_args[param] = enum_values[0]
        except json.JSONDecodeError:
            # Fallback: try to extract tool name from text
            print(f"Failed to parse tool decision JSON: {response_text}")
            # Try to find a reasonable default based on query
            if 'champion' in query.lower() and 'win' in query.lower():
                # Find a champion-related tool
                for tool_name_check in available_tools.keys():
                    if 'champion' in tool_name_check.lower():
                        tool_name = tool_name_check
                        tool_args = {}
                        print(f"Using fallback tool: {tool_name}")
                        break
                else:
                    tool_name = list(available_tools.keys())[0] if available_tools else None
                    tool_args = {}
            else:
                tool_name = list(available_tools.keys())[0] if available_tools else None
                tool_args = {}
        
        if not tool_name:
            return "Sorry, I couldn't determine which tool to use for your query. Please try rephrasing your question."
        
        # Call the MCP tool
        print(f"Calling MCP tool: {tool_name} with arguments: {tool_args}")
        mcp_result = await call_opgg_mcp_tool(tool_name, tool_args)
        
        if not mcp_result:
            return "❌ Sorry, I couldn't retrieve the data from OP.GG. The service might be temporarily unavailable. Please try again later."
        
        # Check for error in result
        if isinstance(mcp_result, dict):
            if "error" in mcp_result:
                error_info = mcp_result["error"]
                error_code = error_info.get("code", "unknown")
                error_message = error_info.get("message", "Unknown error")
                
                # Provide user-friendly error messages
                if error_code == -32601:
                    return f"❌ The requested tool '{tool_name}' is not available. Please try rephrasing your query."
                elif error_code == -32602:
                    return f"❌ Invalid parameters for the query. Error: {error_message}"
                elif "not found" in error_message.lower() or "does not exist" in error_message.lower():
                    return f"❌ The summoner or data you're looking for doesn't exist. Please check the name and try again."
                else:
                    return f"❌ Error retrieving data: {error_message}"
        
        # Use Gemini to format the MCP result into a user-friendly response
        formatting_prompt = f"""The user asked: "{query}"

I retrieved this data from OP.GG:
{json.dumps(mcp_result, indent=2)}

Please format this data into a clear, helpful response that directly answers the user's question. Be concise but informative. If the data is complex, summarize the key points."""
        
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=formatting_prompt)],
            ),
        ]
        
        generate_content_config = types.GenerateContentConfig(
            response_mime_type="text/plain",
        )
        
        formatted_response = ""
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            if chunk.text:
                formatted_response += chunk.text
        
        return formatted_response.strip() if formatted_response else str(mcp_result)
        
    except Exception as e:
        print(f"Error in handle_lol_query_with_mcp: {e}")
        return f"Sorry, I encountered an error while processing your League of Legends query: {str(e)}"

async def format_summoner_analysis(mcp_result: dict, summoner_name: str, tagline: str, limit: int = 10) -> str:
    """
    Format summoner match history data into a readable analysis using Gemini.
    
    Args:
        mcp_result: Raw MCP tool result from lol_list_summoner_matches
        summoner_name: Summoner name
        tagline: Summoner tagline
        limit: Number of matches requested
        
    Returns:
        Formatted analysis string
    """
    client = genai.Client(api_key=GEMINI_API_KEY)
    model = "gemini-flash-latest"
    
    analysis_prompt = f"""Analyze this League of Legends match history data for summoner {summoner_name}#{tagline}:

{json.dumps(mcp_result, indent=2)}

Please provide a comprehensive analysis including:
1. Overall win rate and recent performance trends
2. Most played champions and their performance
3. Preferred positions/roles
4. Key statistics (KDA, CS, damage, etc.)
5. Notable patterns or trends
6. Brief improvement suggestions if applicable

Be concise but informative. Format the response in a clear, readable way."""
    
    try:
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=analysis_prompt)],
            ),
        ]
        
        generate_content_config = types.GenerateContentConfig(
            response_mime_type="text/plain",
        )
        
        analysis_response = ""
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            if chunk.text:
                analysis_response += chunk.text
        
        return analysis_response.strip() if analysis_response else "Unable to generate analysis."
    except Exception as e:
        print(f"Error formatting summoner analysis: {e}")
        return f"Match history retrieved, but analysis failed: {str(e)}"

async def format_matchup_guide(mcp_result: dict, my_champion: str, opponent_champion: str, position: str) -> str:
    """
    Format lane matchup guide data into a readable response using Gemini.
    
    Args:
        mcp_result: Raw MCP tool result from lol_get_lane_matchup_guide
        my_champion: Your champion name
        opponent_champion: Opponent champion name
        position: Lane position
        
    Returns:
        Formatted matchup guide string
    """
    client = genai.Client(api_key=GEMINI_API_KEY)
    model = "gemini-flash-latest"
    
    guide_prompt = f"""Format this League of Legends lane matchup guide for {my_champion} vs {opponent_champion} in {position}:

{json.dumps(mcp_result, indent=2)}

Please organize the information clearly, including:
1. Matchup overview and difficulty
2. Rune recommendations
3. Item build suggestions and timings
4. Laning phase tips
5. Key abilities to watch for
6. General strategy

Make it easy to read and actionable."""
    
    try:
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=guide_prompt)],
            ),
        ]
        
        generate_content_config = types.GenerateContentConfig(
            response_mime_type="text/plain",
        )
        
        guide_response = ""
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            if chunk.text:
                guide_response += chunk.text
        
        return guide_response.strip() if guide_response else "Unable to generate matchup guide."
    except Exception as e:
        print(f"Error formatting matchup guide: {e}")
        return f"Matchup data retrieved, but formatting failed: {str(e)}"

async def format_esports_schedule(mcp_result: dict) -> str:
    """
    Format esports schedule data into a readable response using Gemini.
    
    Args:
        mcp_result: Raw MCP tool result from lol_esports_list_schedules
        
    Returns:
        Formatted schedule string
    """
    client = genai.Client(api_key=GEMINI_API_KEY)
    model = "gemini-flash-latest"
    
    schedule_prompt = f"""Format this League of Legends esports schedule:

{json.dumps(mcp_result, indent=2)}

Please organize upcoming matches clearly, including:
1. Match dates and times (convert UTC to readable format)
2. Teams playing
3. League/tournament name
4. Any important context

Make it easy to scan and understand when matches are happening."""
    
    try:
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=schedule_prompt)],
            ),
        ]
        
        generate_content_config = types.GenerateContentConfig(
            response_mime_type="text/plain",
        )
        
        schedule_response = ""
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            if chunk.text:
                schedule_response += chunk.text
        
        return schedule_response.strip() if schedule_response else "Unable to generate schedule."
    except Exception as e:
        print(f"Error formatting esports schedule: {e}")
        return f"Schedule data retrieved, but formatting failed: {str(e)}"

async def format_team_standings(mcp_result: dict, league: str) -> str:
    """
    Format team standings data into a readable response using Gemini.
    
    Args:
        mcp_result: Raw MCP tool result from lol_esports_list_team_standings
        league: League name
        
    Returns:
        Formatted standings string
    """
    client = genai.Client(api_key=GEMINI_API_KEY)
    model = "gemini-flash-latest"
    
    standings_prompt = f"""Format this League of Legends {league.upper()} team standings:

{json.dumps(mcp_result, indent=2)}

Please organize the standings clearly, showing:
1. Team rankings
2. Win/loss records
3. Any relevant statistics
4. Current form or trends if available

Make it easy to read and compare teams."""
    
    try:
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=standings_prompt)],
            ),
        ]
        
        generate_content_config = types.GenerateContentConfig(
            response_mime_type="text/plain",
        )
        
        standings_response = ""
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            if chunk.text:
                standings_response += chunk.text
        
        return standings_response.strip() if standings_response else "Unable to generate standings."
    except Exception as e:
        print(f"Error formatting team standings: {e}")
        return f"Standings data retrieved, but formatting failed: {str(e)}"

def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color to RGB tuple"""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert RGB to hex color"""
    return f"#{r:02x}{g:02x}{b:02x}".upper()

def rgb_to_hsv(r: int, g: int, b: int) -> tuple[int, int, int]:
    """Convert RGB to HSV"""
    h, s, v = colorsys.rgb_to_hsv(r/255.0, g/255.0, b/255.0)
    return (int(h*360), int(s*100), int(v*100))

def rgb_to_hsl(r: int, g: int, b: int) -> tuple[int, int, int]:
    """Convert RGB to HSL"""
    h, l, s = colorsys.rgb_to_hls(r/255.0, g/255.0, b/255.0)
    return (int(h*360), int(s*100), int(l*100))

def rgb_to_cmyk(r: int, g: int, b: int) -> tuple[int, int, int, int]:
    """Convert RGB to CMYK"""
    # Normalize RGB values to 0-1 range
    r, g, b = r/255.0, g/255.0, b/255.0
    
    # Calculate K (black)
    k = 1 - max(r, g, b)
    
    # Avoid division by zero
    if k == 1:
        return (0, 0, 0, 100)
    
    # Calculate CMY
    c = (1 - r - k) / (1 - k)
    m = (1 - g - k) / (1 - k)
    y = (1 - b - k) / (1 - k)
    
    return (int(c*100), int(m*100), int(y*100), int(k*100))

def get_complementary_color(r: int, g: int, b: int) -> tuple[int, int, int]:
    """Get complementary color (opposite on color wheel)"""
    return (255 - r, 255 - g, 255 - b)

def get_color_brightness(r: int, g: int, b: int) -> float:
    """Calculate perceived brightness of color (0-1 scale)"""
    # Using relative luminance formula
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255

def create_color_swatch(hex_color: str, size: tuple[int, int] = (400, 200)) -> io.BytesIO:
    """Create a color swatch image"""
    r, g, b = hex_to_rgb(hex_color)
    
    # Create image with the color
    img = Image.new('RGB', size, (r, g, b))
    draw = ImageDraw.Draw(img)
    
    # Add a subtle border
    border_color = (255, 255, 255) if get_color_brightness(r, g, b) < 0.5 else (0, 0, 0)
    draw.rectangle([(0, 0), (size[0]-1, size[1]-1)], outline=border_color, width=3)
    
    # Save to BytesIO
    img_buffer = io.BytesIO()
    img.save(img_buffer, format='PNG')
    img_buffer.seek(0)
    
    return img_buffer

def interpolate_color(color1: tuple[int, int, int], color2: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    """Interpolate between two RGB colors"""
    r1, g1, b1 = color1
    r2, g2, b2 = color2
    
    r = int(r1 + (r2 - r1) * factor)
    g = int(g1 + (g2 - g1) * factor)
    b = int(b1 + (b2 - b1) * factor)
    
    return (r, g, b)

def create_gradient_swatch(hex_color1: str, hex_color2: str, size: tuple[int, int] = (400, 200), direction: str = "horizontal") -> io.BytesIO:
    """Create a gradient between two colors"""
    r1, g1, b1 = hex_to_rgb(hex_color1)
    r2, g2, b2 = hex_to_rgb(hex_color2)
    
    img = Image.new('RGB', size)
    draw = ImageDraw.Draw(img)
    
    if direction == "horizontal":
        # Horizontal gradient (left to right)
        for x in range(size[0]):
            factor = x / (size[0] - 1)
            color = interpolate_color((r1, g1, b1), (r2, g2, b2), factor)
            draw.line([(x, 0), (x, size[1])], fill=color)
    elif direction == "vertical":
        # Vertical gradient (top to bottom)
        for y in range(size[1]):
            factor = y / (size[1] - 1)
            color = interpolate_color((r1, g1, b1), (r2, g2, b2), factor)
            draw.line([(0, y), (size[0], y)], fill=color)
    elif direction == "diagonal":
        # Diagonal gradient
        for x in range(size[0]):
            for y in range(size[1]):
                factor = (x + y) / (size[0] + size[1] - 2)
                color = interpolate_color((r1, g1, b1), (r2, g2, b2), factor)
                draw.point((x, y), fill=color)
    
    # Add border with averaged color brightness
    avg_brightness = (get_color_brightness(r1, g1, b1) + get_color_brightness(r2, g2, b2)) / 2
    border_color = (255, 255, 255) if avg_brightness < 0.5 else (0, 0, 0)
    draw.rectangle([(0, 0), (size[0]-1, size[1]-1)], outline=border_color, width=3)
    
    # Save to BytesIO
    img_buffer = io.BytesIO()
    img.save(img_buffer, format='PNG')
    img_buffer.seek(0)
    
    return img_buffer

def get_gradient_midpoint_color(hex_color1: str, hex_color2: str) -> str:
    """Get the midpoint color of a gradient"""
    r1, g1, b1 = hex_to_rgb(hex_color1)
    r2, g2, b2 = hex_to_rgb(hex_color2)
    mid_color = interpolate_color((r1, g1, b1), (r2, g2, b2), 0.5)
    return rgb_to_hex(*mid_color)

class Say(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Rate limiting to prevent spam
        self.user_cooldowns = {}
        self.cooldown_duration = 15  # seconds between AI responses per user
        # Pre-fetch champion list on cog load
        asyncio.create_task(self._initialize_champion_cache())
    
    async def _initialize_champion_cache(self):
        """Pre-fetch champion list when cog loads"""
        await fetch_champion_list()
    
    async def champion_autocomplete(self, interaction: nextcord.Interaction, current: str):
        """
        Autocomplete callback for champion name options.
        Filters champions based on user input.
        """
        champion_map = await fetch_champion_list()
        
        if not champion_map:
            # Fallback: return empty list if we can't fetch champions
            return []
        
        # Filter champions that match the current input (case-insensitive)
        current_lower = current.lower()
        matching_champions = [
            name for name in champion_map.keys()
            if current_lower in name.lower()
        ]
        
        # Sort by relevance (exact matches first, then by position of match)
        matching_champions.sort(key=lambda name: (
            not name.lower().startswith(current_lower),  # Exact prefix matches first
            name.lower().find(current_lower)  # Then by position of match
        ))
        
        # Return up to 25 options (Discord's limit)
        # nextcord send_autocomplete expects a list of strings
        return matching_champions[:25]

    @nextcord.slash_command(name='say', description="Send a message as a character. Costs 200 Shmeckles to use.", guild_ids=[GUILD_ID])
    async def say(self, 
                  interaction: nextcord.Interaction, 
                  character: str = nextcord.SlashOption(
                      name="character",
                      description="The character to speak as",
                      choices={"Master Chief": "Master Chief", "Cortana": "Cortana", "Madame Zeroni": "Madame Zeroni", "Zuko": "Zuko", "Babu Frik": "Babu Frik", "Dr. Pepper": "Dr. Pepper"}    
                  ), 
                  message: str = nextcord.SlashOption(
                      name="message",
                      description="The message to say"
                  ),
                  channel: nextcord.abc.GuildChannel = nextcord.SlashOption(
                      name="channel",
                      description="Channel to send the message to (optional)",
                      required=False,
                      channel_types=[nextcord.ChannelType.text] 
                  )):
        
        await interaction.response.defer(ephemeral=True)

        economy_cog = self.bot.get_cog('Economy')
        if not economy_cog:
            await interaction.followup.send("Economy system is currently unavailable. Please try again later.", ephemeral=True)
            return

        user_id = interaction.user.id
        # Assuming economy_cog.get_user_balance is an async method
        current_balance = await economy_cog.get_user_balance(user_id) 

        if current_balance < COST_TO_SAY:
            await interaction.followup.send(f"You need {COST_TO_SAY} coins to use this command, but you only have {current_balance} coins.", ephemeral=True)
            return

        avatar_url = character_avatars.get(character)
        
        webhook_to_use_url = None
        temp_webhook_obj = None
        final_target_channel_obj = None # To store the channel object for mentioning

        try:
            if channel:
                # channel_types in SlashOption should ensure this, but an explicit check is safe.
                if not isinstance(channel, nextcord.TextChannel): 
                    await interaction.followup.send("The specified channel must be a text channel.", ephemeral=True)
                    return
                
                final_target_channel_obj = channel
                bot_member = interaction.guild.me
                if not final_target_channel_obj.permissions_for(bot_member).manage_webhooks:
                    await interaction.followup.send(f"I don't have permission to create webhooks in {final_target_channel_obj.mention}. Please grant 'Manage Webhooks' permission.", ephemeral=True)
                    return

                try:
                    temp_webhook_obj = await final_target_channel_obj.create_webhook(name=character, reason=f"Temporary webhook for /say command by {interaction.user}")
                    webhook_to_use_url = temp_webhook_obj.url
                except nextcord.Forbidden:
                    await interaction.followup.send(f"I'm forbidden from creating a webhook in {final_target_channel_obj.mention}. Please check my permissions.", ephemeral=True)
                    return
                except Exception as e:
                    print(f"Error creating webhook: {e}")
                    await interaction.followup.send("An error occurred while trying to create a webhook for the specified channel.", ephemeral=True)
                    return
            else:
                webhook_to_use_url = webhook_url
                # If you need to mention the default channel, you'll need its ID to fetch the channel object.
                # For example:
                # default_channel_id = YOUR_DEFAULT_WEBHOOK_CHANNEL_ID_HERE 
                # final_target_channel_obj = interaction.guild.get_channel(default_channel_id)

            if not webhook_to_use_url:
                await interaction.followup.send("Could not determine the webhook URL to use.", ephemeral=True)
                if temp_webhook_obj: # Clean up if created but URL somehow not set
                    await temp_webhook_obj.delete(reason="Cleanup after failed /say command (no URL)")
                return

            webhook = DiscordWebhook(url=webhook_to_use_url, content=message, username=character, avatar_url=avatar_url)
            
            loop = asyncio.get_event_loop()
            # discord-webhook's execute() is synchronous, run in executor
            response = await loop.run_in_executor(None, webhook.execute)

            if response.status_code in [200, 204]: # 200: OK, 204: No Content (still success for webhooks)
                # Assuming economy_cog.deduct_user_balance is an async method
                await economy_cog.deduct_user_balance(user_id, COST_TO_SAY) 
                
                channel_mention_str = f"in {final_target_channel_obj.mention}" if final_target_channel_obj else "to the pre-configured channel"
                await interaction.followup.send(f"Message sent as {character} {channel_mention_str}.", ephemeral=True)
                # For logging, get updated balance
                new_balance = await economy_cog.get_user_balance(user_id)
                print(f"Message sent as {character} by {interaction.user.name} ({user_id}) {channel_mention_str}: {message}. Cost: {COST_TO_SAY}. Balance remaining: {new_balance}")
            else:
                # Do not deduct if sending failed
                await interaction.followup.send(f"Failed to send message. Webhook response: {response.status_code} - {response.text}", ephemeral=True)
                print(f"Failed to send message as {character} by {interaction.user.name} ({user_id}): {response.status_code} - {response.text}")

        except Exception as e:
            print(f"An error occurred in /say command: {e}")
            await interaction.followup.send("An unexpected error occurred. Please try again later.", ephemeral=True)
        
        finally:
            if temp_webhook_obj:
                try:
                    await temp_webhook_obj.delete(reason="Cleanup after /say command")
                except Exception as e:
                    webhook_id_for_log = temp_webhook_obj.id if temp_webhook_obj else "Unknown ID"
                    print(f"Error deleting temporary webhook {webhook_id_for_log}: {e}")

    @nextcord.slash_command(name='opgg_summoner', description="Analyze a League of Legends summoner's recent performance", guild_ids=[GUILD_ID])
    async def opgg_summoner(
        self,
        interaction: nextcord.Interaction,
        summoner_name: str = nextcord.SlashOption(
            name="summoner_name",
            description="Summoner name (before the #)"
        ),
        tagline: str = nextcord.SlashOption(
            name="tagline",
            description="Tagline (after the #, e.g., NA1, EUW1)"
        ),
        region: str = nextcord.SlashOption(
            name="region",
            description="Server region",
            required=False,
            choices={"NA": "NA", "EUW": "EUW", "EUNE": "EUNE", "KR": "KR", "BR": "BR", "LAN": "LAN", "LAS": "LAS", "OCE": "OCE", "RU": "RU", "TR": "TR", "JP": "JP"}
        ),
        limit: int = nextcord.SlashOption(
            name="limit",
            description="Number of recent matches to analyze (default: 10)",
            required=False,
            min_value=1,
            max_value=20
        )
    ):
        """Analyze a summoner's recent match history and performance"""
        await interaction.response.defer()
        
        try:
            # Auto-detect region from tagline if not provided
            if not region:
                region = get_region_from_tagline(tagline)
                if not region:
                    await interaction.followup.send(
                        f"❌ Could not determine region from tagline '{tagline}'. Please specify the region manually.",
                        ephemeral=True
                    )
                    return
            
            # Default limit to 10 if not specified
            if not limit:
                limit = 10
            
            # Required output fields for match history
            desired_output_fields = [
                "data.game_history[].participants[].champion_name",
                "data.game_history[].participants[].position",
                "data.game_history[].participants[].stats.kill",
                "data.game_history[].participants[].stats.death",
                "data.game_history[].participants[].stats.assist",
                "data.game_history[].participants[].stats.result",
                "data.game_history[].participants[].stats.op_score",
                "data.game_history[].participants[].stats.gold_earned",
                "data.game_history[].participants[].stats.minion_kill",
                "data.game_history[].participants[].stats.total_damage_dealt_to_champions",
                "data.game_history[].game_type",
                "data.game_history[].created_at",
                "data.game_history[].id"
            ]
            
            # Call MCP tool
            tool_args = {
                "game_name": summoner_name,
                "tag_line": tagline,
                "region": region,
                "lang": "en_US",
                "limit": limit,
                "desired_output_fields": desired_output_fields
            }
            
            mcp_result = await call_opgg_mcp_tool("lol_list_summoner_matches", tool_args)
            
            if not mcp_result:
                await interaction.followup.send(
                    f"❌ Failed to retrieve match history for {summoner_name}#{tagline}. The summoner may not exist or the service may be unavailable.",
                    ephemeral=True
                )
                return
            
            # Check for errors in result
            if isinstance(mcp_result, dict) and "error" in mcp_result:
                error_msg = mcp_result.get("error", {}).get("message", "Unknown error")
                await interaction.followup.send(
                    f"❌ Error retrieving match history: {error_msg}",
                    ephemeral=True
                )
                return
            
            # Format the analysis
            analysis = await format_summoner_analysis(mcp_result, summoner_name, tagline, limit)
            
            # Clean up numeric IDs (Rune IDs, Item IDs, etc.)
            analysis = clean_numeric_ids(analysis)
            
            # Format tables for Discord
            analysis = format_table_for_discord(analysis)
            
            # Split into sections if needed
            sections = split_response_into_sections(analysis, max_length=4000)
            
            # Send multiple embeds if needed
            for i, section in enumerate(sections):
                # Truncate section if still too long (safety check)
                section = truncate_embed_description(section, max_length=4096)
                
                # Create embed
                title = f"Summoner Analysis: {summoner_name}#{tagline}"
                if len(sections) > 1:
                    title += f" ({i+1}/{len(sections)})"
                
                embed = nextcord.Embed(
                    title=title,
                    description=section,
                    color=nextcord.Color.gold()
                )
                embed.set_footer(text=f"Region: {region} • {limit} recent matches")
                embed.timestamp = nextcord.utils.utcnow()
                
                await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"Error in /opgg_summoner: {e}")
            await interaction.followup.send(
                f"❌ An error occurred while analyzing the summoner: {str(e)}",
                ephemeral=True
            )

    @nextcord.slash_command(name='opgg_matchup', description="Get lane matchup guide for League of Legends", guild_ids=[GUILD_ID])
    async def opgg_matchup(
        self,
        interaction: nextcord.Interaction,
        my_champion: str = nextcord.SlashOption(
            name="my_champion",
            description="Your champion name",
            autocomplete=True
        ),
        opponent_champion: str = nextcord.SlashOption(
            name="opponent_champion",
            description="Opponent champion name",
            autocomplete=True
        ),
        position: str = nextcord.SlashOption(
            name="position",
            description="Lane position",
            choices={"top": "top", "mid": "mid", "jungle": "jungle", "adc": "adc", "support": "support"}
        )
    ):
        """Get lane matchup guide for your champion vs opponent"""
        await interaction.response.defer()
        
        try:
            # Get champion mapping to convert display names to internal names
            champion_map = await fetch_champion_list()
            
            # Convert champion names to UPPER_SNAKE_CASE (internal format)
            # Use cached mapping if available, otherwise fallback to simple conversion
            if champion_map and my_champion in champion_map:
                my_champ_upper = champion_map[my_champion]
            else:
                # Fallback: convert to UPPER_SNAKE_CASE manually
                my_champ_upper = my_champion.upper().replace(" ", "_")
            
            if champion_map and opponent_champion in champion_map:
                opponent_champ_upper = champion_map[opponent_champion]
            else:
                # Fallback: convert to UPPER_SNAKE_CASE manually
                opponent_champ_upper = opponent_champion.upper().replace(" ", "_")
            
            # Call MCP tool
            tool_args = {
                "lang": "en_US",
                "position": position,
                "my_champion": my_champ_upper,
                "opponent_champion": opponent_champ_upper
            }
            
            mcp_result = await call_opgg_mcp_tool("lol_get_lane_matchup_guide", tool_args)
            
            if not mcp_result:
                await interaction.followup.send(
                    f"❌ Failed to retrieve matchup guide for {my_champion} vs {opponent_champion}. Please check champion names and try again.",
                    ephemeral=True
                )
                return
            
            # Check for errors
            if isinstance(mcp_result, dict) and "error" in mcp_result:
                error_msg = mcp_result.get("error", {}).get("message", "Unknown error")
                await interaction.followup.send(
                    f"❌ Error retrieving matchup guide: {error_msg}",
                    ephemeral=True
                )
                return
            
            # Format the guide
            guide = await format_matchup_guide(mcp_result, my_champion, opponent_champion, position)
            
            # Clean up numeric IDs (Rune IDs, Item IDs, etc.)
            guide = clean_numeric_ids(guide)
            
            # Format tables for Discord
            guide = format_table_for_discord(guide)
            
            # Split into sections if needed
            sections = split_response_into_sections(guide, max_length=4000)
            
            # Send multiple embeds if needed
            for i, section in enumerate(sections):
                # Truncate section if still too long (safety check)
                section = truncate_embed_description(section, max_length=4096)
                
                # Create embed
                title = f"Matchup Guide: {my_champion} vs {opponent_champion} ({position})"
                if len(sections) > 1:
                    title += f" ({i+1}/{len(sections)})"
                
                embed = nextcord.Embed(
                    title=title,
                    description=section,
                    color=nextcord.Color.blue()
                )
                embed.set_footer(text=f"Position: {position.title()}")
                embed.timestamp = nextcord.utils.utcnow()
                
                await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"Error in /opgg_matchup: {e}")
            await interaction.followup.send(
                f"❌ An error occurred while retrieving the matchup guide: {str(e)}",
                ephemeral=True
            )
    
    @opgg_matchup.on_autocomplete("my_champion")
    async def my_champion_autocomplete(self, interaction: nextcord.Interaction, current: str):
        """Autocomplete for my_champion option"""
        choices = await self.champion_autocomplete(interaction, current)
        await interaction.response.send_autocomplete(choices)
    
    @opgg_matchup.on_autocomplete("opponent_champion")
    async def opponent_champion_autocomplete(self, interaction: nextcord.Interaction, current: str):
        """Autocomplete for opponent_champion option"""
        choices = await self.champion_autocomplete(interaction, current)
        await interaction.response.send_autocomplete(choices)

    @nextcord.slash_command(name='opgg_esports_schedule', description="View upcoming League of Legends esports matches", guild_ids=[GUILD_ID])
    async def opgg_esports_schedule(self, interaction: nextcord.Interaction):
        """Get upcoming esports match schedules"""
        await interaction.response.defer()
        
        try:
            # Call MCP tool (no parameters needed)
            mcp_result = await call_opgg_mcp_tool("lol_esports_list_schedules", {})
            
            if not mcp_result:
                await interaction.followup.send(
                    "❌ Failed to retrieve esports schedule. The service may be temporarily unavailable.",
                    ephemeral=True
                )
                return
            
            # Check for errors
            if isinstance(mcp_result, dict) and "error" in mcp_result:
                error_msg = mcp_result.get("error", {}).get("message", "Unknown error")
                await interaction.followup.send(
                    f"❌ Error retrieving schedule: {error_msg}",
                    ephemeral=True
                )
                return
            
            # Format the schedule
            schedule = await format_esports_schedule(mcp_result)
            
            # Truncate if too long for Discord embed
            schedule = truncate_embed_description(schedule)
            
            # Create embed
            embed = nextcord.Embed(
                title="Upcoming LoL Esports Matches",
                description=schedule,
                color=nextcord.Color.purple()
            )
            embed.timestamp = nextcord.utils.utcnow()
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"Error in /opgg_esports_schedule: {e}")
            await interaction.followup.send(
                f"❌ An error occurred while retrieving the schedule: {str(e)}",
                ephemeral=True
            )

    @nextcord.slash_command(name='opgg_standings', description="View League of Legends esports team standings", guild_ids=[GUILD_ID])
    async def opgg_standings(
        self,
        interaction: nextcord.Interaction,
        league: str = nextcord.SlashOption(
            name="league",
            description="League to view standings for",
            choices={
                "LCK": "lck",
                "LPL": "lpl",
                "LEC": "lec",
                "LCS": "lcs",
                "LJL": "ljl",
                "VCS": "vcs",
                "CBLOL": "cblol",
                "LCL": "lcl",
                "LLA": "lla",
                "TCL": "tcl",
                "PCS": "pcs",
                "LCO": "lco",
                "MSI": "msi",
                "Worlds": "worlds"
            }
        )
    ):
        """Get team standings for a League of Legends esports league"""
        await interaction.response.defer()
        
        try:
            # Call MCP tool
            tool_args = {
                "short_name": league.lower()
            }
            
            mcp_result = await call_opgg_mcp_tool("lol_esports_list_team_standings", tool_args)
            
            if not mcp_result:
                await interaction.followup.send(
                    f"❌ Failed to retrieve standings for {league.upper()}. The service may be temporarily unavailable.",
                    ephemeral=True
                )
                return
            
            # Check for errors
            if isinstance(mcp_result, dict) and "error" in mcp_result:
                error_msg = mcp_result.get("error", {}).get("message", "Unknown error")
                await interaction.followup.send(
                    f"❌ Error retrieving standings: {error_msg}",
                    ephemeral=True
                )
                return
            
            # Format the standings
            standings = await format_team_standings(mcp_result, league)
            
            # Truncate if too long for Discord embed
            standings = truncate_embed_description(standings)
            
            # Create embed
            embed = nextcord.Embed(
                title=f"{league.upper()} Team Standings",
                description=standings,
                color=nextcord.Color.green()
            )
            embed.timestamp = nextcord.utils.utcnow()
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"Error in /opgg_standings: {e}")
            await interaction.followup.send(
                f"❌ An error occurred while retrieving the standings: {str(e)}",
                ephemeral=True
            )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: nextcord.RawReactionActionEvent):
        # Ignore reactions from bots
        if payload.user_id == self.bot.user.id:
            return
        
        # Fetch the user who reacted
        user = self.bot.get_user(payload.user_id)
        if user is None: # Fallback if user not in cache
            try:
                user = await self.bot.fetch_user(payload.user_id)
            except nextcord.NotFound:
                print(f"[REACTION DEBUG] User {payload.user_id} not found.")
                return
        
        if user.bot: # Check again after fetching, just in case
            return

        # Fetch the channel and message
        try:
            channel = self.bot.get_channel(payload.channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(payload.channel_id)
            
            if not isinstance(channel, nextcord.TextChannel): # Ensure it's a text channel
                return

            message = await channel.fetch_message(payload.message_id)
        except nextcord.NotFound:
            print(f"[REACTION DEBUG] Message or Channel not found for reaction (Msg ID: {payload.message_id}, Chan ID: {payload.channel_id}).")
            return
        except nextcord.Forbidden:
            print(f"[REACTION DEBUG] Bot lacks permissions to fetch message/channel for reaction (Msg ID: {payload.message_id}, Chan ID: {payload.channel_id}).")
            return
        except Exception as e:
            print(f"[REACTION DEBUG] Error fetching message/channel: {e}")
            return

        generator_function = None
        character_name = None
        response_prefix = None

        if str(payload.emoji) == ZERONI_REACTION_EMOJI and message.content:
            print(f"'{ZERONI_REACTION_EMOJI}' reaction detected from {user.name} on message in #{channel.name}")
            generator_function = generate_zeroni
            character_name = "Madame Zeroni"
            response_prefix = "Madame Zeroni (via raw reaction)"

        elif str(payload.emoji) == COMMUNITY_NOTES_REACTION_EMOJI and message.content:
            print(f"'{COMMUNITY_NOTES_REACTION_EMOJI}' reaction detected from {user.name} on message in #{channel.name}")
            generator_function = lambda text: generate_notes(text, True)  # Enable web search for reactions too
            character_name = "Community Note"
            response_prefix = "Community Note (via raw reaction)"
        else:
            return

        try:
            loop = asyncio.get_event_loop()
            api_response_content = await loop.run_in_executor(None, generator_function, message.content)

            if not api_response_content:
                print(f"{response_prefix} had no response for: \"{message.content[:50]}...\"")
                return

            embed_description = f"{api_response_content}\n\n[Jump to original message]({message.jump_url})"

            embed = nextcord.Embed(
                description=embed_description,
                color=nextcord.Color.blue() # You can choose a color
            )

            if character_name == "Community Note":
                # Set the bot as the author for Community Notes
                bot_user = self.bot.user
                embed.set_author(name=f"{bot_user.display_name} [Community Note]", icon_url=bot_user.display_avatar.url if bot_user.display_avatar else nextcord.Embed.Empty)
            elif character_name:
                # For other characters, use the character_avatars
                avatar_url = character_avatars.get(character_name)
                author_icon_url = avatar_url if avatar_url and isinstance(avatar_url, str) and avatar_url.startswith(('http://', 'https://')) else nextcord.Embed.Empty
                embed.set_author(name=character_name, icon_url=author_icon_url)
            
            # Add a footer to indicate it was triggered by a reaction
            user_display_avatar_url = user.display_avatar.url if user.display_avatar else nextcord.Embed.Empty
            embed.set_footer(text=f"Triggered by {user.display_name}'s reaction", icon_url=user_display_avatar_url)
            embed.timestamp = nextcord.utils.utcnow()

            # Send the embed to the channel where the reaction occurred
            await channel.send(embed=embed)
            print(f"Sent {character_name} embed response to #{channel.name} for message ID {message.id}")

        except nextcord.Forbidden:
            print(f"Bot lacks 'Send Messages' or 'Embed Links' permission in {channel.name} for {character_name} reaction response.")
            # You might want to notify the user or log this more formally
            # await message.reply(f"I can't post {character_name}'s response here. I might be missing 'Send Messages' or 'Embed Links' permissions in {channel.mention}.", delete_after=30)
        except Exception as e:
            print(f"An error occurred in on_raw_reaction_add for {character_name}: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message):
        """Handle bot mentions, replies to bot messages, and hex color detection"""
        # Ignore messages from bots (including self)
        if message.author.bot:
            return
        
        # Ignore messages without content
        if not message.content.strip():
            return
        
        # Check for hex colors first (since they don't require rate limiting)
        hex_pattern = r'#[0-9A-Fa-f]{6}\b'
        hex_matches = re.findall(hex_pattern, message.content)
        
        if hex_matches:
            # Handle hex color detection (supports 1-2 colors)
            colors_to_process = hex_matches[:2]  # Limit to first 2 colors
            await self._handle_hex_colors(message, colors_to_process)
            return  # Don't process as mention/reply if it's a hex color
        
        # Check if bot is mentioned
        bot_mentioned = self.bot.user in message.mentions
        
        # Check if this is a reply to any message and get the referenced message
        referenced_message = None
        is_reply_to_bot = False
        is_reply_with_mention = False
        
        if message.reference and message.reference.message_id:
            try:
                referenced_message = await message.channel.fetch_message(message.reference.message_id)
                is_reply_to_bot = referenced_message.author == self.bot.user
                is_reply_with_mention = bot_mentioned and referenced_message.author != self.bot.user
            except (nextcord.NotFound, nextcord.Forbidden):
                referenced_message = None
                is_reply_to_bot = False
                is_reply_with_mention = False
        
        # Process if bot was mentioned, replying to bot, or mentioned in a reply to someone else
        if bot_mentioned or is_reply_to_bot:
            # Check rate limiting
            current_time = time.time()
            user_id = message.author.id
            
            if user_id in self.user_cooldowns:
                time_since_last = current_time - self.user_cooldowns[user_id]
                if time_since_last < self.cooldown_duration:
                    # User is on cooldown, send ephemeral message
                    remaining_time = int(self.cooldown_duration - time_since_last)
                    try:
                        await message.reply(
                            f"⏰ Please wait {remaining_time} more seconds before requesting another AI response.",
                            delete_after=10,
                            mention_author=False
                        )
                    except nextcord.Forbidden:
                        # If we can't send a message, try to react with a clock emoji
                        try:
                            await message.add_reaction("⏰")
                        except:
                            pass  # Silent fail if we can't even react
                    return
            
            # Update cooldown
            self.user_cooldowns[user_id] = current_time
            
            # Determine trigger type for logging and context
            if is_reply_with_mention:
                trigger_type = "mention in reply"
            elif bot_mentioned:
                trigger_type = "mention"
            else:
                trigger_type = "reply"
            
            print(f"Bot {trigger_type} detected from {message.author.name} in #{message.channel.name}: {message.content[:100]}...")
            
            # Process the message content with context
            content_to_process = message.content
            
            # Remove bot mention from content if present
            if bot_mentioned:
                content_to_process = re.sub(f'<@!?{self.bot.user.id}>', '', content_to_process).strip()
            
            # Build context-aware prompt
            if is_reply_with_mention and referenced_message:
                # When bot is mentioned in a reply, include both the original message and the reply
                context_prompt = f"""Original message from {referenced_message.author.display_name}: "{referenced_message.content}"

Reply from {message.author.display_name} (mentioning you): "{content_to_process}"

Please respond considering both the original message context and the user's reply."""
            elif is_reply_to_bot and referenced_message:
                # When replying to bot, include the bot's previous message for context
                context_prompt = f"""Previous bot message: "{referenced_message.content}"

User's reply: "{content_to_process}"

Please respond to the user's reply in context of the previous conversation."""
            else:
                # Direct mention without reply context
                context_prompt = content_to_process
            
            # Skip if no meaningful content remains
            if not content_to_process and not (is_reply_with_mention and referenced_message):
                return
            
            try:
                # Check if this is a summoner search query
                summoner_name, extracted_tagline = extract_summoner_info(context_prompt)
                has_valid_summoner_format = summoner_name is not None and extracted_tagline is not None
                
                # Check if query mentions summoner-related keywords (even without proper format)
                summoner_keywords = ['summoner', 'player', 'stats for', 'match history', 'game history', 'champs has', 'champions has']
                has_summoner_keyword = any(keyword in context_prompt.lower() for keyword in summoner_keywords)
                
                # Determine if this is a League of Legends query and route accordingly
                query_method = await decide_query_method(context_prompt)
                
                if query_method == 'mcp':
                    # Use OP.GG MCP tools for LoL-specific queries
                    print(f"Using OP.GG MCP tools for query: {context_prompt[:50]}...")
                    
                    # If this looks like a summoner search but doesn't have the required tagline format, prompt user
                    if has_summoner_keyword and not has_valid_summoner_format:
                        # Send error message requiring tagline format
                        embed = nextcord.Embed(
                            description=f"❌ **Summoner Format Required**\n\n"
                                      f"For summoner searches, you must include the summoner name and tagline in **quotation marks** using the format: **\"Name#Tagline\"**\n\n"
                                      f"**Examples:**\n"
                                      f"• `What champs has \"JJ3571#NA1\" been playing?`\n"
                                      f"• `Show me stats for \"PlayerName#EUW1\"`\n"
                                      f"• `Search for summoner \"Username With Spaces#KR1\"`\n\n"
                                      f"**Note:** Quotation marks are required to properly identify the summoner name, especially if it contains spaces.\n\n"
                                      f"Common taglines: NA1, EUW1, EUNE1, KR1, BR1, etc.",
                            color=nextcord.Color.red()
                        )
                        
                        bot_user = self.bot.user
                        embed.set_author(
                            name=f"{bot_user.display_name} [OP.GG]", 
                            icon_url=bot_user.display_avatar.url if bot_user.display_avatar else nextcord.Embed.Empty
                        )
                        
                        embed.set_footer(
                            text="Please include the tagline in your query",
                            icon_url=message.author.display_avatar.url if message.author.display_avatar else nextcord.Embed.Empty
                        )
                        embed.timestamp = nextcord.utils.utcnow()
                        
                        await message.reply(embed=embed, mention_author=False)
                        return
                    
                    # Use extracted tagline if available, otherwise let the function handle it
                    try:
                        api_response_content = await handle_lol_query_with_mcp(context_prompt, summoner_name=summoner_name, tagline=extracted_tagline)
                    except Exception as e:
                        print(f"Error in handle_lol_query_with_mcp: {e}")
                        api_response_content = f"❌ An error occurred while processing your League of Legends query: {str(e)}. Please try again or use a slash command like `/opgg_summoner`."
                else:
                    # Use Gemini web search for general queries
                    print(f"Using Gemini web search for query: {context_prompt[:50]}...")
                    try:
                        loop = asyncio.get_event_loop()
                        api_response_content = await loop.run_in_executor(
                            None, 
                            generate_notes, 
                            context_prompt,
                            True  # Enable web search
                        )
                    except Exception as e:
                        print(f"Error in generate_notes: {e}")
                        api_response_content = f"❌ An error occurred while processing your query: {str(e)}. Please try again."

                if not api_response_content:
                    print(f"No response generated for {trigger_type}: \"{content_to_process[:50]}...\"")
                    # Send a helpful error message
                    error_embed = nextcord.Embed(
                        description="❌ I couldn't generate a response for your query. Please try rephrasing or use a specific command.",
                        color=nextcord.Color.red()
                    )
                    error_embed.set_footer(text="Tip: For League of Legends data, try /opgg_summoner or /opgg_matchup")
                    try:
                        await message.reply(embed=error_embed, mention_author=False)
                    except:
                        pass
                    return
                
                # Check if response is an error message (starts with ❌)
                if api_response_content.startswith("❌"):
                    # Create error embed for better visibility
                    error_description = truncate_embed_description(api_response_content)
                    error_embed = nextcord.Embed(
                        description=error_description,
                        color=nextcord.Color.red()
                    )
                    bot_user = self.bot.user
                    error_embed.set_author(
                        name=f"{bot_user.display_name} [OP.GG]", 
                        icon_url=bot_user.display_avatar.url if bot_user.display_avatar else nextcord.Embed.Empty
                    )
                    error_embed.set_footer(
                        text="Tip: Use /opgg_summoner for summoner analysis or /opgg_matchup for matchup guides",
                        icon_url=message.author.display_avatar.url if message.author.display_avatar else nextcord.Embed.Empty
                    )
                    error_embed.timestamp = nextcord.utils.utcnow()
                    try:
                        await message.reply(embed=error_embed, mention_author=False)
                    except:
                        pass
                    return

                # Clean up numeric IDs (Rune IDs, Item IDs, etc.)
                api_response_content = clean_numeric_ids(api_response_content)
                
                # Format tables for Discord
                api_response_content = format_table_for_discord(api_response_content)
                
                # Split into sections if needed
                sections = split_response_into_sections(api_response_content, max_length=3800)
                
                # Choose embed color based on data source
                embed_color = nextcord.Color.gold() if query_method == 'mcp' else nextcord.Color.blue()
                
                # Set up common embed properties
                bot_user = self.bot.user
                author_name = f"{bot_user.display_name} [OP.GG]" if query_method == 'mcp' else bot_user.display_name
                user_display_avatar_url = message.author.display_avatar.url if message.author.display_avatar else nextcord.Embed.Empty
                data_source = "OP.GG MCP" if query_method == 'mcp' else "Web Search"
                
                # Build context link text
                context_link = ""
                if is_reply_with_mention and referenced_message:
                    context_link = f"\n\n[Responding to this conversation]({message.reference.jump_url})"
                elif is_reply_to_bot and referenced_message:
                    context_link = f"\n\n[In reply to this message]({message.reference.jump_url})"
                
                # Build footer text
                if is_reply_with_mention:
                    footer_text = f"Triggered by {message.author.display_name}'s mention in reply • {data_source}"
                elif bot_mentioned:
                    footer_text = f"Triggered by {message.author.display_name}'s mention • {data_source}"
                else:
                    footer_text = f"Triggered by {message.author.display_name}'s reply • {data_source}"
                
                # Send multiple embeds if needed
                for i, section in enumerate(sections):
                    embed_description = section
                    
                    # Add context link only to last embed
                    if i == len(sections) - 1:
                        embed_description += context_link
                    
                    # Truncate if still too long (safety check)
                    embed_description = truncate_embed_description(embed_description, max_length=4096)
                    
                    embed = nextcord.Embed(
                        description=embed_description,
                        color=embed_color
                    )
                    
                    embed.set_author(
                        name=author_name, 
                        icon_url=bot_user.display_avatar.url if bot_user.display_avatar else nextcord.Embed.Empty
                    )
                    
                    # Add page number to footer if multiple sections
                    if len(sections) > 1:
                        footer_text_with_page = f"{footer_text} • Page {i+1}/{len(sections)}"
                    else:
                        footer_text_with_page = footer_text
                    
                    embed.set_footer(
                        text=footer_text_with_page, 
                        icon_url=user_display_avatar_url
                    )
                    embed.timestamp = nextcord.utils.utcnow()
                    
                    # Send the response (reply only to first embed)
                    if i == 0:
                        await message.reply(embed=embed, mention_author=False)
                    else:
                        await message.channel.send(embed=embed)
                print(f"Sent enhanced response to {trigger_type} in #{message.channel.name}")

            except nextcord.Forbidden:
                print(f"Bot lacks permissions to respond to {trigger_type} in {message.channel.name}")
                try:
                    # Try to react with an emoji to indicate we saw the message but can't respond
                    await message.add_reaction("👀")
                except:
                    pass  # If we can't even react, just silently fail
            except Exception as e:
                print(f"An error occurred processing {trigger_type}: {e}")

    async def _handle_hex_colors(self, message: nextcord.Message, hex_colors: list[str]):
        """Handle hex color detection and display color information"""
        try:
            # Handle single color vs gradient
            if len(hex_colors) == 1:
                await self._handle_single_color(message, hex_colors[0])
            elif len(hex_colors) >= 2:
                await self._handle_gradient_colors(message, hex_colors[0], hex_colors[1])
            
        except nextcord.Forbidden:
            print(f"Bot lacks permissions to respond with color info in {message.channel.name}")
            try:
                await message.add_reaction("🎨")
            except:
                pass
        except Exception as e:
            print(f"An error occurred processing hex colors {hex_colors}: {e}")

    async def _handle_single_color(self, message: nextcord.Message, hex_color: str):
        """Handle single hex color display"""
        hex_color = hex_color.upper()
        print(f"Hex color {hex_color} detected from {message.author.name} in #{message.channel.name}")
        
        # Convert to various color formats
        r, g, b = hex_to_rgb(hex_color)
        hsv_h, hsv_s, hsv_v = rgb_to_hsv(r, g, b)
        hsl_h, hsl_s, hsl_l = rgb_to_hsl(r, g, b)
        c, m, y, k = rgb_to_cmyk(r, g, b)
        comp_r, comp_g, comp_b = get_complementary_color(r, g, b)
        comp_hex = rgb_to_hex(comp_r, comp_g, comp_b)
        
        # Create color swatch image
        color_swatch = create_color_swatch(hex_color)
        
        # Create embed with color information
        embed = nextcord.Embed(
            title=f"Color Information: {hex_color}",
            color=int(hex_color.lstrip('#'), 16),
            description=f"Here's detailed information about the color **{hex_color}**"
        )
        
        # Add color format fields
        embed.add_field(
            name="Color Formats",
            value=f"**HEX:** {hex_color}\n"
                  f"**RGB:** {r}, {g}, {b}\n"
                  f"**HSV:** {hsv_h}°, {hsv_s}%, {hsv_v}%\n"
                  f"**HSL:** {hsl_h}°, {hsl_s}%, {hsl_l}%\n"
                  f"**CMYK:** {c}%, {m}%, {y}%, {k}%",
            inline=True
        )
        
        # Add complementary color info
        embed.add_field(
            name="Complementary Color",
            value=f"**HEX:** {comp_hex}\n"
                  f"**RGB:** {comp_r}, {comp_g}, {comp_b}",
            inline=True
        )
        
        # Add color properties
        brightness = get_color_brightness(r, g, b)
        brightness_desc = "Light" if brightness > 0.5 else "Dark"
        
        embed.add_field(
            name="Properties",
            value=f"**Brightness:** {brightness:.2f} ({brightness_desc})\n"
                  f"**Best Text Color:** {'Black' if brightness > 0.5 else 'White'}",
            inline=True
        )
        
        # Set footer
        embed.set_footer(
            text=f"Color detected from {message.author.display_name}'s message",
            icon_url=message.author.display_avatar.url if message.author.display_avatar else nextcord.Embed.Empty
        )
        embed.timestamp = nextcord.utils.utcnow()
        
        # Create view with complementary color button
        view = ComplementaryColorView(hex_color, comp_hex)
        view.children[0].label = f"View {comp_hex}"
        
        # Upload color swatch as file and send embed
        file = nextcord.File(color_swatch, filename=f"color_{hex_color.lstrip('#')}.png")
        embed.set_image(url=f"attachment://color_{hex_color.lstrip('#')}.png")
        
        await message.reply(embed=embed, file=file, view=view, mention_author=False)
        print(f"Sent color information for {hex_color} in #{message.channel.name}")

    async def _handle_gradient_colors(self, message: nextcord.Message, hex_color1: str, hex_color2: str):
        """Handle gradient between two hex colors"""
        hex_color1 = hex_color1.upper()
        hex_color2 = hex_color2.upper()
        print(f"Gradient {hex_color1} → {hex_color2} detected from {message.author.name} in #{message.channel.name}")
        
        # Get color information for both colors
        r1, g1, b1 = hex_to_rgb(hex_color1)
        r2, g2, b2 = hex_to_rgb(hex_color2)
        
        # Get midpoint color for embed color
        midpoint_hex = get_gradient_midpoint_color(hex_color1, hex_color2)
        
        # Create gradient image
        gradient_swatch = create_gradient_swatch(hex_color1, hex_color2, size=(500, 200))
        
        # Create embed with gradient information
        embed = nextcord.Embed(
            title=f"Color Gradient: {hex_color1} → {hex_color2}",
            color=int(midpoint_hex.lstrip('#'), 16),
            description=f"Beautiful gradient between **{hex_color1}** and **{hex_color2}**"
        )
        
        # Start color info
        hsv1_h, hsv1_s, hsv1_v = rgb_to_hsv(r1, g1, b1)
        
        embed.add_field(
            name=f"Start Color ({hex_color1})",
            value=f"**RGB:** {r1}, {g1}, {b1}\n"
                  f"**HSV:** {hsv1_h}°, {hsv1_s}%, {hsv1_v}%",
            inline=True
        )
        
        # End color info
        hsv2_h, hsv2_s, hsv2_v = rgb_to_hsv(r2, g2, b2)
        
        embed.add_field(
            name=f"End Color ({hex_color2})",
            value=f"**RGB:** {r2}, {g2}, {b2}\n"
                  f"**HSV:** {hsv2_h}°, {hsv2_s}%, {hsv2_v}%",
            inline=True
        )
        
        # Midpoint color info
        mid_r, mid_g, mid_b = hex_to_rgb(midpoint_hex)
        
        embed.add_field(
            name=f"Midpoint ({midpoint_hex})",
            value=f"**RGB:** {mid_r}, {mid_g}, {mid_b}\n"
                  f"**Blend:** 50/50 mix",
            inline=True
        )
        
        # Gradient properties
        color_distance = ((r2-r1)**2 + (g2-g1)**2 + (b2-b1)**2) ** 0.5
        brightness_diff = abs(get_color_brightness(r1, g1, b1) - get_color_brightness(r2, g2, b2))
        
        embed.add_field(
            name="Gradient Properties",
            value=f"**Color Distance:** {color_distance:.1f}\n"
                  f"**Brightness Diff:** {brightness_diff:.2f}\n"
                  f"**Transition:** {'Smooth' if color_distance < 200 else 'Bold'}",
            inline=True
        )
        
        # Set footer
        embed.set_footer(
            text=f"Gradient detected from {message.author.display_name}'s message • Horizontal gradient shown",
            icon_url=message.author.display_avatar.url if message.author.display_avatar else nextcord.Embed.Empty
        )
        embed.timestamp = nextcord.utils.utcnow()
        
        # Upload gradient as file and send embed
        filename = f"gradient_{hex_color1.lstrip('#')}_{hex_color2.lstrip('#')}.png"
        file = nextcord.File(gradient_swatch, filename=filename)
        embed.set_image(url=f"attachment://{filename}")
        
        await message.reply(embed=embed, file=file, mention_author=False)
        print(f"Sent gradient information for {hex_color1} → {hex_color2} in #{message.channel.name}")

    def _get_color_name(self, r: int, g: int, b: int) -> str:
        """Get a basic color name based on RGB values"""
        # Simple color name detection based on dominant channels
        if r > 200 and g < 100 and b < 100:
            return "Red"
        elif r < 100 and g > 200 and b < 100:
            return "Green"
        elif r < 100 and g < 100 and b > 200:
            return "Blue"
        elif r > 200 and g > 200 and b < 100:
            return "Yellow"
        elif r > 200 and g < 100 and b > 200:
            return "Magenta"
        elif r < 100 and g > 200 and b > 200:
            return "Cyan"
        elif r > 200 and g > 200 and b > 200:
            return "White"
        elif r < 50 and g < 50 and b < 50:
            return "Black"
        elif r > 100 and g > 100 and b > 100:
            return "Gray"
        elif r > 150 and g > 100 and b < 100:
            return "Orange"
        elif r > 100 and g < 100 and b > 150:
            return "Purple"
        else:
            return None

    async def _generate_contextual_response(self, content: str, context_type: str, original_message=None):
        """Generate a contextual response based on the trigger type"""
        # This helper method could be expanded for different response types
        # For now, we'll use the enhanced generate_notes function
        
        context_prompt = content
        if context_type == "reply" and original_message:
            context_prompt = f"User is replying to a previous message. Original context: '{original_message.content[:200]}...' User's reply: '{content}'"
        elif context_type == "mention":
            context_prompt = f"User mentioned the bot directly with: '{content}'"
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, generate_notes, context_prompt, True)


def setup(bot):
    bot.add_cog(Say(bot))
    print("SayCog has been added to the bot.")