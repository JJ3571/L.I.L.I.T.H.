"""
Production cog suite — everything under ``main_bot.cogs.production``.

What we assert:

- Every ``*.py`` file (except ``__init__.py``) is importable and exports a ``setup`` callable.
- Each module defines at least one ``commands.Cog`` subclass that belongs to that module.
- Every slash command and subcommand registered on those classes has Discord-safe metadata
  (name length, non-empty description, async callback) and sane option descriptions.
- Root-level slash command names are unique within each cog class (catches copy-paste collisions).

Deep per-cog behavior stays in focused tests (e.g. ``test_counter_cog.py``).
"""

from __future__ import annotations

import importlib
import inspect
import re
from pathlib import Path

import pytest
from nextcord.application_command import SlashApplicationCommand, SlashApplicationSubcommand
from nextcord.ext import commands

from main_bot.main import COGS_ROOT
from main_bot.paths import PROJECT_ROOT

_SLASH_TYPES = (SlashApplicationCommand, SlashApplicationSubcommand)

# Discord application command name rules (chat input commands); see API docs.
_COMMAND_NAME_RE = re.compile(r"^[-_a-z0-9]{1,32}$", re.ASCII)


def _production_stems_from_disk() -> list[str]:
    prod_dir = PROJECT_ROOT / "src" / "main_bot" / "cogs" / "production"
    stems = sorted(p.stem for p in prod_dir.glob("*.py") if p.name != "__init__.py")
    return stems


PRODUCTION_COG_STEMS = _production_stems_from_disk()


def _iter_cog_classes(module):
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if not issubclass(obj, commands.Cog) or obj is commands.Cog:
            continue
        if getattr(obj, "__module__", None) != module.__name__:
            continue
        yield obj


def _iter_slash_members(cog_cls: type):
    for attr_name, attr in inspect.getmembers(cog_cls):
        if isinstance(attr, _SLASH_TYPES):
            yield attr_name, attr


def _slash_violations(module_stem: str, cog_cls: type) -> list[str]:
    violations: list[str] = []
    root_names: list[str] = []

    for attr_name, cmd in _iter_slash_members(cog_cls):
        name = getattr(cmd, "name", None)
        if not isinstance(name, str) or not name:
            violations.append(
                f"{module_stem}.{cog_cls.__name__}.{attr_name}: invalid or missing command name {name!r}"
            )
            continue
        if not _COMMAND_NAME_RE.match(name):
            violations.append(
                f"{module_stem}.{cog_cls.__name__}.{attr_name}: command name {name!r} "
                "must match [-_a-z0-9] and length 1..32"
            )
        if isinstance(cmd, SlashApplicationCommand):
            root_names.append(name)

        desc = getattr(cmd, "description", None)
        if not isinstance(desc, str) or not desc.strip():
            violations.append(
                f"{module_stem}.{cog_cls.__name__}.{attr_name} ({name!r}): "
                "description must be a non-empty string"
            )

        cb = getattr(cmd, "callback", None)
        if cb is None or not inspect.iscoroutinefunction(cb):
            violations.append(
                f"{module_stem}.{cog_cls.__name__}.{attr_name} ({name!r}): "
                "callback must be an async function"
            )

        options = getattr(cmd, "options", None) or {}
        for opt_key, opt in options.items():
            odesc = getattr(opt, "description", None)
            if not isinstance(odesc, str) or not odesc.strip():
                violations.append(
                    f"{module_stem}.{cog_cls.__name__}.{attr_name} ({name!r}) "
                    f"option {opt_key!r}: description must be a non-empty string"
                )

    if len(root_names) != len(set(root_names)):
        violations.append(
            f"{module_stem}.{cog_cls.__name__}: duplicate root slash command names: {root_names!r}"
        )

    return violations


def test_production_stems_match_load_extensions_glob() -> None:
    """Same file discovery rule as ``load_extensions``: ``COGS_ROOT / 'production'``."""
    expected = sorted(
        p.stem for p in (COGS_ROOT / "production").glob("*.py") if p.name != "__init__.py"
    )
    assert PRODUCTION_COG_STEMS == expected, (
        "Production cog list drifted from main.COGS_ROOT/production. "
        f"disk={PRODUCTION_COG_STEMS!r} main={expected!r}"
    )


@pytest.mark.parametrize("stem", PRODUCTION_COG_STEMS)
def test_production_module_imports(stem: str) -> None:
    importlib.import_module(f"main_bot.cogs.production.{stem}")


@pytest.mark.parametrize("stem", PRODUCTION_COG_STEMS)
def test_production_module_defines_setup(stem: str) -> None:
    mod = importlib.import_module(f"main_bot.cogs.production.{stem}")
    setup_fn = getattr(mod, "setup", None)
    assert callable(setup_fn), f"{stem}: module must define callable setup(bot)"


@pytest.mark.parametrize("stem", PRODUCTION_COG_STEMS)
def test_production_module_has_local_cog_class(stem: str) -> None:
    mod = importlib.import_module(f"main_bot.cogs.production.{stem}")
    cogs = list(_iter_cog_classes(mod))
    assert cogs, f"{stem}: expected at least one commands.Cog subclass defined in this module"


@pytest.mark.parametrize("stem", PRODUCTION_COG_STEMS)
def test_production_slash_command_contract(stem: str) -> None:
    mod = importlib.import_module(f"main_bot.cogs.production.{stem}")
    all_violations: list[str] = []
    for cls in _iter_cog_classes(mod):
        all_violations.extend(_slash_violations(stem, cls))
    assert not all_violations, "Slash command contract violations:\n" + "\n".join(all_violations)


@pytest.mark.parametrize("stem", PRODUCTION_COG_STEMS)
def test_production_cog_exposes_at_least_one_slash_command(stem: str) -> None:
    """Every production extension currently registers slash commands; catch accidental removals."""
    mod = importlib.import_module(f"main_bot.cogs.production.{stem}")
    count = 0
    for cls in _iter_cog_classes(mod):
        for _, cmd in _iter_slash_members(cls):
            if isinstance(cmd, SlashApplicationCommand):
                count += 1
    assert count >= 1, f"{stem}: expected at least one root @slash_command on a production Cog"
