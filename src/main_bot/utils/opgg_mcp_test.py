import nextcord
from nextcord.ext import commands
import json
import aiohttp
from main_bot.server_configs.config import GUILD_ID

# OP.GG MCP Server endpoint
OPGG_MCP_ENDPOINT = "https://mcp-api.op.gg/mcp"


class ToolListPaginationView(nextcord.ui.View):
    """View for paginating through the tool list"""
    
    def __init__(self, pages: list[str], timeout: float = 300.0):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.current_page = 0
        self.max_pages = len(pages)
    
    def update_buttons(self):
        """Update button states based on current page"""
        self.first_page.disabled = self.current_page == 0
        self.prev_page.disabled = self.current_page == 0
        self.next_page.disabled = self.current_page >= self.max_pages - 1
        self.last_page.disabled = self.current_page >= self.max_pages - 1
        self.page_info.label = f"Page {self.current_page + 1}/{self.max_pages}"
    
    @nextcord.ui.button(label="⏮ First", style=nextcord.ButtonStyle.secondary)
    async def first_page(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.current_page = 0
        self.update_buttons()
        embed = nextcord.Embed(
            title="OP.GG MCP Tools",
            description=self.pages[self.current_page],
            color=nextcord.Color.blue()
        )
        embed.set_footer(text=f"Page {self.current_page + 1} of {self.max_pages}")
        await interaction.response.edit_message(embed=embed, view=self)
    
    @nextcord.ui.button(label="◀ Prev", style=nextcord.ButtonStyle.primary)
    async def prev_page(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            embed = nextcord.Embed(
                title="OP.GG MCP Tools",
                description=self.pages[self.current_page],
                color=nextcord.Color.blue()
            )
            embed.set_footer(text=f"Page {self.current_page + 1} of {self.max_pages}")
            await interaction.response.edit_message(embed=embed, view=self)
    
    @nextcord.ui.button(label="Page 1/1", style=nextcord.ButtonStyle.secondary, disabled=True)
    async def page_info(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        # This button is just for display, no action needed
        pass
    
    @nextcord.ui.button(label="Next ▶", style=nextcord.ButtonStyle.primary)
    async def next_page(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if self.current_page < self.max_pages - 1:
            self.current_page += 1
            self.update_buttons()
            embed = nextcord.Embed(
                title="OP.GG MCP Tools",
                description=self.pages[self.current_page],
                color=nextcord.Color.blue()
            )
            embed.set_footer(text=f"Page {self.current_page + 1} of {self.max_pages}")
            await interaction.response.edit_message(embed=embed, view=self)
    
    @nextcord.ui.button(label="Last ⏭", style=nextcord.ButtonStyle.secondary)
    async def last_page(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.current_page = self.max_pages - 1
        self.update_buttons()
        embed = nextcord.Embed(
            title="OP.GG MCP Tools",
            description=self.pages[self.current_page],
            color=nextcord.Color.blue()
        )
        embed.set_footer(text=f"Page {self.current_page + 1} of {self.max_pages}")
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def on_timeout(self):
        """Disable all buttons when view times out"""
        for item in self.children:
            item.disabled = True


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
        tool_name: Name of the MCP tool to call
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
                        return {"error": result["error"]}
                    return result
                else:
                    response_text = await response.text()
                    return {"error": f"HTTP {response.status}: {response_text}"}
    except Exception as e:
        return {"error": str(e)}


class OpggMcpTest(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(name="mcp_list", description="List all available OP.GG MCP tools", guild_ids=[GUILD_ID])
    async def mcp_list(self, interaction: nextcord.Interaction):
        """List all available OP.GG MCP tools with their parameters"""
        await interaction.response.defer()
        
        tools = await list_opgg_mcp_tools()
        
        if not tools:
            await interaction.followup.send("❌ Failed to retrieve tools from OP.GG MCP server.", ephemeral=True)
            return
        
        # Build tool information list
        tool_list = []
        for tool in tools:
            if isinstance(tool, dict):
                tool_name = tool.get('name', 'Unknown')
                tool_desc = tool.get('description', 'No description')
                
                # Get parameter information
                input_schema = tool.get('inputSchema', {})
                properties = input_schema.get('properties', {}) if isinstance(input_schema, dict) else {}
                required = input_schema.get('required', []) if isinstance(input_schema, dict) else []
                
                param_info = []
                for param_name, param_details in properties.items():
                    param_type = param_details.get('type', 'string')
                    param_desc = param_details.get('description', '')
                    is_required = param_name in required
                    enum_values = param_details.get('enum', [])
                    
                    req_marker = "**REQUIRED**" if is_required else "optional"
                    enum_str = f" (Options: {', '.join(map(str, enum_values))})" if enum_values else ""
                    param_info.append(f"• `{param_name}` ({param_type}) - {req_marker}{enum_str}")
                    if param_desc:
                        param_info[-1] += f"\n  └ {param_desc}"
                
                tool_info = f"**{tool_name}**\n{tool_desc}\n"
                if param_info:
                    tool_info += "\n".join(param_info)
                else:
                    tool_info += "No parameters required"
                
                tool_list.append(tool_info)
        
        # Split into pages (Discord embed description limit is 4096 characters)
        pages = []
        current_page = []
        current_length = 0
        
        # Add header to first page
        header = f"Found {len(tools)} available tools\n\n"
        header_length = len(header)
        
        for tool_info in tool_list:
            tool_length = len(tool_info) + 4  # +4 for separators "\n\n"
            
            # Check if adding this tool would exceed the limit
            if current_length + tool_length + header_length > 3800:  # Leave buffer for safety
                # Save current page
                if current_page:
                    pages.append(header + "\n\n".join(current_page))
                    header = ""  # No header for subsequent pages
                    header_length = 0
                # Start new page
                current_page = [tool_info]
                current_length = tool_length
            else:
                current_page.append(tool_info)
                current_length += tool_length
        
        # Add final page
        if current_page:
            pages.append((header if header else "") + "\n\n".join(current_page))
        
        if not pages:
            pages = ["No tools found"]
        
        # Create pagination view
        view = ToolListPaginationView(pages)
        view.update_buttons()
        
        # Create and send first page
        embed = nextcord.Embed(
            title="OP.GG MCP Tools",
            description=pages[0],
            color=nextcord.Color.blue()
        )
        embed.set_footer(text=f"Page 1 of {len(pages)}")
        
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @nextcord.slash_command(name="mcp_test", description="Test an OP.GG MCP tool", guild_ids=[GUILD_ID])
    async def mcp_test(
        self,
        interaction: nextcord.Interaction,
        tool_name: str = nextcord.SlashOption(
            name="tool_name",
            description="Name of the MCP tool to test (e.g., lol_get_summoner_profile)"
        ),
        parameters: str = nextcord.SlashOption(
            name="parameters",
            description="JSON string of parameters (e.g., {\"game_name\":\"JJ3571\",\"tag_line\":\"NA1\"})",
            required=False
        )
    ):
        """Test an OP.GG MCP tool with specified parameters"""
        await interaction.response.defer()
        
        # Parse parameters JSON
        tool_args = {}
        if parameters:
            try:
                tool_args = json.loads(parameters)
                if not isinstance(tool_args, dict):
                    await interaction.followup.send("❌ Parameters must be a JSON object (dictionary).", ephemeral=True)
                    return
            except json.JSONDecodeError as e:
                await interaction.followup.send(f"❌ Invalid JSON in parameters: {e}", ephemeral=True)
                return
        
        # Call the MCP tool
        result = await call_opgg_mcp_tool(tool_name, tool_args)
        
        # Create response embed
        if result is None:
            embed = nextcord.Embed(
                title="❌ Tool Call Failed",
                description=f"Failed to call tool `{tool_name}`",
                color=nextcord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Format the result
        result_json = json.dumps(result, indent=2, ensure_ascii=False)
        
        # Check if result contains an error
        if "error" in result:
            embed = nextcord.Embed(
                title=f"❌ Error from {tool_name}",
                description=f"```json\n{result_json}\n```",
                color=nextcord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Success - format the response
        # Discord has a 4096 character limit for embed descriptions
        if len(result_json) > 4000:
            # Split into multiple messages
            embed = nextcord.Embed(
                title=f"✅ Success: {tool_name}",
                description=f"**Parameters used:**\n```json\n{json.dumps(tool_args, indent=2)}\n```\n\n**Response (truncated, see below):**",
                color=nextcord.Color.green()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            # Send full response in code block
            chunks = [result_json[i:i+1900] for i in range(0, len(result_json), 1900)]
            for i, chunk in enumerate(chunks):
                await interaction.followup.send(f"```json\n{chunk}\n```", ephemeral=True)
        else:
            embed = nextcord.Embed(
                title=f"✅ Success: {tool_name}",
                description=f"**Parameters used:**\n```json\n{json.dumps(tool_args, indent=2)}\n```\n\n**Response:**\n```json\n{result_json}\n```",
                color=nextcord.Color.green()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        
        print(f"MCP test: {tool_name} called with args {tool_args}")

    @nextcord.slash_command(name="mcp_tool_info", description="Get detailed information about a specific MCP tool", guild_ids=[GUILD_ID])
    async def mcp_tool_info(
        self,
        interaction: nextcord.Interaction,
        tool_name: str = nextcord.SlashOption(
            name="tool_name",
            description="Name of the MCP tool to get info about"
        )
    ):
        """Get detailed information about a specific MCP tool"""
        await interaction.response.defer()
        
        tools = await list_opgg_mcp_tools()
        
        if not tools:
            await interaction.followup.send("❌ Failed to retrieve tools from OP.GG MCP server.", ephemeral=True)
            return
        
        # Find the specific tool
        tool_info = None
        for tool in tools:
            if isinstance(tool, dict) and tool.get('name') == tool_name:
                tool_info = tool
                break
        
        if not tool_info:
            await interaction.followup.send(f"❌ Tool `{tool_name}` not found. Use `/mcp_list` to see available tools.", ephemeral=True)
            return
        
        # Build detailed embed
        embed = nextcord.Embed(
            title=f"Tool: {tool_name}",
            description=tool_info.get('description', 'No description available'),
            color=nextcord.Color.blue()
        )
        
        # Get parameter information
        input_schema = tool_info.get('inputSchema', {})
        properties = input_schema.get('properties', {}) if isinstance(input_schema, dict) else {}
        required = input_schema.get('required', []) if isinstance(input_schema, dict) else []
        
        if properties:
            param_text = []
            for param_name, param_details in properties.items():
                param_type = param_details.get('type', 'string')
                param_desc = param_details.get('description', 'No description')
                is_required = param_name in required
                enum_values = param_details.get('enum', [])
                default_value = param_details.get('default')
                
                req_marker = "**REQUIRED**" if is_required else "Optional"
                param_line = f"**{param_name}** ({param_type}) - {req_marker}\n{param_desc}"
                
                if enum_values:
                    param_line += f"\nValid values: `{', '.join(map(str, enum_values))}`"
                if default_value is not None:
                    param_line += f"\nDefault: `{default_value}`"
                
                param_text.append(param_line)
            
            embed.add_field(
                name="Parameters",
                value="\n\n".join(param_text),
                inline=False
            )
        else:
            embed.add_field(
                name="Parameters",
                value="No parameters required",
                inline=False
            )
        
        # Example usage
        example_params = {}
        for param_name, param_details in properties.items():
            if param_name in required:
                param_type = param_details.get('type', 'string')
                enum_values = param_details.get('enum', [])
                if enum_values:
                    example_params[param_name] = enum_values[0]
                elif param_type == 'string':
                    example_params[param_name] = "example_value"
                elif param_type == 'number':
                    example_params[param_name] = 0
                elif param_type == 'boolean':
                    example_params[param_name] = False
        
        if example_params:
            embed.add_field(
                name="Example Parameters",
                value=f"```json\n{json.dumps(example_params, indent=2)}\n```",
                inline=False
            )
        
        await interaction.followup.send(embed=embed, ephemeral=True)


def setup(bot):
    bot.add_cog(OpggMcpTest(bot))
    print("OpggMcpTest cog has been added to the bot.")

