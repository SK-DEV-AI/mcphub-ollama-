import subprocess
import re
import logging
import json
import tempfile
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, DataTable, TabbedContent, TabPane, Button, Log, Input, Label
from textual.containers import Horizontal, Vertical, Container
from .utils import list_installed_servers, get_registry_servers, install_server, uninstall_server, get_server_env_vars
from .config import load_config, get_secret, set_secret, delete_secret, is_secret, init_keyring
import os

logging.basicConfig(filename="mcp.log", level=logging.INFO, format='%(asctime)s - %(message)s')

class InputScreen(Screen):
    """A screen to get input from the user."""

    def __init__(self, prompt_text: str, is_password: bool = False, default_value: str = "") -> None:
        super().__init__()
        self.prompt_text = prompt_text
        self.is_password = is_password
        self.default_value = default_value

    def compose(self) -> ComposeResult:
        yield Container(
            Label(self.prompt_text),
            Input(value=self.default_value, password=self.is_password, id="input_field"),
            Button("Submit", id="submit_button"),
            id="dialog"
        )

    def on_mount(self) -> None:
        self.query_one("#input_field").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit_button":
            value = self.query_one("#input_field").value
            self.dismiss(value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)


class MCPCentralTUI(App):
    """A Textual application to manage MCP servers."""

    BINDINGS = [
        ("d", "toggle_dark", "Toggle dark mode"),
        ("r", "refresh_servers", "Refresh Installed"),
        ("f5", "refresh_registry", "Refresh Registry"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.running_processes = {}  # server_name: (process, url)
        self.server_logs = {} # server_name: logs
        self.selected_server = None
        self.selected_registry_server = None
        self.config = load_config()

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        with TabbedContent(initial="installed"):
            with TabPane("Installed Servers", id="installed"):
                with Horizontal():
                    yield DataTable(id="server_table")
                    with Vertical(id="installed_buttons"):
                        yield Button("Start", id="start_button", disabled=True)
                        yield Button("Stop", id="stop_button", disabled=True)
                        yield Button("View Logs", id="logs_button", disabled=True)
                        yield Button("Uninstall", id="uninstall_button", disabled=True)
                        yield Button("Launch Chat", id="launch_chat_button", disabled=True)
                        yield Button("Set Custom File", id="set_custom_file_button")
            with TabPane("Registry", id="registry"):
                with Vertical():
                    yield Input(placeholder="Search registry...", id="registry_search")
                    yield DataTable(id="registry_table")
                    yield Button("Install Server", id="install_button", disabled=True)
            with TabPane("Environment", id="env"):
                yield DataTable(id="env_table")
                with Horizontal():
                    yield Button("Set Value", id="set_env_button", disabled=True)
                    yield Button("Clear Value", id="clear_env_button", disabled=True)
            with TabPane("Logs", id="logs"):
                yield Log(id="log_view")
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        logging.info("App started")
        init_keyring()
        self.action_refresh_servers()
        self.set_interval(1, self.update_logs)
        self.action_refresh_registry()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Called when a row in the DataTable is selected."""
        if event.data_table.id == "server_table":
            if event.data_table.row_count > 0:
                self.selected_server = event.data_table.get_row_at(event.cursor_row)[0]
                self.update_installed_buttons()
                self.update_env_tab()
        elif event.data_table.id == "registry_table":
            if event.data_table.row_count > 0:
                self.selected_registry_server = event.data_table.get_row_at(event.cursor_row)[0]
                self.query_one("#install_button").disabled = False
        elif event.data_table.id == "env_table":
            if event.data_table.row_count > 0:
                self.query_one("#set_env_button").disabled = False
                self.query_one("#clear_env_button").disabled = False


    def update_installed_buttons(self):
        is_custom_server = False
        if self.selected_server:
            table = self.query_one("#server_table")
            # Ensure the cursor row is valid before getting cell data
            if table.row_count > 0 and 0 <= table.cursor_row < table.row_count:
                try:
                    source = table.get_cell_at((table.cursor_row, 2))
                    is_custom_server = (source == "Custom")
                except IndexError:
                    # This can happen if the table is refreshed and the cursor is out of bounds
                    # before the next selection event. Safest to assume not custom.
                    is_custom_server = False

        # Update context-sensitive buttons based on selected server
        if self.selected_server:
            is_running = self.selected_server in self.running_processes
            self.query_one("#start_button").disabled = is_running or is_custom_server
            self.query_one("#stop_button").disabled = not is_running or is_custom_server
            # Logs are only available for servers this app runs (Smithery servers)
            self.query_one("#logs_button").disabled = not (self.selected_server in self.server_logs)
            self.query_one("#uninstall_button").disabled = is_running or is_custom_server
        else:
            self.query_one("#start_button").disabled = True
            self.query_one("#stop_button").disabled = True
            self.query_one("#logs_button").disabled = True
            self.query_one("#uninstall_button").disabled = True

        # Update "Launch Chat" button based on any running server or custom servers
        any_server_running_with_url = any(
            url for _, url in self.running_processes.values() if url
        )
        custom_file_exists = self.config.get('custom_servers_file') and os.path.exists(self.config['custom_servers_file'])
        self.query_one("#launch_chat_button").disabled = not (any_server_running_with_url or custom_file_exists)

    def update_env_tab(self):
        table = self.query_one("#env_table")
        table.clear(columns=True)
        self.query_one("#set_env_button").disabled = True
        self.query_one("#clear_env_button").disabled = True
        if self.selected_server:
            table.add_columns("Variable", "Value")
            required_vars = get_server_env_vars(self.selected_server)
            for var in required_vars:
                value = get_secret(self.selected_server, var)
                display_value = "(hidden)" if is_secret(var) and value else value or ""
                table.add_row(var, display_value)

    def get_all_servers(self) -> list[str]:
        """Gets a unified list of servers from Smithery CLI and the custom JSON file."""
        servers = set()
        try:
            # Get servers from Smithery
            servers.update(list_installed_servers())
        except RuntimeError as e:
            logging.error(f"Error fetching Smithery servers: {e}")
            self.bell()
            self.server_logs["smithery_error"] = str(e)
            self.selected_server = "smithery_error"
            self.view_logs()

        # Get servers from custom file
        custom_file_path = self.config.get('custom_servers_file')
        if custom_file_path and os.path.exists(custom_file_path):
            try:
                with open(custom_file_path, 'r') as f:
                    custom_data = json.load(f)

                if not isinstance(custom_data, dict) or "mcpServers" not in custom_data:
                    raise ValueError("JSON file must be an object with a top-level 'mcpServers' key.")

                mcp_servers = custom_data["mcpServers"]
                if not isinstance(mcp_servers, dict):
                    raise ValueError("The 'mcpServers' key must contain a dictionary of server objects.")

                custom_servers = mcp_servers.keys()
                servers.update(custom_servers)

            except (json.JSONDecodeError, IOError, ValueError) as e:
                error_message = f"Error processing custom servers file {custom_file_path}: {e}"
                logging.error(error_message)
                self.bell()
                self.server_logs["custom_file_error"] = error_message
                self.selected_server = "custom_file_error"
                self.view_logs()

        return sorted(list(servers))

    def _get_all_servers_blocking(self) -> tuple[list, set]:
        """Blocking method to get all servers."""
        all_servers = self.get_all_servers()
        smithery_servers = set(list_installed_servers())
        return all_servers, smithery_servers

    def update_server_table(self, result: tuple[list, set]):
        """Callback to update the server table from the main thread."""
        all_servers, smithery_servers = result
        table = self.query_one("#server_table")
        table.clear(columns=True)
        table.add_columns("Server Name", "Status", "Source")

        for server in all_servers:
            status = "Running" if server in self.running_processes else "N/A"
            source = "Smithery" if server in smithery_servers else "Custom"
            if source == "Smithery":
                status = "Running" if server in self.running_processes else "Stopped"
            table.add_row(server, status, source)
        self.update_installed_buttons()

    def action_refresh_servers(self) -> None:
        """An action to refresh the list of installed servers."""
        logging.info("Refreshing servers")
        self.run_in_thread(self._get_all_servers_blocking, callback=self.update_server_table)

    def _get_registry_servers_blocking(self, query=""):
        """Blocking method to get registry servers."""
        try:
            return get_registry_servers(self.config.get('api_key'), query)
        except Exception as e:
            logging.error(f"Error refreshing registry: {e}")
            self.bell()
            self.server_logs["registry_error"] = str(e)
            self.selected_server = "registry_error"
            self.call_from_thread(self.view_logs)
            return None

    def update_registry_table(self, servers: list | None):
        """Callback to update the registry table from the main thread."""
        if servers is None:
            return
        table = self.query_one("#registry_table")
        table.clear(columns=True)
        table.add_columns("Name", "Description")
        for server in servers:
            table.add_row(server['qualifiedName'], server['description'])

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "registry_search":
            self.action_refresh_registry(event.value)

    def action_refresh_registry(self, query=""):
        logging.info(f"Refreshing registry with query: {query}")
        self.run_in_thread(lambda: self._get_registry_servers_blocking(query), callback=self.update_registry_table)

    def _install_server_blocking(self):
        if not self.selected_registry_server:
            return
        logging.info(f"Installing server: {self.selected_registry_server}")
        try:
            install_server(self.selected_registry_server)
            self.call_from_thread(self.action_refresh_servers)
        except Exception as e:
            logging.error(f"Error installing server: {e}")
            self.bell()
            self.server_logs["install_error"] = str(e)
            self.selected_server = "install_error"
            self.call_from_thread(self.view_logs)

    def _uninstall_server_blocking(self):
        if not self.selected_server:
            return
        logging.info(f"Uninstalling server: {self.selected_server}")
        try:
            if self.selected_server in self.running_processes:
                self.call_from_thread(self.stop_server)
            uninstall_server(self.selected_server)
            self.call_from_thread(self.action_refresh_servers)
            self.selected_server = None
            self.call_from_thread(self.update_installed_buttons)
            self.call_from_thread(self.update_env_tab)
        except Exception as e:
            logging.error(f"Error uninstalling server: {e}")
            self.bell()
            self.server_logs["uninstall_error"] = str(e)
            self.selected_server = "uninstall_error"
            self.call_from_thread(self.view_logs)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Called when a button is pressed."""
        if event.button.id == "start_button":
            self.start_server()
        elif event.button.id == "stop_button":
            self.stop_server()
        elif event.button.id == "logs_button":
            self.view_logs()
        elif event.button.id == "install_button":
            self.run_in_thread(self._install_server_blocking)
        elif event.button.id == "uninstall_button":
            self.run_in_thread(self._uninstall_server_blocking)
        elif event.button.id == "set_env_button":
            self.set_env_var()
        elif event.button.id == "clear_env_button":
            self.clear_env_var()
        elif event.button.id == "launch_chat_button":
            self.launch_chat()
        elif event.button.id == "set_custom_file_button":
            self.set_custom_servers_file()

    def set_custom_servers_file(self):
        """Opens a prompt to set the path for the custom servers JSON file."""
        current_path = self.config.get('custom_servers_file', '')

        def on_submit(new_path: str):
            if os.path.exists(new_path) and new_path.endswith('.json'):
                self.config['custom_servers_file'] = new_path
                save_config(self.config)
                logging.info(f"Custom servers file set to: {new_path}")
                self.action_refresh_servers()  # Refresh the server list to include new servers
            elif not new_path: # Allow clearing the path
                self.config['custom_servers_file'] = ''
                save_config(self.config)
                logging.info("Custom servers file path cleared.")
                self.action_refresh_servers()
            else:
                logging.error(f"Invalid path or file type for custom servers file: {new_path}")
                self.bell()

        self.push_screen(
            InputScreen("Enter path to custom servers JSON file:", default_value=current_path),
            on_submit
        )

    def launch_chat(self):
        logging.info("Attempting to launch chat with all available servers")

        final_mcp_servers = {}

        # 1. Add running Smithery servers
        for name, (_, url) in self.running_processes.items():
            if url:
                final_mcp_servers[name] = {"type": "streamable_http", "url": url}

        # 2. Add servers from custom file
        custom_file_path = self.config.get('custom_servers_file')
        if custom_file_path and os.path.exists(custom_file_path):
            try:
                with open(custom_file_path, 'r') as f:
                    custom_data = json.load(f)
                    if isinstance(custom_data, dict) and "mcpServers" in custom_data:
                        # Merge custom servers, overwriting duplicates if any
                        final_mcp_servers.update(custom_data["mcpServers"])
            except (json.JSONDecodeError, IOError) as e:
                logging.error(f"Error reading custom servers file {custom_file_path}: {e}")
                self.bell()

        if not final_mcp_servers:
            self.bell()
            logging.warning("Launch chat called but no running or custom servers are available.")
            return

        def launch(model: str):
            if not model:
                return

            # This is the final configuration object to be written to the temp file
            final_config_for_ollmcp = {"mcpServers": final_mcp_servers}

            try:
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', prefix='mcp_servers_') as temp_config_file:
                    json.dump(final_config_for_ollmcp, temp_config_file, indent=2)
                    temp_config_path = temp_config_file.name

                terminal = self.config.get('terminal', 'konsole')
                ollama_host = self.config.get('ollama_host', 'http://localhost:11434')

                logging.info(f"Launching ollmcp with: terminal={terminal}, config={temp_config_path}, model={model}, host={ollama_host}")

                subprocess.Popen([terminal, '-e', 'ollmcp', '--servers-json', temp_config_path, '--model', model, '--host', ollama_host])

            except FileNotFoundError:
                logging.error(f"Could not find terminal '{terminal}'.")
                self.bell()
                self.server_logs["chat_error"] = f"Could not find terminal '{terminal}'."
                self.selected_server = "chat_error"
                self.view_logs()
            except Exception as e:
                logging.error(f"Failed to launch chat: {e}")
                self.bell()
                self.server_logs["chat_error"] = str(e)
                self.selected_server = "chat_error"
                self.view_logs()

        self.push_screen(InputScreen("Enter Ollama Model name:", default_value="llama3"), launch)

    def set_env_var(self):
        env_table = self.query_one("#env_table")
        if env_table.cursor_row < 0 or not self.selected_server:
            return

        var_name = env_table.get_row_at(env_table.cursor_row)[0]

        def set_value(value: str):
            logging.info(f"Setting env var {var_name} for {self.selected_server}")
            set_secret(self.selected_server, var_name, value)
            self.update_env_tab()

        self.push_screen(
            InputScreen(f"Enter value for {var_name}", is_secret(var_name)),
            set_value
        )

    def clear_env_var(self):
        env_table = self.query_one("#env_table")
        if env_table.cursor_row < 0 or not self.selected_server:
            return

        var_name = env_table.get_row_at(env_table.cursor_row)[0]
        logging.info(f"Clearing env var {var_name} for {self.selected_server}")
        delete_secret(self.selected_server, var_name)
        self.update_env_tab()

    def get_env_for_server(self, server):
        env = os.environ.copy()
        required_vars = get_server_env_vars(server)
        for var in required_vars:
            value = get_secret(server, var)
            if value:
                env[var] = value
        return env

    def start_server(self):
        if not self.selected_server:
            return

        server = self.selected_server
        logging.info(f"Starting server: {server}")
        env = self.get_env_for_server(server)
        process = subprocess.Popen(
            ['npx', '@smithery/cli', 'run', server, '--client', 'gemini-cli'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            bufsize=1,
            universal_newlines=True
        )
        self.running_processes[server] = (process, None)
        self.server_logs[server] = f"Starting server {server}...\n"
        self.action_refresh_servers()

    def stop_server(self):
        if not self.selected_server or self.selected_server not in self.running_processes:
            return

        server = self.selected_server
        logging.info(f"Stopping server: {server}")
        process, _ = self.running_processes.pop(server)
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        self.action_refresh_servers()

    def view_logs(self):
        if not self.selected_server:
            return

        log_view = self.query_one("#log_view")
        log_view.clear()
        log_view.write(self.server_logs.get(self.selected_server, "No logs for this server."))
        self.query_one(TabbedContent).active = "logs"

    def update_logs(self) -> None:
        for server, (process, url) in list(self.running_processes.items()):
            if process.stdout:
                while True:
                    line = process.stdout.readline()
                    if line:
                        self.server_logs[server] += line
                        if url is None:
                            match = re.search(r'Listening on (http://localhost:\d+)', line)
                            if match:
                                new_url = match.group(1)
                                self.running_processes[server] = (process, new_url)
                                self.action_refresh_servers()
                        if self.selected_server == server and self.query_one(TabbedContent).active == "logs":
                            self.query_one("#log_view").write(line)
                    else:
                        break

    def install_server_from_registry(self):
        if not self.selected_registry_server:
            return

        logging.info(f"Installing server: {self.selected_registry_server}")
        try:
            install_server(self.selected_registry_server)
            self.action_refresh_servers()
        except Exception as e:
            logging.error(f"Error installing server: {e}")
            self.bell()
            self.server_logs["install_error"] = str(e)
            self.selected_server = "install_error"
            self.view_logs()

    def uninstall_selected_server(self):
        if not self.selected_server:
            return

        logging.info(f"Uninstalling server: {self.selected_server}")
        try:
            if self.selected_server in self.running_processes:
                self.stop_server()
            uninstall_server(self.selected_server)
            self.action_refresh_servers()
            self.selected_server = None
            self.update_installed_buttons()
            self.update_env_tab()
        except Exception as e:
            logging.error(f"Error uninstalling server: {e}")
            self.bell()
            self.server_logs["uninstall_error"] = str(e)
            self.selected_server = "uninstall_error"
            self.view_logs()


def main():
    app = MCPCentralTUI()
    app.run()

if __name__ == "__main__":
    main()
