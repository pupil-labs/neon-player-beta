import logging
import logging.handlers
import pickle
from pathlib import Path

from PySide6.QtNetwork import QLocalServer, QLocalSocket

from pupil_labs import neon_player

IPC_APP_NAME = "neon-player-log-ipc"


class IPCLogger(logging.Handler):
    def __init__(self) -> None:
        super().__init__()

        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)

        self.server = None
        self._client_sockets = []

        if not self._connect_to_log_socket():
            self._start_server()
            self._connect_to_log_socket()

        else:
            logging.getLogger().addHandler(self)

    def _start_server(self) -> None:
        QLocalServer.removeServer(IPC_APP_NAME)

        self.server = QLocalServer()
        if not self.server.listen(IPC_APP_NAME):
            raise OSError("Failed to start log server")

        """Configure logging to both console and file."""
        log_dir = Path.home() / "Pupil Labs" / "Neon Player" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        log_file = log_dir / "neon_player.log"

        # Set up root logger
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)

        # Create formatters
        log_formatter = logging.Formatter(neon_player.LOG_FORMAT_STRING)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_formatter)

        logger.addHandler(console_handler)

        # File handler with rotation (10MB per file, keep 5 backups)
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
            file_handler.setFormatter(log_formatter)
            logger.addHandler(file_handler)
            logging.info(f"Logging to file: {log_file}")
        except Exception:
            logging.exception(f"Could not start file logger [{log_file}]")

        self.server.newConnection.connect(self._handle_new_connection)

    def _handle_new_connection(self) -> None:
        socket = self.server.nextPendingConnection()
        socket.setReadBufferSize(0)
        socket.readyRead.connect(lambda: self._on_ready_ready(socket))

        self._client_sockets.append(socket)

    def _on_ready_ready(self, socket: QLocalSocket) -> None:
        log_record = pickle.loads(socket.readAll().data())  # noqa: S301
        log_record.msg = f"[BG] {log_record.msg}"
        logging.getLogger().handle(log_record)

    def _connect_to_log_socket(self) -> None:
        self.log_socket = QLocalSocket()
        self.log_socket.connectToServer(IPC_APP_NAME)

        return self.log_socket.waitForConnected(500)

    def handle(self, record: logging.LogRecord) -> None:
        if self.server is None:
            # Tracebacks can't be serialized, so if there's exception, strip the tb
            if record.exc_info:
                record.exc_info = record.exc_info[0:1]

            data = pickle.dumps(record)
            self.log_socket.write(data)
            self.log_socket.flush()
