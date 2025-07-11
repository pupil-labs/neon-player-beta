import multiprocessing as mp
import sys

from .app import NeonPlayerApp


def main() -> None:
    mp.set_start_method("spawn")
    app = NeonPlayerApp(sys.argv)
    sys.exit(app.run())


if __name__ == "__main__":
    main()
