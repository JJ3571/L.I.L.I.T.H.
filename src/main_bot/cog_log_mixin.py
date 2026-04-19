"""Mixin adding ``cog_print`` for ``[ClassName] message`` terminal lines from cogs."""


def cog_console_line(source_name: str, message: str) -> None:
    """For module-level helpers or UI classes that are not a ``commands.Cog`` instance."""
    print(f"[{source_name}] {message}")


class CogLogMixin:
    def cog_print(self, message: str) -> None:
        print(f"[{self.__class__.__name__}] {message}")
