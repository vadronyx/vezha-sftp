import sys
import os
import stat
import paramiko

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLineEdit, QPushButton, QListWidget,
                             QSplitter, QTreeView, QTextEdit, QProgressBar,
                             QListWidgetItem, QMessageBox, QAbstractItemView)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDir
from PyQt6.QtGui import QIcon, QFileSystemModel, QAction

STYLE_SHEET = """
QMainWindow { background-color: #1e1e1e; }
QWidget { color: #cccccc; font-family: 'Segoe UI', sans-serif; font-size: 13px; }

QLineEdit { 
    background-color: #2d2d30; border: 1px solid #3f3f46; 
    padding: 6px; border-radius: 3px; color: #ffffff;
}
QLineEdit:focus { border: 1px solid #007acc; }

QPushButton { 
    background-color: #007acc; color: white; border: none; 
    padding: 7px 15px; border-radius: 3px; font-weight: bold;
}
QPushButton:hover { background-color: #0098ff; }
QPushButton:pressed { background-color: #005c99; }
QPushButton:disabled { background-color: #555555; color: #888888; }
QPushButton#disconnectBtn { background-color: #9e2a2b; }
QPushButton#disconnectBtn:hover { background-color: #b23b3c; }

QListWidget, QTreeView, QTextEdit { 
    background-color: #252526; border: 1px solid #3f3f46; 
    border-radius: 3px; outline: none; padding: 2px;
}
QListWidget::item, QTreeView::item { padding: 4px; }
QListWidget::item:selected, QTreeView::item:selected { 
    background-color: #37373d; color: #ffffff; border: 1px solid #007acc;
}

QSplitter::handle { background-color: #3f3f46; margin: 2px; }
QHeaderView::section { background-color: #2d2d30; color: #cccccc; padding: 4px; border: 1px solid #3f3f46; }

QProgressBar {
    background-color: #2d2d30; border: 1px solid #3f3f46; border-radius: 3px;
    text-align: center; color: white; font-weight: bold;
}
QProgressBar::chunk { background-color: #007acc; border-radius: 2px; }

QMenuBar { background-color: #2d2d30; color: #cccccc; border-bottom: 1px solid #3f3f46; }
QMenuBar::item:selected { background-color: #3f3f46; }
QMenu { background-color: #252526; color: #cccccc; border: 1px solid #3f3f46; }
QMenu::item:selected { background-color: #007acc; color: white; }
"""

class RemoteFileList(QListWidget):
    file_dropped = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.isfile(file_path):
                self.file_dropped.emit(file_path)
            elif os.path.isdir(file_path):
                # TODO: фіча на майбутнє. Поки що ігнорую, щоб не ускладнювати рекурсію.
                pass

class SFTPWorker(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int)

    def __init__(self, config, action="list", remote_path=".", local_path=None, file_name=None):
        super().__init__()
        self.config = config
        self.action = action
        self.remote_path = remote_path
        self.local_path = local_path
        self.file_name = file_name

    def run(self):
        try:
            transport = paramiko.Transport((self.config['host'], int(self.config['port'])))
            transport.banner_timeout = 5

            try:
                transport.connect(username=self.config['user'], password=self.config['pass'])
            except paramiko.AuthenticationException:
                self.error.emit("Login or password incorrect!")
                return
            except Exception as e:
                self.error.emit(f"Failed to connect: {str(e)}")
                return

            sftp = paramiko.SFTPClient.from_transport(transport)

            if self.action == "list":
                self.log.emit(f"Reading directory: {self.remote_path}")
                items = []
                for attr in sftp.listdir_attr(self.remote_path):
                    is_dir = stat.S_ISDIR(attr.st_mode)
                    items.append((attr.filename, is_dir))

                folders = sorted([i for i in items if i[1]], key=lambda x: x[0].lower())
                files = sorted([i for i in items if not i[1]], key=lambda x: x[0].lower())
                self.finished.emit([("..", True)] + folders + files)

            elif self.action == "download":
                remote_target = os.path.join(self.remote_path, self.file_name).replace("\\", "/")
                local_target = os.path.join(self.local_path, self.file_name)
                self.log.emit(f"Downloading: {self.file_name}")
                sftp.get(remote_target, local_target, callback=lambda t, total: self.progress.emit(t, total))
                self.log.emit("Download complete.")
                self.finished.emit([])

            elif self.action == "upload":
                remote_target = os.path.join(self.remote_path, self.file_name).replace("\\", "/")
                self.log.emit(f"Uploading: {self.file_name}")
                sftp.put(self.local_path, remote_target, callback=lambda t, total: self.progress.emit(t, total))
                self.log.emit("Upload complete.")
                self.finished.emit([])

            sftp.close()
            transport.close()
        except Exception as e:
            self.error.emit(str(e))


class EnSFTPApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vezha SFTP")
        self.setMinimumSize(1000, 700)
        self.setStyleSheet(STYLE_SHEET)

        self.current_remote_path = "."
        self.init_ui()
        self.create_menu_bar()

    def create_menu_bar(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        server_menu = menubar.addMenu("Server")
        connect_action = QAction("Connect", self)
        connect_action.triggered.connect(self.start_connect)
        server_menu.addAction(connect_action)

        disconnect_action = QAction("Disconnect", self)
        disconnect_action.triggered.connect(self.disconnect_server)
        server_menu.addAction(disconnect_action)

        help_menu = menubar.addMenu("Help")
        about_action = QAction("About program...", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        conn_layout = QHBoxLayout()
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("Host (IP or Domain)")
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Username")
        self.pass_input = QLineEdit()
        self.pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_input.setPlaceholderText("Password")
        self.port_input = QLineEdit("22")
        self.port_input.setFixedWidth(50)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.start_connect)

        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setObjectName("disconnectBtn")
        self.disconnect_btn.clicked.connect(self.disconnect_server)

        conn_layout.addWidget(self.host_input)
        conn_layout.addWidget(self.user_input)
        conn_layout.addWidget(self.pass_input)
        conn_layout.addWidget(self.port_input)
        conn_layout.addWidget(self.connect_btn)
        conn_layout.addWidget(self.disconnect_btn)
        main_layout.addLayout(conn_layout)

        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.file_splitter = QSplitter(Qt.Orientation.Horizontal)

        local_widget = QWidget()
        local_layout = QVBoxLayout(local_widget)
        local_layout.setContentsMargins(0, 0, 0, 0)

        self.local_model = QFileSystemModel()
        self.local_model.setRootPath(QDir.rootPath())
        self.local_tree = QTreeView()
        self.local_tree.setModel(self.local_model)
        self.local_tree.setRootIndex(self.local_model.index(QDir.homePath()))
        self.local_tree.setColumnWidth(0, 250)

        self.upload_btn = QPushButton("Upload to server ->")
        self.upload_btn.clicked.connect(self.upload_file)

        local_layout.addWidget(self.local_tree)
        local_layout.addWidget(self.upload_btn)

        remote_widget = QWidget()
        remote_layout = QVBoxLayout(remote_widget)
        remote_layout.setContentsMargins(0, 0, 0, 0)

        self.remote_list = RemoteFileList()
        self.remote_list.itemDoubleClicked.connect(self.change_directory)
        self.remote_list.file_dropped.connect(self.upload_dropped_file)

        self.download_btn = QPushButton("<- Download")
        self.download_btn.clicked.connect(self.download_file)

        remote_layout.addWidget(self.remote_list)
        remote_layout.addWidget(self.download_btn)

        self.file_splitter.addWidget(local_widget)
        self.file_splitter.addWidget(remote_widget)
        self.file_splitter.setSizes([500, 500])

        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(18)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()

        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setMaximumHeight(150)
        self.log("System ready. Enter data to connect.")

        bottom_layout.addWidget(self.progress_bar)
        bottom_layout.addWidget(self.log_console)

        self.main_splitter.addWidget(self.file_splitter)
        self.main_splitter.addWidget(bottom_widget)
        main_layout.addWidget(self.main_splitter)

    def log(self, message):
        self.log_console.append(f"> {message}")
        scrollbar = self.log_console.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def get_config(self):
        return {
            'host': self.host_input.text(),
            'port': self.port_input.text(),
            'user': self.user_input.text(),
            'pass': self.pass_input.text()
        }

    def start_connect(self):
        if not self.host_input.text():
            self.log("Error: Host address is empty!")
            return

        self.log("Connecting to server...")
        self.worker = SFTPWorker(self.get_config(), "list", self.current_remote_path)
        self.worker.finished.connect(self.update_list)
        self.worker.error.connect(self.handle_error)
        self.worker.log.connect(self.log)
        self.worker.start()

    def disconnect_server(self):
        """Clear list, reset session connection"""
        self.remote_list.clear()
        self.current_remote_path = "."
        self.log("Disconnected from server.")
        self.progress_bar.hide()

    def update_list(self, files):
        self.remote_list.clear()
        dir_icon = self.style().standardIcon(self.style().StandardPixmap.SP_DirIcon)
        file_icon = self.style().standardIcon(self.style().StandardPixmap.SP_FileIcon)

        for name, is_dir in files:
            item = QListWidgetItem(name)
            if is_dir:
                item.setIcon(dir_icon)
                item.setData(Qt.ItemDataRole.UserRole, "dir")
            else:
                item.setIcon(file_icon)
                item.setData(Qt.ItemDataRole.UserRole, "file")
            self.remote_list.addItem(item)

        self.log(f"Current directory: {self.current_remote_path}")

    def change_directory(self, item):
        if item.data(Qt.ItemDataRole.UserRole) != "dir": return
        name = item.text()
        if name == "..":
            self.current_remote_path = "/".join(self.current_remote_path.rstrip("/").split("/")[:-1])
            if not self.current_remote_path: self.current_remote_path = "/"
        else:
            if self.current_remote_path == "/":
                self.current_remote_path += name
            else:
                self.current_remote_path += f"/{name}"
        self.start_connect()

    def update_progress(self, transferred, total):
        if total > 0:
            percent = int((transferred / total) * 100)
            self.progress_bar.setValue(percent)

    def transfer_finished(self):
        self.progress_bar.hide()
        self.progress_bar.setValue(0)
        self.start_connect()

    def download_file(self):
        item = self.remote_list.currentItem()
        if not item or item.data(Qt.ItemDataRole.UserRole) == "dir":
            self.log("Select a file to download.")
            return

        local_index = self.local_tree.currentIndex()
        if not local_index.isValid():
            local_dir = QDir.homePath()
        else:
            local_info = self.local_model.fileInfo(local_index)
            local_dir = local_info.absoluteFilePath() if local_info.isDir() else local_info.absolutePath()

        self.start_worker_task("download", self.current_remote_path, local_dir, item.text())

    def upload_file(self):
        local_index = self.local_tree.currentIndex()
        if not local_index.isValid():
            self.log("Select a file to upload.")
            return

        local_info = self.local_model.fileInfo(local_index)
        if local_info.isDir():
            self.log("Folders cannot be uploaded yet.")
            return

        self.start_worker_task("upload", self.current_remote_path, local_info.absoluteFilePath(), local_info.fileName())

    def upload_dropped_file(self, file_path):
        """Action when file is uploaded via Drag & Drop"""
        file_name = os.path.basename(file_path)
        self.log(f"Uploading file via Drag & Drop: {file_name}")
        self.start_worker_task("upload", self.current_remote_path, file_path, file_name)

    def start_worker_task(self, action, remote_path, local_path, file_name):
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        self.worker = SFTPWorker(self.get_config(), action, remote_path, local_path, file_name)
        self.worker.log.connect(self.log)
        self.worker.progress.connect(self.update_progress)
        self.worker.error.connect(self.handle_error)
        self.worker.finished.connect(self.transfer_finished)
        self.worker.start()

    def handle_error(self, err):
        self.log(f"Error: {err}")
        self.progress_bar.hide()
        QMessageBox.critical(self, "Connection Error", err)

    def show_about(self):
        text = (
            "<h2>Vezha-SFTP Client</h2>"
            "<p>A simple program for working with SFTP servers.</p>"
            "<p><b>Version:</b> 1.0 (Stable)<br>"
            "<b>Developer:</b> Vadronyx Dev</p>"
        )
        QMessageBox.about(self, "About Program", text)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = EnSFTPApp()
    window.show()
    sys.exit(app.exec())
