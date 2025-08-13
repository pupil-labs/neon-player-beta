import multiprocessing as mp
import sys

from .app import NeonPlayerApp


def main() -> None:
    app = NeonPlayerApp(sys.argv)
    sys.exit(app.run())


if __name__ == "__main__":
    main()
