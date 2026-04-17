import sys
import os
import stat
import paramiko
import urllib.request
import json
import webbrowser
import posixpath
import binascii

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLineEdit, QPushButton, QListWidget,
                             QSplitter, QTreeView, QTextEdit, QProgressBar,
                             QListWidgetItem, QMessageBox, QAbstractItemView)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDir, QTimer, QEventLoop
from PyQt6.QtGui import QIcon, QFileSystemModel, QAction

CURRENT_VERSION = "1.0.3"
GITHUB_REPO = "vadronyx/VezhaSFTP"


class CancelledError(Exception):
    pass


class InteractivePolicy(paramiko.MissingHostKeyPolicy):

    def __init__(self, worker):
        self.worker = worker

    def missing_host_key(self, client, hostname, key):
        hex_fp = binascii.hexlify(key.get_fingerprint()).decode('utf-8')
        fingerprint = ':'.join(hex_fp[i:i + 2] for i in range(0, len(hex_fp), 2))
        key_type = key.get_name()

        self.worker.log.emit(f"[SECURITY] New host key detected for {hostname}: {fingerprint}")
        self.worker.log.emit("Awaiting host key confirmation...")

        self.worker._trust_answer = None
        loop = QEventLoop()
        self.worker.trust_resolved.connect(loop.quit)

        timeout_timer = QTimer()
        timeout_timer.setSingleShot(True)
        timeout_timer.timeout.connect(loop.quit)
        timeout_timer.start(60000)

        self.worker.ask_trust_signal.emit(hostname, key_type, fingerprint)

        loop.exec()
        timeout_timer.stop()

        if self.worker._is_cancelled:
            raise CancelledError("Operation cancelled during trust prompt.")

        if self.worker._trust_answer is None:
            raise paramiko.SSHException("Host trust prompt timed out (60s) or aborted.")

        if self.worker._trust_answer is True:
            client.get_host_keys().add(hostname, key.get_name(), key)
            filename = client._host_keys_filename
            if not filename:
                filename = os.path.expanduser('~/.ssh/known_hosts')
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            client.save_host_keys(filename)
            return
        else:
            raise paramiko.SSHException(f"Connection rejected by user. Untrusted host key for {hostname}.")


STYLE_SHEET = """
QMainWindow { background-color: #1e1e1e; }
QWidget { color: #cccccc; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
QLineEdit { background-color: #2d2d30; border: 1px solid #3f3f46; padding: 6px; border-radius: 3px; color: #ffffff; }
QLineEdit:focus { border: 1px solid #007acc; }
QLineEdit:disabled { background-color: #1e1e1e; color: #555555; }
QPushButton { background-color: #007acc; color: white; border: none; padding: 7px 15px; border-radius: 3px; font-weight: bold; }
QPushButton:hover { background-color: #0098ff; }
QPushButton:pressed { background-color: #005c99; }
QPushButton:disabled { background-color: #333333; color: #666666; }
QPushButton#disconnectBtn { background-color: #9e2a2b; }
QPushButton#disconnectBtn:hover { background-color: #b23b3c; }
QPushButton#disconnectBtn:disabled { background-color: #4a1516; color: #888888; }
QListWidget, QTreeView, QTextEdit { background-color: #252526; border: 1px solid #3f3f46; border-radius: 3px; outline: none; padding: 2px; }
QListWidget::item, QTreeView::item { padding: 4px; }
QListWidget::item:selected, QTreeView::item:selected { background-color: #37373d; color: #ffffff; border: 1px solid #007acc; }
QSplitter::handle { background-color: #3f3f46; margin: 2px; }
QHeaderView::section { background-color: #2d2d30; color: #cccccc; padding: 4px; border: 1px solid #3f3f46; }
QProgressBar { background-color: #2d2d30; border: 1px solid #3f3f46; border-radius: 3px; text-align: center; color: white; font-weight: bold; }
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


class SFTPWorker(QThread):
    directory_loaded = pyqtSignal(list)
    transfer_completed = pyqtSignal()
    error = pyqtSignal(str)
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int)

    ask_trust_signal = pyqtSignal(str, str, str)
    trust_resolved = pyqtSignal()

    ask_large_file_signal = pyqtSignal(str, int)
    large_file_resolved = pyqtSignal()

    def __init__(self, host, port, user, password, action="list", remote_path=".", local_path=None, file_name=None,
                 parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port
        self.user = user
        self.password = password  # ?????????? ?????????
        self.action = action
        self.remote_path = remote_path
        self.local_path = local_path
        self.file_name = file_name

        self._is_cancelled = False
        self._trust_answer = None
        self._large_file_answer = None

    def cancel(self):
        self._is_cancelled = True
        self.trust_resolved.emit()
        self.large_file_resolved.emit()

    def set_trust_response(self, answer):
        self._trust_answer = answer
        self.trust_resolved.emit()

    def set_large_file_response(self, answer):
        self._large_file_answer = answer
        self.large_file_resolved.emit()

    def progress_callback(self, transferred, total):
        if self._is_cancelled:
            raise CancelledError("Operation cancelled by user.")
        self.progress.emit(transferred, total)

    def check_large_file(self, file_size):
        LARGE_FILE_LIMIT = 500 * 1024 * 1024  # 500 MB
        if file_size > LARGE_FILE_LIMIT:
            self._large_file_answer = None
            loop = QEventLoop()
            self.large_file_resolved.connect(loop.quit)
            self.ask_large_file_signal.emit(self.file_name, file_size)
            loop.exec()

            if self._is_cancelled or not self._large_file_answer:
                raise CancelledError(f"Transfer of large file '{self.file_name}' cancelled by user.")

    def run(self):
        client = None
        sftp = None

        # Memory Safety: ??????????? ?????? ? ???????? ?????? ? ????????? ??????? ??'????
        temp_password = self.password
        self.password = None

        try:
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            client.set_missing_host_key_policy(InteractivePolicy(self))

            client.connect(
                hostname=self.host,
                port=int(self.port),
                username=self.user,
                password=temp_password,
                timeout=10,
                banner_timeout=10,
                auth_timeout=10
            )
            # Memory Safety: ????????? ???????? ?????? ????? ?'???????
            temp_password = None

            sftp = client.open_sftp()

            if self.action == "list":
                self.log.emit(f"Reading directory: {self.remote_path}")
                items = []
                for attr in sftp.listdir_attr(self.remote_path):
                    if self._is_cancelled: raise CancelledError("Operation cancelled by user.")
                    is_dir = stat.S_ISDIR(attr.st_mode)
                    items.append((attr.filename, is_dir))

                folders = sorted([i for i in items if i[1]], key=lambda x: x[0].lower())
                files = sorted([i for i in items if not i[1]], key=lambda x: x[0].lower())
                self.directory_loaded.emit([("..", True)] + folders + files)

            elif self.action == "download":
                remote_target = posixpath.join(self.remote_path, self.file_name)
                local_target = os.path.join(self.local_path, self.file_name)

                attr = sftp.stat(remote_target)
                self.check_large_file(attr.st_size)

                self.log.emit(f"Downloading: {self.file_name}")
                sftp.get(remote_target, local_target, callback=self.progress_callback)
                self.log.emit("Download complete.")
                self.transfer_completed.emit()

            elif self.action == "upload":
                remote_target = posixpath.join(self.remote_path, self.file_name)

                file_size = os.path.getsize(self.local_path)
                self.check_large_file(file_size)

                self.log.emit(f"Uploading: {self.file_name}")
                sftp.put(self.local_path, remote_target, callback=self.progress_callback)
                self.log.emit("Upload complete.")
                self.transfer_completed.emit()

        except CancelledError as e:
            self.error.emit(str(e))
        except paramiko.AuthenticationException:
            self.error.emit("Login or password incorrect!")
        except paramiko.SSHException as e:
            self.error.emit(f"SSH Error: {str(e)}")
        except OSError as e:
            self.error.emit(f"Network Error: {str(e)}")
        except Exception as e:
            self.error.emit(f"Unexpected Error: {str(e)}")
        finally:
            if sftp: sftp.close()
            if client: client.close()


class UpdateChecker(QThread):
    update_available = pyqtSignal(str, str)

    def parse_version(self, v_string):
        clean_v = v_string.lower().lstrip('v').strip()
        try:
            return tuple(map(int, clean_v.split('.')))
        except ValueError:
            return (0, 0, 0)

    def run(self):
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            req = urllib.request.Request(url, headers={'User-Agent': f'VezhaSFTP-Client-v{CURRENT_VERSION}'})
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                latest_version = data["tag_name"]
                if self.parse_version(latest_version) > self.parse_version(CURRENT_VERSION):
                    self.update_available.emit(latest_version, data["html_url"])
        except Exception:
            pass


class EnSFTPApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Vezha SFTP v{CURRENT_VERSION}")
        self.setMinimumSize(1000, 700)
        self.setStyleSheet(STYLE_SHEET)

        self.current_remote_path = "."
        self.is_logged_in = False

        self.init_ui()
        self.create_menu_bar()
        self.set_session_state(False)
        self.check_for_updates()

    def is_worker_active(self):
        if getattr(self, "worker", None) is None:
            return False
        try:
            return self.worker.isRunning()
        except RuntimeError:
            self.worker = None
            return False

    def check_for_updates(self):
        self.updater = UpdateChecker(parent=self)
        self.updater.update_available.connect(self.prompt_update)
        self.updater.finished.connect(self.updater.deleteLater)
        self.updater.start()

    def prompt_update(self, version, url):
        self.log(f"[UPDATE] New version {version} is available on GitHub!")
        reply = QMessageBox.question(
            self, "Update Available",
            f"A new version of VezhaSFTP ({version}) is available!\n\nDo you want to download it from GitHub?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes: webbrowser.open(url)

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

    def set_session_state(self, is_logged_in):
        self.is_logged_in = is_logged_in
        self.host_input.setEnabled(not is_logged_in)
        self.user_input.setEnabled(not is_logged_in)
        self.pass_input.setEnabled(not is_logged_in)
        self.port_input.setEnabled(not is_logged_in)

        self.connect_btn.setEnabled(not is_logged_in)
        self.disconnect_btn.setEnabled(is_logged_in)

        if not is_logged_in:
            self.upload_btn.setEnabled(False)
            self.download_btn.setEnabled(False)

    def set_action_ui_locked(self, locked):
        if not self.is_logged_in: return
        self.upload_btn.setEnabled(not locked)
        self.download_btn.setEnabled(not locked)
        self.disconnect_btn.setEnabled(True)

    def ask_host_trust(self, hostname, key_type, fingerprint):
        worker = getattr(self, "worker", None)
        if not worker: return

        msg = (f"SECURITY WARNING: The server's host key is unknown!\n\n"
               f"Server: {hostname}\nKey Type: {key_type}\nFingerprint: {fingerprint}\n\n"
               f"?? This could be a MITM (Man-in-the-Middle) attack if you were expecting a known server.\n\n"
               f"Do you trust this host and want to add it to known_hosts?")

        reply = QMessageBox.warning(
            self, "Unknown Host Key", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        try:
            if worker and worker.isRunning():
                worker.set_trust_response(reply == QMessageBox.StandardButton.Yes)
        except RuntimeError:
            pass

    def ask_large_file(self, filename, size_bytes):
        worker = getattr(self, "worker", None)
        if not worker: return

        size_mb = size_bytes / (1024 * 1024)
        msg = (f"The file '{filename}' is quite large ({size_mb:.2f} MB).\n\n"
               f"Transferring large files may take a considerable amount of time. "
               f"Do you want to proceed?")

        reply = QMessageBox.question(
            self, "Large File Transfer", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        try:
            if worker and worker.isRunning():
                worker.set_large_file_response(reply == QMessageBox.StandardButton.Yes)
        except RuntimeError:
            pass

    def cleanup_worker(self):
        self.worker = None

    def validate_inputs(self):
        if not self.host_input.text() or not self.user_input.text():
            self.log("[ERROR]: Host and Username are required!")
            return False
        try:
            port = int(self.port_input.text())
            if not (0 < port <= 65535): raise ValueError
        except ValueError:
            self.log("[ERROR]: Invalid port number!")
            return False
        return True

    def start_connect(self):
        if self.is_worker_active() or not self.validate_inputs():
            return

        self.current_remote_path = "."

        self.set_session_state(False)
        self.connect_btn.setEnabled(False)
        self.log("Connecting to server...")

        self.worker = SFTPWorker(
            self.host_input.text(), self.port_input.text(),
            self.user_input.text(), self.pass_input.text(),
            "list", self.current_remote_path, parent=self
        )

        self.worker.ask_trust_signal.connect(self.ask_host_trust)
        self.worker.log.connect(self.log)
        self.worker.error.connect(self.handle_error)
        self.worker.directory_loaded.connect(self.update_list)

        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(self.cleanup_worker)
        self.worker.start()

    def refresh_directory(self):
        if not self.is_logged_in or self.is_worker_active(): return

        self.set_action_ui_locked(True)

        self.worker = SFTPWorker(
            self.host_input.text(), self.port_input.text(),
            self.user_input.text(), self.pass_input.text(),
            "list", self.current_remote_path, parent=self
        )
        self.worker.log.connect(self.log)
        self.worker.error.connect(self.handle_error)
        self.worker.directory_loaded.connect(self.update_list)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(self.cleanup_worker)
        self.worker.start()

    def disconnect_server(self):
        if self.is_worker_active():
            self.log("Cancelling active operations...")
            self.worker.cancel()
            if not self.worker.wait(3000):
                self.log("[WARNING]: Worker did not stop gracefully in time.")

        self.remote_list.clear()
        self.log("[STATUS]: Disconnected from server.")
        self.progress_bar.hide()
        self.set_session_state(False)

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

        if not self.is_logged_in:
            self.log("[STATUS]: Successfully connected.")
            self.set_session_state(True)

        self.set_action_ui_locked(False)

    def change_directory(self, item):
        if item.data(Qt.ItemDataRole.UserRole) != "dir": return
        name = item.text()
        if name == "..":
            self.current_remote_path = posixpath.dirname(self.current_remote_path)
            if not self.current_remote_path: self.current_remote_path = "/"
        else:
            self.current_remote_path = posixpath.join(self.current_remote_path, name)
        self.refresh_directory()

    def update_progress(self, transferred, total):
        if total > 0:
            percent = int((transferred / total) * 100)
            self.progress_bar.setValue(percent)

    def transfer_finished(self):
        self.progress_bar.hide()
        self.progress_bar.setValue(0)
        self.worker = None
        QTimer.singleShot(100, self.refresh_directory)

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
        file_name = os.path.basename(file_path)
        self.log(f"Uploading file via Drag & Drop: {file_name}")
        self.start_worker_task("upload", self.current_remote_path, file_path, file_name)

    def start_worker_task(self, action, remote_path, local_path, file_name):
        if self.is_worker_active() or not self.is_logged_in:
            return

        self.set_action_ui_locked(True)
        self.progress_bar.show()
        self.progress_bar.setValue(0)

        self.worker = SFTPWorker(
            self.host_input.text(), self.port_input.text(),
            self.user_input.text(), self.pass_input.text(),
            action, remote_path, local_path, file_name, parent=self
        )

        self.worker.ask_trust_signal.connect(self.ask_host_trust)
        self.worker.ask_large_file_signal.connect(self.ask_large_file)
        self.worker.log.connect(self.log)
        self.worker.progress.connect(self.update_progress)
        self.worker.error.connect(self.handle_error)
        self.worker.transfer_completed.connect(self.transfer_finished)

        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(self.cleanup_worker)
        self.worker.start()

    def handle_error(self, err):
        self.log(f"[ERROR]: {err}")
        self.progress_bar.hide()

        if not self.is_logged_in or "Authentication" in str(err) or "Network" in str(err):
            self.set_session_state(False)
            self.connect_btn.setEnabled(True)
        else:
            self.set_action_ui_locked(False)

        if "cancelled by user" not in str(err).lower() and "rejected" not in str(err).lower():
            QMessageBox.critical(self, "Error", str(err))

    def show_about(self):
        text = (
            "<h2>VezhaSFTP Client</h2>"
            "<p>A professional lightweight program for working with SFTP servers.</p>"
            f"<p><b>Version:</b> {CURRENT_VERSION}<br>"
            "<b>Developer:</b> vadronyx</p>"
        )
        QMessageBox.about(self, "About Program", text)


if __name__ == "__main__":
    # ??????????? ??? ??? ?????? ??????? Windows
    import ctypes

    try:
        myappid = f'vadronyx.vezhasftp.client.{CURRENT_VERSION.replace(".", "_")}'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setStyle("Fusion")


    def get_resource_path(relative_path):
        if hasattr(sys, '_MEIPASS'):
            return os.path.join(sys._MEIPASS, relative_path)
        return os.path.join(os.path.abspath("."), relative_path)


    icon_path = get_resource_path("icon.ico")
    app.setWindowIcon(QIcon(icon_path))

    window = EnSFTPApp()
    window.show()
    sys.exit(app.exec())
