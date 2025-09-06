import sys
import os
import re
import subprocess
from PyQt6.QtWidgets import (QApplication, QMainWindow, QSplitter, QListWidget, QListWidgetItem, QTabWidget,
                             QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QLineEdit, QLabel, QTableWidget,
                             QTableWidgetItem, QInputDialog, QMessageBox, QMenu, QHeaderView, QProgressBar)
from PyQt6.QtCore import Qt, QProcess, QProcessEnvironment
from PyQt6.QtGui import QColor, QPalette

from .config import load_config, save_config, get_secret, set_secret, delete_secret, is_secret
from .utils import list_installed_servers, install_server, uninstall_server, get_registry_servers, get_server_env_vars

class MCPcentralGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MCP Central")
        self.setGeometry(100, 100, 1200, 800)

        self.config = load_config()
        self.running_processes = {}  # server_name: (process, url)
        self.server_logs = {} # server_name: logs
        self.selected_server = None

        self.init_ui()

    def init_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.setCentralWidget(splitter)

        # Pane 1: Server Registry
        registry_pane = QWidget()
        registry_layout = QVBoxLayout(registry_pane)
        self.registry_search = QLineEdit()
        self.registry_search.setPlaceholderText("Search registry...")
        self.registry_search.textChanged.connect(self.update_registry_list)
        registry_layout.addWidget(self.registry_search)
        self.registry_list = QListWidget()
        registry_layout.addWidget(self.registry_list)
        self.registry_button = QPushButton("Refresh Registry")
        self.registry_button.clicked.connect(self.update_registry_list)
        registry_layout.addWidget(self.registry_button)
        splitter.addWidget(registry_pane)

        # Pane 2: Installed Servers
        installed_pane = QWidget()
        installed_layout = QVBoxLayout(installed_pane)
        self.installed_list = QListWidget()
        self.installed_list.itemClicked.connect(self.select_server)
        self.installed_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.installed_list.customContextMenuRequested.connect(self.show_installed_context_menu)
        installed_layout.addWidget(self.installed_list)
        refresh_installed = QPushButton("Refresh Installed")
        refresh_installed.clicked.connect(self.update_installed_list)
        installed_layout.addWidget(refresh_installed)
        splitter.addWidget(installed_pane)

        # Pane 3: Server Configuration & Interaction
        control_pane = QWidget()
        control_layout = QVBoxLayout(control_pane)
        self.control_tabs = QTabWidget()
        control_layout.addWidget(self.control_tabs)
        splitter.addWidget(control_pane)

        # Tabs
        self.controls_tab = QWidget()
        controls_layout = QVBoxLayout(self.controls_tab)
        self.start_stop_button = QPushButton("Start Server")
        self.start_stop_button.clicked.connect(self.toggle_server)
        controls_layout.addWidget(self.start_stop_button)
        self.launch_chat_button = QPushButton("Launch Chat")
        self.launch_chat_button.clicked.connect(self.launch_chat)
        controls_layout.addWidget(self.launch_chat_button)
        self.uninstall_button = QPushButton("Uninstall Server")
        self.uninstall_button.clicked.connect(self.uninstall_selected_server)
        controls_layout.addWidget(self.uninstall_button)
        self.control_tabs.addTab(self.controls_tab, "Controls")

        self.env_tab = QTableWidget(0, 3)
        self.env_tab.setHorizontalHeaderLabels(["Variable", "Value", "Actions"])
        self.env_tab.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        add_env_button = QPushButton("Add Environment Variable")
        add_env_button.clicked.connect(self.add_env_var)
        env_layout = QVBoxLayout()
        env_layout.addWidget(self.env_tab)
        env_layout.addWidget(add_env_button)
        env_widget = QWidget()
        env_widget.setLayout(env_layout)
        self.control_tabs.addTab(env_widget, "Environment Variables")

        self.logs_tab = QWidget()
        logs_layout = QVBoxLayout(self.logs_tab)
        self.logs_text = QLabel("Logs will appear here...")
        self.logs_text.setWordWrap(True)
        self.logs_text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        logs_layout.addWidget(self.logs_text)
        self.control_tabs.addTab(self.logs_tab, "Logs")

        # Initial updates
        self.update_registry_list()
        self.update_installed_list()
        self.update_controls_tab()

    def update_registry_list(self):
        query = self.registry_search.text()
        try:
            servers = get_registry_servers(self.config.get('api_key'), query)
            self.registry_list.clear()
            for server in servers:
                item = QListWidgetItem()
                self.registry_list.addItem(item)

                widget = QWidget()
                layout = QHBoxLayout(widget)
                layout.setContentsMargins(0, 5, 0, 5)
                layout.addWidget(QLabel(f"<b>{server['displayName']}</b><br>{server['description']}"))
                install_button = QPushButton("Install")
                install_button.clicked.connect(lambda _, s=server['qualifiedName']: self.install_from_registry(s))
                layout.addWidget(install_button)
                item.setSizeHint(widget.sizeHint())
                self.registry_list.setItemWidget(item, widget)

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not fetch registry: {e}")

    def install_from_registry(self, package):
        try:
            progress = QProgressBar(self)
            progress.setRange(0, 0)
            self.statusBar().addWidget(progress)
            QApplication.processEvents() # Update UI

            install_server(package)

            self.statusBar().removeWidget(progress)
            QMessageBox.information(self, "Success", f"Installed {package}")
            self.update_installed_list()
        except RuntimeError as e:
            self.statusBar().removeWidget(progress)
            QMessageBox.warning(self, "Error", str(e))

    def update_installed_list(self):
        self.installed_list.clear()
        installed = list_installed_servers()
        for server in installed:
            item = QListWidgetItem(server)
            self.installed_list.addItem(item)

        self.update_server_statuses()

    def update_server_statuses(self):
        for i in range(self.installed_list.count()):
            item = self.installed_list.item(i)
            server = item.text()
            status = "Running" if server in self.running_processes else "Stopped"
            color = QColor("green") if status == "Running" else QColor("red")

            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(0,0,0,0)
            layout.addWidget(QLabel(server))
            status_label = QLabel(status)
            palette = status_label.palette()
            palette.setColor(QPalette.ColorRole.WindowText, color)
            status_label.setPalette(palette)
            layout.addWidget(status_label, alignment=Qt.AlignmentFlag.AlignRight)
            item.setSizeHint(widget.sizeHint())
            self.installed_list.setItemWidget(item, widget)

    def show_installed_context_menu(self, position):
        item = self.installed_list.itemAt(position)
        if item:
            server_name = item.text()
            menu = QMenu()
            is_running = server_name in self.running_processes

            start_action = menu.addAction("Stop" if is_running else "Start")
            start_action.triggered.connect(lambda: self.toggle_server(server_name))

            uninstall_action = menu.addAction("Uninstall")
            uninstall_action.triggered.connect(lambda: self.uninstall_selected_server(server_name))
            menu.exec(self.installed_list.mapToGlobal(position))

    def select_server(self, item):
        self.selected_server = item.text()
        self.update_controls_tab()
        self.update_env_tab()
        self.update_logs_tab()

    def update_controls_tab(self):
        if self.selected_server:
            is_running = self.selected_server in self.running_processes
            self.start_stop_button.setText("Stop Server" if is_running else "Start Server")
            self.start_stop_button.setEnabled(True)
            self.launch_chat_button.setEnabled(is_running)
            self.uninstall_button.setEnabled(True)
        else:
            self.start_stop_button.setText("Start Server")
            self.start_stop_button.setEnabled(False)
            self.launch_chat_button.setEnabled(False)
            self.uninstall_button.setEnabled(False)

    def toggle_server(self, server_name=None):
        server = server_name or self.selected_server
        if not server:
            return

        if server in self.running_processes:
            process, url = self.running_processes.pop(server)
            process.terminate()
            process.waitForFinished(1000)
        else:
            env_vars = self.get_env_for_server(server)
            process = QProcess(self)
            process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            process.readyReadStandardOutput.connect(lambda: self.handle_server_output(server))

            penv = QProcessEnvironment.systemEnvironment()
            for k, v in env_vars.items():
                penv.insert(k, v)
            process.setProcessEnvironment(penv)

            self.server_logs[server] = f"Starting server {server}...\n"
            self.update_logs_tab()

            process.start('npx', ['@smithery/cli', 'run', server])
            self.running_processes[server] = (process, None) # URL is unknown initially

        self.update_server_statuses()
        self.update_controls_tab()

    def handle_server_output(self, server):
        if server not in self.running_processes: return

        process, url = self.running_processes[server]
        output = process.readAllStandardOutput().data().decode(errors='ignore')

        self.server_logs[server] += output
        if self.selected_server == server:
            self.update_logs_tab()

        if url is None:
            match = re.search(r'Listening on (http://localhost:\d+)', output)
            if match:
                new_url = match.group(1)
                self.running_processes[server] = (process, new_url)
                self.update_server_statuses()
                self.update_controls_tab()

    def get_env_for_server(self, server):
        env = {}
        required_vars = get_server_env_vars(server)
        for var in required_vars:
            # All variables, secret or not, are stored in the keyring for simplicity and security.
            value = get_secret(server, var)
            if value:
                env[var] = value
        return env

    def launch_chat(self):
        if not self.selected_server or self.selected_server not in self.running_processes:
            return

        server = self.selected_server
        _, url = self.running_processes[server]
        if not url:
            QMessageBox.warning(self, "Server Not Ready", "Server is still starting up. Please wait for the URL to appear.")
            return

        terminal = self.config.get('terminal', 'konsole')
        ollama_host = self.config.get('ollama_host', 'http://localhost:11434')
        model, ok = QInputDialog.getText(self, "Select Model", "Enter Ollama Model name:", text="llama3")
        if ok and model:
            try:
                subprocess.Popen([terminal, '-e', 'ollmcp', '--mcp-server-url', url, '--model', model, '--host', ollama_host])
            except FileNotFoundError:
                QMessageBox.critical(self, "Error", f"Could not find terminal '{terminal}'. Please configure it in the settings.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to launch chat: {e}")

    def uninstall_selected_server(self, server_name=None):
        server = server_name or self.selected_server
        if not server: return

        if QMessageBox.question(self, "Confirm", f"Are you sure you want to uninstall {server}?") == QMessageBox.StandardButton.Yes:
            if server in self.running_processes:
                self.toggle_server(server) # Stop it first

            try:
                uninstall_server(server)
                if server in self.server_logs:
                    del self.server_logs[server]
                if self.selected_server == server:
                    self.selected_server = None

                self.update_installed_list()
                self.update_controls_tab()
                self.update_env_tab()
                self.update_logs_tab()

            except RuntimeError as e:
                QMessageBox.warning(self, "Error", str(e))

    def update_env_tab(self):
        self.env_tab.setRowCount(0)
        if not self.selected_server: return

        server = self.selected_server
        required_vars = get_server_env_vars(server)
        for var in required_vars:
            value = get_secret(server, var) or ""
            display_value = "(hidden)" if is_secret(var) else value
            self.add_env_row(var, display_value)

    def add_env_row(self, var, value):
        row = self.env_tab.rowCount()
        self.env_tab.insertRow(row)
        self.env_tab.setItem(row, 0, QTableWidgetItem(var))

        value_item = QTableWidgetItem(value)
        self.env_tab.setItem(row, 1, value_item)

        set_button = QPushButton("Set")
        set_button.clicked.connect(lambda: self.set_env_var(row))
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(lambda: self.clear_env_var(row))

        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(0,0,0,0)
        actions_layout.addWidget(set_button)
        actions_layout.addWidget(clear_button)
        self.env_tab.setCellWidget(row, 2, actions_widget)

    def add_env_var(self):
        if not self.selected_server: return
        var, ok = QInputDialog.getText(self, "Add Variable", "Variable Name:")
        if ok and var:
            self.add_env_row(var, '')

    def set_env_var(self, row):
        server = self.selected_server
        var = self.env_tab.item(row, 0).text()
        prompt = f"Enter value for {var}:"

        value, ok = QInputDialog.getText(self, "Set Value", prompt,
                                           echo=QLineEdit.EchoMode.Password if is_secret(var) else QLineEdit.EchoMode.Normal)
        if ok:
            set_secret(server, var, value) # Store all as secrets for simplicity
            if is_secret(var):
                self.env_tab.item(row, 1).setText("(hidden)")
            else:
                self.env_tab.item(row, 1).setText(value)

    def clear_env_var(self, row):
        server = self.selected_server
        var = self.env_tab.item(row, 0).text()
        delete_secret(server, var)
        self.env_tab.item(row, 1).setText("")

    def update_logs_tab(self):
        if self.selected_server:
            self.logs_text.setText(self.server_logs.get(self.selected_server, "Server not running or no logs yet."))
        else:
            self.logs_text.setText("No server selected.")

def main():
    app = QApplication(sys.argv)
    window = MCPcentralGUI()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
