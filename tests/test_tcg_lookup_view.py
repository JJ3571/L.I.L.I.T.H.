"""Card and set menus stay checked and keep working after a restart."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from main_bot.cogs.production.tcg import (
    TCG,
    TCG_CARD_SELECT_ID,
    TCG_SET_NEXT_ID,
    TCG_SET_PREV_ID,
    TCG_SET_SELECT_ID,
    TCGLookupView,
    card_select_options,
    lookup_view,
    option_page,
    options_from_message,
    page_containing,
    set_select_options,
    with_selection,
)


class _Opt:
    def __init__(self, label, value, description=None, emoji=None, default=False):
        self.label = label
        self.value = value
        self.description = description
        self.emoji = emoji
        self.default = default


class _Menu:
    def __init__(self, custom_id, options):
        self.custom_id = custom_id
        self.options = options


class _Row:
    def __init__(self, *children):
        self.children = list(children)


def _bolt(**extra):
    card = {
        "name": "Lightning Bolt",
        "id": "lea",
        "oracle_text": "Deal 3 damage to any target.",
        "mana_cost": "{R}",
        "type_line": "Instant",
        "set_name": "Limited Edition Alpha",
    }
    card.update(extra)
    return card


def _printings():
    return [
        {
            "id": "lea",
            "set_name": "Limited Edition Alpha",
            "set": "lea",
            "collector_number": "161",
        },
        {
            "id": "2ed",
            "set_name": "Unlimited Edition",
            "set": "2ed",
            "collector_number": "162",
        },
    ]


def _message(*rows):
    message = MagicMock()
    message.components = list(rows)
    message.embeds = []
    return message


def _interaction(message, values):
    interaction = MagicMock()
    interaction.data = {"values": values}
    interaction.message = message
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.edit_original_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def test_with_selection_checks_only_the_chosen_option():
    options = card_select_options(["Lightning Bolt", "Lightning Strike"])
    marked = with_selection(options, "Lightning Strike")

    assert [opt.default for opt in options] == [False, False]
    assert [(opt.value, opt.default) for opt in marked] == [
        ("Lightning Bolt", False),
        ("Lightning Strike", True),
    ]


def test_set_menu_pages_keep_every_printing_within_twenty_five():
    printings = [
        {"id": f"id-{i}", "set_name": f"Set {i}", "set": "x", "collector_number": str(i)}
        for i in range(40)
    ]
    options = set_select_options(printings)
    page = page_containing(options, "id-30")
    shown, current, pages = option_page(options, page)

    assert len(options) == 40
    assert current == 1
    assert pages == 2
    assert len(shown) == 15
    assert [opt.value for opt in shown][0] == "id-25"
    assert any(opt.value == "id-30" for opt in shown)


def test_option_page_leaves_short_lists_alone():
    options = card_select_options(["Bolt"])
    shown, page, pages = option_page(options, 0)
    assert shown == options
    assert page == 0
    assert pages == 1


def test_options_from_message_reads_the_matching_menu():
    message = _message(
        _Row(_Menu("other", [_Opt("Ignore", "ignore")])),
        _Row(
            _Menu(
                TCG_SET_SELECT_ID,
                [_Opt("Limited Edition Alpha", "lea", description="LEA #161", default=True)],
            )
        ),
    )

    options = options_from_message(message, TCG_SET_SELECT_ID)

    assert [(opt.value, opt.default, opt.description) for opt in options] == [
        ("lea", True, "LEA #161")
    ]
    assert options_from_message(None, TCG_CARD_SELECT_ID) == []


async def test_lookup_view_does_not_expire():
    view = lookup_view(
        MagicMock(),
        card_options=card_select_options(["Lightning Bolt", "Lightning Strike"]),
        selected_card="Lightning Bolt",
        set_options=set_select_options(_printings()),
        selected_set="lea",
    )

    assert isinstance(view, TCGLookupView)
    assert view.timeout is None
    assert view.prevent_update is False
    assert view.is_persistent()
    assert [child.custom_id for child in view.children] == [
        TCG_CARD_SELECT_ID,
        TCG_SET_SELECT_ID,
    ]
    card_menu, set_menu = view.children
    assert card_menu.placeholder == "Lightning Bolt"
    assert [opt.value for opt in card_menu.options if opt.default] == ["Lightning Bolt"]
    assert [opt.value for opt in set_menu.options if opt.default] == ["lea"]


async def test_single_card_keeps_the_set_menu_on_the_shown_printing():
    cog = TCG.__new__(TCG)
    cog.get_card_data = MagicMock(return_value=_bolt())
    cog.get_card_sets = MagicMock(return_value=_printings())

    embed, view = cog._build_card_message("Lightning Bolt")

    assert embed.title == "Lightning Bolt"
    assert [child.custom_id for child in view.children] == [TCG_SET_SELECT_ID]
    assert [opt.value for opt in view.children[0].options if opt.default] == ["lea"]


async def test_card_select_checks_the_choice_from_the_message():
    cog = TCG.__new__(TCG)
    cog._persistent_views = []
    cog.bot = MagicMock()
    cog.get_card_data = MagicMock(return_value=_bolt())
    cog.get_card_sets = MagicMock(return_value=_printings())
    cog.register_persistent_views()
    card_select = next(
        child for child in cog._persistent_views[0].children if child.custom_id == TCG_CARD_SELECT_ID
    )
    interaction = _interaction(
        _message(
            _Row(
                _Menu(
                    TCG_CARD_SELECT_ID,
                    [
                        _Opt("Lightning Bolt", "Lightning Bolt"),
                        _Opt("Lightning Strike", "Lightning Strike"),
                    ],
                )
            )
        ),
        ["Lightning Bolt"],
    )

    await card_select.callback(interaction)

    sent = interaction.edit_original_message.await_args.kwargs
    assert sent["content"] is None
    card_menu = next(child for child in sent["view"].children if child.custom_id == TCG_CARD_SELECT_ID)
    set_menu = next(child for child in sent["view"].children if child.custom_id == TCG_SET_SELECT_ID)
    assert [opt.value for opt in card_menu.options if opt.default] == ["Lightning Bolt"]
    assert [opt.value for opt in card_menu.options] == ["Lightning Bolt", "Lightning Strike"]
    assert card_menu.placeholder == "Lightning Bolt"
    assert [opt.value for opt in set_menu.options if opt.default] == ["lea"]
    assert [opt.value for opt in cog._persistent_views[0].children[0].options] == ["card"]


async def test_set_select_keeps_the_card_checkmark():
    cog = TCG.__new__(TCG)
    cog._persistent_views = []
    cog.bot = MagicMock()
    shown = _bolt(id="2ed", set_name="Unlimited Edition")
    cog.get_card_data_by_set = MagicMock(return_value=shown)
    cog.get_card_data = MagicMock(return_value=shown)
    cog.get_card_sets = MagicMock(return_value=_printings())
    cog.register_persistent_views()
    set_select = next(
        child for child in cog._persistent_views[0].children if child.custom_id == TCG_SET_SELECT_ID
    )
    interaction = _interaction(
        _message(
            _Row(
                _Menu(
                    TCG_CARD_SELECT_ID,
                    [
                        _Opt("Lightning Bolt", "Lightning Bolt", default=True),
                        _Opt("Lightning Strike", "Lightning Strike"),
                    ],
                )
            ),
            _Row(
                _Menu(
                    TCG_SET_SELECT_ID,
                    [
                        _Opt("Limited Edition Alpha", "lea", default=True),
                        _Opt("Unlimited Edition", "2ed"),
                    ],
                )
            ),
        ),
        ["2ed"],
    )

    await set_select.callback(interaction)

    sent = interaction.edit_original_message.await_args.kwargs
    assert sent["embed"].footer.text == "Set: Unlimited Edition"
    card_menu = next(child for child in sent["view"].children if child.custom_id == TCG_CARD_SELECT_ID)
    set_menu = next(child for child in sent["view"].children if child.custom_id == TCG_SET_SELECT_ID)
    assert [opt.value for opt in card_menu.options if opt.default] == ["Lightning Bolt"]
    assert [opt.value for opt in set_menu.options if opt.default] == ["2ed"]
    assert set_menu.placeholder == "Unlimited Edition"


async def test_extra_printings_stay_on_the_card_embed():
    cog = TCG.__new__(TCG)
    printings = [
        {"id": f"id-{i}", "set_name": f"Set {i}", "set": "s", "collector_number": str(i)}
        for i in range(40)
    ]
    cog.get_card_data = MagicMock(return_value=_bolt(id="id-0", set_name="Set 0"))
    cog.get_card_sets = MagicMock(return_value=printings)

    embed, view = cog._build_card_message(
        "Lightning Bolt",
        card_options=card_select_options(["Lightning Bolt", "Lightning Strike"]),
    )

    assert [child.custom_id for child in view.children[:2]] == [
        TCG_CARD_SELECT_ID,
        TCG_SET_SELECT_ID,
    ]
    assert TCG_SET_PREV_ID in [child.custom_id for child in view.children]
    assert TCG_SET_NEXT_ID in [child.custom_id for child in view.children]
    set_menu = next(child for child in view.children if child.custom_id == TCG_SET_SELECT_ID)
    assert len(set_menu.options) == 25
    assert [opt.value for opt in set_menu.options if opt.default] == ["id-0"]
    assert embed.footer.text == "Set: Set 0\nPrintings 1-25 of 40"
    assert view.timeout is None
    assert view.is_persistent()
    prev = next(child for child in view.children if child.custom_id == TCG_SET_PREV_ID)
    nxt = next(child for child in view.children if child.custom_id == TCG_SET_NEXT_ID)
    assert prev.disabled
    assert not nxt.disabled


async def test_next_page_keeps_both_menus_on_the_same_embed():
    cog = TCG.__new__(TCG)
    printings = [
        {"id": f"id-{i}", "set_name": f"Set {i}", "set": "s", "collector_number": str(i)}
        for i in range(40)
    ]
    shown = _bolt(id="id-0", set_name="Set 0")
    cog.get_card_data = MagicMock(return_value=shown)
    cog.get_card_sets = MagicMock(return_value=printings)
    cog.get_card_data_by_set = MagicMock(return_value=shown)
    current = MagicMock()
    current.title = "Lightning Bolt"
    current.footer.text = "Set: Set 0\nPrintings 1-25 of 40"
    message = _message(
        _Row(
            _Menu(
                TCG_CARD_SELECT_ID,
                [
                    _Opt("Lightning Bolt", "Lightning Bolt", default=True),
                    _Opt("Lightning Strike", "Lightning Strike"),
                ],
            )
        ),
        _Row(_Menu(TCG_SET_SELECT_ID, [_Opt("Set 0", "id-0", default=True)])),
    )
    message.embeds = [current]
    interaction = _interaction(message, [])

    await cog.on_set_page(interaction, 1)

    sent = interaction.edit_original_message.await_args.kwargs
    assert sent["embed"].title == "Lightning Bolt"
    assert sent["embed"].footer.text == "Set: Set 0\nPrintings 26-40 of 40"
    card_menu = next(child for child in sent["view"].children if child.custom_id == TCG_CARD_SELECT_ID)
    set_menu = next(child for child in sent["view"].children if child.custom_id == TCG_SET_SELECT_ID)
    assert [opt.value for opt in card_menu.options if opt.default] == ["Lightning Bolt"]
    assert set_menu.options[0].value == "id-25"
    assert len(set_menu.options) == 15
    nxt = next(child for child in sent["view"].children if child.custom_id == TCG_SET_NEXT_ID)
    assert nxt.disabled


async def test_unknown_card_leaves_the_menu_alone():
    cog = TCG.__new__(TCG)
    cog.get_card_data = MagicMock(return_value=None)
    interaction = _interaction(
        _message(_Row(_Menu(TCG_CARD_SELECT_ID, [_Opt("Nope", "Nope")]))),
        ["Nope"],
    )

    await cog.on_card_selected(interaction, "Nope")

    interaction.edit_original_message.assert_not_awaited()
    interaction.followup.send.assert_awaited()


async def test_unload_drops_the_registered_view():
    cog = TCG.__new__(TCG)
    cog.bot = MagicMock()
    cog._persistent_views = []
    cog._autolink_session = None
    cog.register_persistent_views()

    cog.cog_unload()

    cog.bot.remove_view.assert_called_once()
    assert cog._persistent_views == []
