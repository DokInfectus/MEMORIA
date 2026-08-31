from ui.terminal.theme import TerminalTheme


def divider() -> None:
    print(TerminalTheme.green("-" * 72))


def banner(title: str) -> None:
    divider()
    print(TerminalTheme.green(TerminalTheme.bold(title)))
    divider()


def section(title: str) -> None:
    print("")
    print(TerminalTheme.green(f"## {title}"))
    print(TerminalTheme.dim("-" * 40))


def status(label: str, value: str, ok: bool = None) -> None:
    if ok is True:
        marker = TerminalTheme.green("OK")
    elif ok is False:
        marker = TerminalTheme.red("FAIL")
    else:
        marker = TerminalTheme.yellow("INFO")

    print(f"{marker}  {label}: {value}")


def note(text: str) -> None:
    print(TerminalTheme.dim(text))
