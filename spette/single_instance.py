"""Only one SpeTte per user: a second start asks the first one to show its window and ends."""

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    activated = pyqtSignal()           # another start asked this instance to show itself

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self._key = key
        self._server = None
        self._connections = []

    def claim(self, timeout_ms: int = 500) -> bool:
        """True when this is the first instance. False when another one is running (it has been told to show)."""
        socket = QLocalSocket()
        socket.connectToServer(self._key)
        if socket.waitForConnected(timeout_ms):
            socket.write(b"show\n")
            socket.flush()
            socket.waitForBytesWritten(timeout_ms)
            socket.waitForReadyRead(timeout_ms)         # the first instance answers once it has read the message;
            socket.disconnectFromServer()               # closing sooner can drop the message (Windows pipes)
            return False
        QLocalServer.removeServer(self._key)        # the leftover of an instance that crashed
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(self._key):
            return True                             # cannot guard (odd system): run anyway rather than not at all
        server.newConnection.connect(self._on_connection)
        self._server = server
        return True

    def _on_connection(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            connection = self._server.nextPendingConnection()
            self._connections.append(connection)
            connection.readyRead.connect(self._on_message)          # no lambda: it would hold the socket in a cycle
            connection.disconnected.connect(self._on_disconnected)  # that only the garbage collector could break

    def _on_message(self) -> None:
        connection = self.sender()
        if connection is None:
            return
        connection.readAll()
        connection.write(b"ok\n")
        connection.flush()
        self.activated.emit()

    def _on_disconnected(self) -> None:
        connection = self.sender()
        if connection is not None:
            self._forget(connection)

    def _forget(self, connection) -> None:
        if connection in self._connections:
            self._connections.remove(connection)
        connection.deleteLater()

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server.deleteLater()           # never left to be destroyed after the application at exit
            self._server = None
        for connection in list(self._connections):
            self._forget(connection)
