import platform
import click


@click.command()
@click.option(
    "--pipe_name", default=r"\\.\pipe\overlay_manager", help="Name of the Windows pipe."
)
def cross_platform_helper(pipe_name: str):
    if platform.system() != "Windows":
        print("❌ Error: This application is designed to run on Windows only.")
        exit(1)

    from overlays.manager import main

    main(pipe_name)


if __name__ == "__main__":
    cross_platform_helper()
