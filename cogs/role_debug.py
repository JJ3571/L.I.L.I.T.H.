import nextcord
from nextcord.ext import commands

from server_configs.cogs_config import admin_user_ids, birthday_channel_id, birthday_role_id

class Role_Debug(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(name="add_birthday_role", description="Add the birthday role to a user")
    async def add_birthday_role(self, interaction: nextcord.Interaction, user: nextcord.Member):
        role = interaction.guild.get_role(birthday_role_id)
        if role:
            try:
                await user.add_roles(role)
                print(f"Added birthday role to {user.display_name}")
                await interaction.response.send_message(f"Added birthday role to {user.mention}", ephemeral=True)
            except nextcord.Forbidden:
                print(f"Failed to add birthday role to {user.display_name}: Missing permissions")
                await interaction.response.send_message(f"Failed to add birthday role to {user.mention}: Missing permissions", ephemeral=True)
            except nextcord.HTTPException as e:
                print(f"Failed to add birthday role to {user.display_name}: {e}")
                await interaction.response.send_message(f"Failed to add birthday role to {user.mention}: {e}", ephemeral=True)
        else:
            print("Birthday role not found")
            await interaction.response.send_message("Birthday role not found", ephemeral=True)

    @nextcord.slash_command(name="remove_birthday_role", description="Remove the birthday role from a user")
    async def remove_birthday_role(self, interaction: nextcord.Interaction, user: nextcord.Member):
        role = interaction.guild.get_role(birthday_role_id)
        if role:
            try:
                await user.remove_roles(role)
                print(f"Removed birthday role from {user.display_name}")
                await interaction.response.send_message(f"Removed birthday role from {user.mention}", ephemeral=True)
            except nextcord.Forbidden:
                print(f"Failed to remove birthday role from {user.display_name}: Missing permissions")
                await interaction.response.send_message(f"Failed to remove birthday role from {user.mention}: Missing permissions", ephemeral=True)
            except nextcord.HTTPException as e:
                print(f"Failed to remove birthday role from {user.display_name}: {e}")
                await interaction.response.send_message(f"Failed to remove birthday role from {user.mention}: {e}", ephemeral=True)
        else:
            print("Birthday role not found")
            await interaction.response.send_message("Birthday role not found", ephemeral=True)


def setup(bot):
    bot.add_cog(Role_Debug(bot))
    print("DebugCog has been added to the bot.")