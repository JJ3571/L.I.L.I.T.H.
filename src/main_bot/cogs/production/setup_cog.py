"""Prefix ``.setup`` hub for guild-scoped settings (not a slash command)."""

from __future__ import annotations

import logging
from typing import List, Optional

import nextcord
from nextcord.ext import commands

from main_bot.cog_log_mixin import CogLogMixin
from main_bot.guild_settings import (
    FEATURE_GROUPS,
    GROUP_KEYS,
    SETTING_BY_KEY,
    clear_setting,
    get_settings,
    import_env_into_db,
    is_bot_admin,
    set_group_skipped,
    set_setting,
)
from main_bot.server_configs.config import GUILD_ID

logger = logging.getLogger(__name__)

STATUS_EMOJI = {
    "configured": "OK",
    "missing": "MISSING",
    "skipped": "SKIPPED",
}


def _pool(bot: commands.Bot):
    return bot.pg_pool


def _deny(interaction_or_ctx) -> str:
    return "You do not have permission to use this command."


class SetupHubView(nextcord.ui.View):
    def __init__(self, bot: commands.Bot, author_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.author_id = author_id
        options = [
            nextcord.SelectOption(
                label=label[:100],
                value=group,
                description=f"Status: {get_settings().group_status(group)}"[:100],
            )
            for group, label in FEATURE_GROUPS
        ]
        select = nextcord.ui.Select(
            placeholder="Choose a feature group…",
            options=options,
            custom_id="setup_group_select",
        )
        select.callback = self._on_group
        self.add_item(select)

        for label, custom_id, style in (
            ("Import from env", "setup_import_env", nextcord.ButtonStyle.secondary),
            ("Show all", "setup_show", nextcord.ButtonStyle.secondary),
            ("Refresh", "setup_refresh", nextcord.ButtonStyle.primary),
        ):
            btn = nextcord.ui.Button(label=label, style=style, custom_id=custom_id)
            btn.callback = self._button_callback
            self.add_item(btn)

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the user who ran `.setup` can use these controls.", ephemeral=True
            )
            return False
        member = interaction.user
        if isinstance(member, nextcord.Member) and is_bot_admin(member):
            return True
        await interaction.response.send_message(_deny(interaction), ephemeral=True)
        return False

    async def _on_group(self, interaction: nextcord.Interaction) -> None:
        group = interaction.data["values"][0]  # type: ignore[index]
        await interaction.response.edit_message(
            embed=_group_embed(group),
            view=SetupGroupView(self.bot, self.author_id, group),
        )

    async def _button_callback(self, interaction: nextcord.Interaction) -> None:
        cid = interaction.data.get("custom_id") if interaction.data else None
        if cid == "setup_import_env":
            settings, written = await import_env_into_db(
                _pool(self.bot), guild_id=GUILD_ID, updated_by=interaction.user.id
            )
            desc = (
                f"Imported **{len(written)}** non-default env keys into the database.\n"
                + (", ".join(f"`{k}`" for k in written) if written else "(nothing to import)")
            )
            await interaction.response.send_message(desc[:1900], ephemeral=True)
            await interaction.message.edit(embed=_hub_embed(), view=SetupHubView(self.bot, self.author_id))
            return
        if cid == "setup_show":
            await interaction.response.send_message(embed=_hub_embed(detailed=True), ephemeral=True)
            return
        if cid == "setup_refresh":
            await interaction.response.edit_message(
                embed=_hub_embed(), view=SetupHubView(self.bot, self.author_id)
            )


class SetupGroupView(nextcord.ui.View):
    def __init__(self, bot: commands.Bot, author_id: int, group: str):
        super().__init__(timeout=300)
        self.bot = bot
        self.author_id = author_id
        self.group = group

        if group == "roles":
            role_select = nextcord.ui.RoleSelect(
                placeholder="Select bot-admin roles (optional)…",
                min_values=0,
                max_values=10,
                custom_id="setup_role_select",
            )
            role_select.callback = self._on_roles
            self.add_item(role_select)
        else:
            channel_keys = [
                k
                for k in GROUP_KEYS.get(group, [])
                if SETTING_BY_KEY[k].value_type == "int"
                and ("channel" in k or "category" in k)
            ]
            if channel_keys:
                ch_select = nextcord.ui.ChannelSelect(
                    placeholder="Pick a channel/category, then choose which key…",
                    min_values=1,
                    max_values=1,
                    custom_id="setup_channel_pick",
                )
                ch_select.callback = self._on_channel_picked
                self.add_item(ch_select)
                key_options = [
                    nextcord.SelectOption(
                        label=(SETTING_BY_KEY[k].label or k)[:100],
                        value=k,
                    )
                    for k in channel_keys
                ]
                if key_options:
                    key_select = nextcord.ui.Select(
                        placeholder="Assign picked channel to key…",
                        options=key_options[:25],
                        custom_id="setup_channel_key",
                    )
                    key_select.callback = self._on_channel_key
                    self.add_item(key_select)
                    self._pending_channel_id: Optional[int] = None

            role_keys = [
                k
                for k in GROUP_KEYS.get(group, [])
                if SETTING_BY_KEY[k].value_type == "int" and "role" in k
            ]
            if role_keys:
                rsel = nextcord.ui.RoleSelect(
                    placeholder="Pick a role…",
                    min_values=1,
                    max_values=1,
                    custom_id="setup_single_role",
                )
                rsel.callback = self._on_single_role
                self.add_item(rsel)
                self._role_key = role_keys[0]

        for label, custom_id, style in (
            ("Skip group", "setup_skip", nextcord.ButtonStyle.danger),
            ("Unskip", "setup_unskip", nextcord.ButtonStyle.secondary),
            ("Clear group keys", "setup_clear_group", nextcord.ButtonStyle.secondary),
            ("Back", "setup_back", nextcord.ButtonStyle.primary),
        ):
            btn = nextcord.ui.Button(label=label, style=style, custom_id=custom_id)
            btn.callback = self._button
            self.add_item(btn)

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the user who ran `.setup` can use these controls.", ephemeral=True
            )
            return False
        member = interaction.user
        if isinstance(member, nextcord.Member) and is_bot_admin(member):
            return True
        await interaction.response.send_message(_deny(interaction), ephemeral=True)
        return False

    async def _on_roles(self, interaction: nextcord.Interaction) -> None:
        roles = interaction.data.get("values") if interaction.data else []  # type: ignore[union-attr]
        # RoleSelect returns role objects via resolved; values are IDs as strings
        role_ids = [int(r) for r in (roles or [])]
        await set_setting(
            _pool(self.bot),
            "bot_admin_role_ids",
            role_ids,
            guild_id=GUILD_ID,
            updated_by=interaction.user.id,
        )
        await set_group_skipped(
            _pool(self.bot),
            self.group,
            False,
            guild_id=GUILD_ID,
            updated_by=interaction.user.id,
        )
        await interaction.response.edit_message(
            embed=_group_embed(self.group),
            view=SetupGroupView(self.bot, self.author_id, self.group),
        )

    async def _on_channel_picked(self, interaction: nextcord.Interaction) -> None:
        values = interaction.data.get("values") if interaction.data else []
        if not values:
            await interaction.response.send_message("No channel selected.", ephemeral=True)
            return
        self._pending_channel_id = int(values[0])
        await interaction.response.send_message(
            f"Selected channel/category `{self._pending_channel_id}`. "
            f"Now choose which setting key to assign it to.",
            ephemeral=True,
        )

    async def _on_channel_key(self, interaction: nextcord.Interaction) -> None:
        if not getattr(self, "_pending_channel_id", None):
            await interaction.response.send_message(
                "Pick a channel/category first, then choose the key.", ephemeral=True
            )
            return
        key = interaction.data["values"][0]  # type: ignore[index]
        await set_setting(
            _pool(self.bot),
            key,
            self._pending_channel_id,
            guild_id=GUILD_ID,
            updated_by=interaction.user.id,
        )
        await set_group_skipped(
            _pool(self.bot), self.group, False, guild_id=GUILD_ID, updated_by=interaction.user.id
        )
        self._pending_channel_id = None
        await interaction.response.edit_message(
            embed=_group_embed(self.group),
            view=SetupGroupView(self.bot, self.author_id, self.group),
        )

    async def _on_single_role(self, interaction: nextcord.Interaction) -> None:
        values = interaction.data.get("values") if interaction.data else []
        if not values:
            await interaction.response.send_message("No role selected.", ephemeral=True)
            return
        key = getattr(self, "_role_key", None)
        if not key:
            await interaction.response.send_message("No role key for this group.", ephemeral=True)
            return
        await set_setting(
            _pool(self.bot),
            key,
            int(values[0]),
            guild_id=GUILD_ID,
            updated_by=interaction.user.id,
        )
        await set_group_skipped(
            _pool(self.bot), self.group, False, guild_id=GUILD_ID, updated_by=interaction.user.id
        )
        await interaction.response.edit_message(
            embed=_group_embed(self.group),
            view=SetupGroupView(self.bot, self.author_id, self.group),
        )

    async def _button(self, interaction: nextcord.Interaction) -> None:
        cid = interaction.data.get("custom_id") if interaction.data else None
        pool = _pool(self.bot)
        uid = interaction.user.id
        if cid == "setup_back":
            await interaction.response.edit_message(
                embed=_hub_embed(), view=SetupHubView(self.bot, self.author_id)
            )
            return
        if cid == "setup_skip":
            await set_group_skipped(pool, self.group, True, guild_id=GUILD_ID, updated_by=uid)
            await interaction.response.edit_message(
                embed=_group_embed(self.group),
                view=SetupGroupView(self.bot, self.author_id, self.group),
            )
            return
        if cid == "setup_unskip":
            await set_group_skipped(pool, self.group, False, guild_id=GUILD_ID, updated_by=uid)
            await interaction.response.edit_message(
                embed=_group_embed(self.group),
                view=SetupGroupView(self.bot, self.author_id, self.group),
            )
            return
        if cid == "setup_clear_group":
            for key in GROUP_KEYS.get(self.group, []):
                await clear_setting(pool, key, guild_id=GUILD_ID, updated_by=uid)
            await interaction.response.edit_message(
                embed=_group_embed(self.group),
                view=SetupGroupView(self.bot, self.author_id, self.group),
            )


def _hub_embed(*, detailed: bool = False) -> nextcord.Embed:
    settings = get_settings()
    embed = nextcord.Embed(
        title="Guild setup",
        description=(
            "Configure guild knobs stored in Postgres. Secrets stay in `.env` / Doppler.\n"
            "Use **Import from env** once to copy non-default channel/emoji IDs from the process environment."
        ),
        color=0x5865F2,
    )
    lines: List[str] = []
    for group, label in FEATURE_GROUPS:
        status = settings.group_status(group)
        lines.append(f"**{label}** — `{STATUS_EMOJI.get(status, status)}`")
        if detailed:
            for key in GROUP_KEYS.get(group, []):
                defn = SETTING_BY_KEY[key]
                if settings.has(key):
                    lines.append(f"  • `{key}` = `{settings.get(key)!r}`")
                else:
                    lines.append(f"  • `{key}` unset (default `{defn.default!r}`)")
    embed.add_field(name="Feature groups", value="\n".join(lines)[:1024], inline=False)
    return embed


def _group_embed(group: str) -> nextcord.Embed:
    settings = get_settings()
    label = dict(FEATURE_GROUPS).get(group, group)
    status = settings.group_status(group)
    embed = nextcord.Embed(
        title=f"Setup — {label}",
        description=f"Status: **{status}**",
        color=0x5865F2,
    )
    for key in GROUP_KEYS.get(group, []):
        defn = SETTING_BY_KEY[key]
        val = settings.get(key) if settings.has(key) else f"(unset → {defn.default!r})"
        embed.add_field(
            name=defn.label or key,
            value=f"`{key}` = `{val}`",
            inline=False,
        )
    if group == "roles":
        embed.set_footer(
            text="Leave empty to rely on Discord Administrator only. "
            "Selected roles get bot-admin without full Administrator."
        )
    return embed


class SetupCog(commands.Cog, CogLogMixin):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="setup")
    async def setup_cmd(self, ctx: commands.Context, action: Optional[str] = None) -> None:
        if ctx.guild is None or ctx.guild.id != GUILD_ID:
            await ctx.send("This command only works in the configured guild.")
            return
        member = ctx.author
        if not isinstance(member, nextcord.Member) or not is_bot_admin(member):
            await ctx.send(_deny(ctx))
            return

        if action and action.lower() in ("import-env", "import_env", "import"):
            _, written = await import_env_into_db(
                _pool(self.bot), guild_id=GUILD_ID, updated_by=member.id
            )
            await ctx.send(
                f"Imported {len(written)} keys from env: "
                + (", ".join(f"`{k}`" for k in written) if written else "(none)")
            )
            return

        if action and action.lower() == "show":
            await ctx.send(embed=_hub_embed(detailed=True))
            return

        view = SetupHubView(self.bot, member.id)
        await ctx.send(embed=_hub_embed(), view=view)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(SetupCog(bot))
