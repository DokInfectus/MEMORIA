def ask_text(label: str, default: str = "") -> str:
    if default:
        value = input(f"{label} [{default}]: ").strip()
        return value or default

    return input(f"{label}: ").strip()


def ask_yes_no(label: str, default: bool = False) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"

    value = input(f"{label} {suffix}: ").strip().lower()

    if not value:
        return default

    return value in {"y", "yes", "j", "ja"}


def ask_choice(title: str, options: list, default: int = 1) -> int:
    print("")
    print(title)

    for index, option in enumerate(options, start=1):
        print(f"{index}) {option}")

    value = input(f"Select [{default}]: ").strip()

    if not value:
        return default

    try:
        choice = int(value)
    except ValueError:
        return default

    if choice < 1 or choice > len(options):
        return default

    return choice
