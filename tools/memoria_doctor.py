#!/usr/bin/env python3
import os
import sys
import traceback


PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


from doctor.manager import DoctorManager


def main() -> int:
    """
    Fuehrt den MEMORIA Doctor aus.

    Dieses Skript ist fuer Benutzer und Support gedacht.
    Es gibt einen technischen Diagnosebericht aus,
    ohne private Chats, Tokens oder Personas zu lesen.
    """

    try:
        report = DoctorManager().run_report()
        print(report)
        return 0

    except Exception as e:
        print("=== MEMORIA DOCTOR ERROR ===")
        print("")
        print("MEMORIA Doctor konnte nicht erfolgreich ausgefuehrt werden.")
        print("")
        print("Fehler:")
        print(str(e))
        print("")
        print("Technische Details:")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
