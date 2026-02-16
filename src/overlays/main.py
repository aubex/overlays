import platform
import sys
from importlib.metadata import version


def cross_platform_helper():
    if "--version" in sys.argv or "-v" in sys.argv:
        print(f"overlays {version('overlays')}")
        return

    if platform.system() != "Windows":
        print("❌ Error: This application is designed to run on Windows only.")
        exit(1)

    from overlays.manager import main

    main()


if __name__ == "__main__":
    cross_platform_helper()
