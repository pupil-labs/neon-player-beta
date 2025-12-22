import sys


def main() -> None:
    from pupil_labs.neon_player.app import NeonPlayerApp

    app = NeonPlayerApp(sys.argv)
    sys.exit(app.run())
