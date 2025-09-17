import platform


def cross_platform_helper():
    if platform.system() != "Windows":
        print("❌ Error: This application is designed to run on Windows only.")
        exit(1)

    from overlays.manager import main

    main()


if __name__ == "__main__":
    cross_platform_helper()
