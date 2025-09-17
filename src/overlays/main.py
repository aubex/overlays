import platform
import sys


def cross_platform_helper():
    if platform.system() != "Windows":
        print("❌ Error: This application is designed to run on Windows only.")
        exit(1)

    from overlays.manager import main

    if len(sys.argv) == 2:
        main(sys.argv[1])
    else:
        main()


if __name__ == "__main__":
    cross_platform_helper()
