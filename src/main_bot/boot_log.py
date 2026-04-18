"""Stdout prefix for lines emitted while extensions load (see ``main_bot.main``)."""

BOT_STARTING = "[BOT_STARTING]"


def boot_print(message: str) -> None:
    print(f"{BOT_STARTING} {message}")
