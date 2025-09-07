import subprocess
import re
import logging
import json
import tempfile
import webbrowser
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, DataTable, TabbedContent, TabPane, Button, Log, Input, Label, Static, LoadingIndicator
from textual.containers import Horizontal, Vertical, Container
from textual import work
from .utils import list_installed_servers, get_registry_servers, install_server, uninstall_server, get_server_env_vars
from .config import load_config, save_config, get_secret, set_secret, delete_secret, is_secret, init_keyring
import os

logging.basicConfig(filename="app.log", level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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

class APIKeyScreen(Screen):
    """A screen to get the Smithery API key from the user."""

    def compose(self) -> ComposeResult:
        yield Container(
            Static("Smithery API Key Required", classes="title"),
            Static("Please enter your Smithery API key to access the registry."),
            Static("You can get a key from: https://smithery.ai/account/api-keys"),
            Input(password=True, id="api_key_input"),
            Horizontal(
                Button("Get Key", id="get_key_button", variant="primary"),
                Button("Submit", id="submit_api_key_button", variant="success"),
            ),
            id="api_key_dialog"
        )

    def on_mount(self) -> None:
        self.query_one("#api_key_input").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "get_key_button":
            webbrowser.open("https://smithery.ai/account/api-keys")
        elif event.button.id == "submit_api_key_button":
            api_key = self.query_one("#api_key_input").value
            if api_key:
                self.dismiss(api_key)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value:
            self.dismiss(event.value)

class MCPCentralTUI(App):
    """A Textual application to manage MCP servers."""

    CSS = """
    #main_container.hidden {
        display: none;
    }
    #loading_container {
        align: center middle;
    }
    """

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
        yield Container(
            LoadingIndicator(),
            Static("Loading, please wait...", id="loading_label"),
            id="loading_container"
        )
        with Container(id="main_container", classes="hidden"):
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
        logging.info("App started. Initializing...")
        init_keyring()
        logging.info("Keyring initialized.")
        self.query_api_key()


    def query_api_key(self) -> None:
        """Check for API key and prompt user if missing."""
        logging.info("Checking for Smithery API key.")
        if not self.config.get('api_key'):
            logging.info("Smithery API key not found, prompting user.")
            self.push_screen(APIKeyScreen(), self.handle_api_key)
        else:
            logging.info("Smithery API key found.")
            self.finish_startup()

    def handle_api_key(self, api_key: str) -> None:
        """Callback to handle the API key from the user."""
        if api_key:
            logging.info("Received API key from user.")
            self.config['api_key'] = api_key
            save_config(self.config)
            self.finish_startup()
        else:
            logging.warning("User dismissed API key screen without providing a key.")
            self.notify("Smithery API key is required to browse the registry.", severity="warning")
            self.finish_startup()

    def finish_startup(self) -> None:
        """The rest of the startup sequence."""
        logging.info("Finishing startup sequence. Starting background worker.")
        self.set_interval(1, self.update_logs)
        self.load_initial_data()

    @work(exclusive=True)
    def load_initial_data(self) -> None:
        """Load initial server and registry data in the background."""
        logging.info("Background worker started for initial data load.")

        # Fetch installed servers
        try:
            installed_servers = self.get_all_servers()
            logging.info(f"Worker found {len(installed_servers)} installed servers.")
        except Exception as e:
            logging.error(f"Worker error fetching installed servers: {e}", exc_info=True)
            installed_servers = [f"Error: {e}"]

        # Fetch registry servers
        try:
            api_key = self.config.get('api_key')
            if api_key:
                registry_servers = get_registry_servers(api_key, "")
                logging.info(f"Worker found {len(registry_servers)} registry servers.")
            else:
                registry_servers = []
                logging.info("Worker skipping registry search, no API key.")
        except Exception as e:
            logging.error(f"Worker error fetching registry servers: {e}", exc_info=True)
            registry_servers = [{"qualifiedName": f"Error: {e}", "description": ""}]

        # Schedule UI update on the main thread
        self.call_from_thread(self.update_ui_with_loaded_data, installed_servers, registry_servers)

    def update_ui_with_loaded_data(self, installed_servers: list, registry_servers: list) -> None:
        """Update the UI with data loaded from the background worker."""
        logging.info("Updating UI with data from background worker.")

        # Populate installed servers table
        table = self.query_one("#server_table")
        table.clear(columns=True)
        table.add_columns("Server Name", "Status", "Source")
        if installed_servers:
            try:
                smithery_servers = set(list_installed_servers()) # Re-list to determine source accurately
                for server in installed_servers:
                    if server.startswith("Error:"):
                        table.add_row(server, "Error", "Error")
                        continue
                    status = "Running" if server in self.running_processes else "N/A"
                    source = "Smithery" if server in smithery_servers else "Custom"
                    if source == "Smithery":
                        status = "Running" if server in self.running_processes else "Stopped"
                    table.add_row(server, status, source)
            except Exception as e:
                logging.error(f"Error populating installed servers table: {e}", exc_info=True)
                table.add_row(f"Error loading servers: {e}", "Error", "Error")


        # Populate registry table
        table = self.query_one("#registry_table")
        table.clear(columns=True)
        table.add_columns("Name", "Description")
        if registry_servers:
            for server in registry_servers:
                table.add_row(server['qualifiedName'], server.get('description', ''))

        # Hide loading indicator and show main content
        self.query_one("#loading_container").display = False
        self.query_one("#main_container").remove_class("hidden")
        logging.info("UI update complete. Application is ready.")


    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Called when a row in the DataTable is selected."""
        if event.data_table.id == "server_table":
            if event.data_table.row_count > 0 and event.cursor_row is not None:
                self.selected_server = event.data_table.get_row_at(event.cursor_row)[0]
                self.update_installed_buttons()
                self.update_env_tab()
        elif event.data_table.id == "registry_table":
            if event.data_table.row_count > 0 and event.cursor_row is not None:
                self.selected_registry_server = event.data_table.get_row_at(event.cursor_row)[0]
                self.query_one("#install_button").disabled = False
        elif event.data_table.id == "env_table":
            if event.data_table.row_count > 0 and event.cursor_row is not None:
                self.query_one("#set_env_button").disabled = False
                self.query_one("#clear_env_button").disabled = False


    def update_installed_buttons(self):
        is_custom_server = False
        table = self.query_one("#server_table")
        if self.selected_server and table.is_valid_row_index(table.cursor_row):
            try:
                source = table.get_cell_at(table.cursor_coordinate, 2)
                is_custom_server = (source == "Custom")
            except IndexError:
                is_custom_server = False

        # Update context-sensitive buttons based on selected server
        if self.selected_server:
            is_running = self.selected_server in self.running_processes
            self.query_one("#start_button").disabled = is_running or is_custom_server
            self.query_one("#stop_button").disabled = not is_running or is_custom_server
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
        custom_file_path = self.config.get('custom_servers_file')
        custom_file_exists = custom_file_path and os.path.exists(custom_file_path)
        self.query_one("#launch_chat_button").disabled = not (any_server_running_with_url or custom_file_exists)


    def update_env_tab(self):
        table = self.query_one("#env_table")
        table.clear(columns=True)
        self.query_one("#set_env_button").disabled = True
        self.query_one("#clear_env_button").disabled = True
        if self.selected_server:
            table.add_columns("Variable", "Value")
            try:
                required_vars = get_server_env_vars(self.selected_server)
                for var in required_vars:
                    value = get_secret(self.selected_server, var)
                    display_value = "(hidden)" if is_secret(var) and value else value or ""
                    table.add_row(var, display_value)
            except Exception as e:
                logging.error(f"Error updating env tab for server {self.selected_server}: {e}")
                self.notify(f"Could not get env vars for {self.selected_server}.", severity="error")


    def get_all_servers(self) -> list[str]:
        """Gets a unified list of servers from Smithery CLI and the custom JSON file."""
        servers = set()
        try:
            # Get servers from Smithery
            servers.update(list_installed_servers())
        except Exception as e:
            logging.error(f"Error fetching Smithery servers: {e}")
            self.notify(f"Error fetching Smithery servers: {e}", severity="error", timeout=10)

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
                self.notify(error_message, severity="error", timeout=10)

        return sorted(list(servers))

    def action_refresh_servers(self) -> None:
        """An action to refresh the list of installed servers."""
        self.query_one("#loading_container").display = True
        self.query_one("#main_container").add_class("hidden")
        self.refresh_servers_worker()

    @work(exclusive=True, group="refresh")
    def refresh_servers_worker(self):
        logging.info("Worker refreshing installed servers list.")
        try:
            installed_servers = self.get_all_servers()
        except Exception as e:
            installed_servers = [f"Error: {e}"]
        self.call_from_thread(self.update_servers_table, installed_servers)

    def update_servers_table(self, installed_servers: list) -> None:
        """Update the installed servers table with new data."""
        table = self.query_one("#server_table")
        current_selection = self.selected_server
        table.clear(columns=True)
        table.add_columns("Server Name", "Status", "Source")
        try:
            smithery_servers = set(list_installed_servers())
            for server in installed_servers:
                if server.startswith("Error:"):
                    table.add_row(server, "Error", "Error")
                    continue
                status = "Running" if server in self.running_processes else "N/A"
                source = "Smithery" if server in smithery_servers else "Custom"
                if source == "Smithery":
                    status = "Running" if server in self.running_processes else "Stopped"
                table.add_row(server, status, source)

            if current_selection in installed_servers:
                for i, row in enumerate(table.rows):
                    if row[0] == current_selection:
                        table.cursor_row = i
                        break
        except Exception as e:
            logging.error(f"Failed to refresh servers table: {e}")
            self.notify("Could not refresh server list.", severity="error")

        self.query_one("#loading_container").display = False
        self.query_one("#main_container").remove_class("hidden")
        self.update_installed_buttons()


    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "registry_search":
            self.action_refresh_registry(event.value)

    def action_refresh_registry(self, query: str = "") -> None:
        """An action to refresh the list of registry servers."""
        self.query_one("#loading_container").display = True
        self.query_one("#main_container").add_class("hidden")
        self.refresh_registry_worker(query)

    @work(exclusive=True, group="refresh")
    def refresh_registry_worker(self, query: str):
        logging.info(f"Worker refreshing registry with query: '{query}'")
        if not self.config.get('api_key'):
            self.call_from_thread(self.notify, "Smithery API key not set.", severity="warning")
            self.call_from_thread(self.update_registry_table, [])
            return

        try:
            servers = get_registry_servers(self.config.get('api_key'), query)
            self.call_from_thread(self.update_registry_table, servers)
        except Exception as e:
            error_msg = f"Error refreshing registry: {e}"
            logging.error(error_msg)
            self.call_from_thread(self.notify, error_msg, severity="error", timeout=10)
            self.call_from_thread(self.update_registry_table, [])

    def update_registry_table(self, servers: list) -> None:
        """Update the registry table with new data."""
        table = self.query_one("#registry_table")
        table.clear(columns=True)
        table.add_columns("Name", "Description")
        if servers:
            for server in servers:
                table.add_row(server['qualifiedName'], server.get('description', ''))
        self.query_one("#loading_container").display = False
        self.query_one("#main_container").remove_class("hidden")


    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Called when a button is pressed."""
        if event.button.id == "start_button":
            self.start_server()
        elif event.button.id == "stop_button":
            self.stop_server()
        elif event.button.id == "logs_button":
            self.view_logs()
        elif event.button.id == "install_button":
            self.install_server_from_registry()
        elif event.button.id == "uninstall_button":
            self.uninstall_selected_server()
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
            if not new_path: # Allow clearing the path
                self.config['custom_servers_file'] = ''
                save_config(self.config)
                logging.info("Custom servers file path cleared.")
                self.action_refresh_servers()
            elif os.path.exists(new_path) and new_path.endswith('.json'):
                self.config['custom_servers_file'] = new_path
                save_config(self.config)
                logging.info(f"Custom servers file set to: {new_path}")
                self.action_refresh_servers()
            else:
                logging.error(f"Invalid path or file type for custom servers file: {new_path}")
                self.notify("Invalid path or file type. Must be a .json file.", severity="error")

        self.push_screen(
            InputScreen("Enter path to custom servers JSON file (or leave blank to clear):", default_value=current_path),
            on_submit
        )

    def launch_chat(self):
        logging.info("Attempting to launch chat with all available servers.")

        final_mcp_servers = {}

        # 1. Add running Smithery servers with URLs
        for name, (_, url) in self.running_processes.items():
            if url:
                final_mcp_servers[name] = {"type": "streamable_http", "url": url}
                logging.info(f"Adding running Smithery server to chat launch: {name}")

        # 2. Add servers from custom file
        custom_file_path = self.config.get('custom_servers_file')
        if custom_file_path and os.path.exists(custom_file_path):
            try:
                with open(custom_file_path, 'r') as f:
                    custom_data = json.load(f)
                    if isinstance(custom_data, dict) and "mcpServers" in custom_data:
                        final_mcp_servers.update(custom_data["mcpServers"])
                        logging.info(f"Added {len(custom_data['mcpServers'])} servers from custom file: {custom_file_path}")
            except (json.JSONDecodeError, IOError) as e:
                logging.error(f"Error reading custom servers file {custom_file_path}: {e}")
                self.notify(f"Error reading custom servers file: {e}", severity="error")

        if not final_mcp_servers:
            self.notify("No running or custom servers available to launch chat.", severity="warning")
            logging.warning("Launch chat called but no servers are available.")
            return

        def launch(model: str):
            if not model:
                return

            final_config_for_ollmcp = {"mcpServers": final_mcp_servers}

            try:
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', prefix='mcp_servers_') as temp_config_file:
                    json.dump(final_config_for_ollmcp, temp_config_file, indent=2)
                    temp_config_path = temp_config_file.name

                logging.info(f"Created temporary server config for ollmcp at: {temp_config_path}")

                terminal = self.config.get('terminal', 'konsole')
                ollama_host = self.config.get('ollama_host', 'http://localhost:11434')

                command = [terminal, '-e', 'ollmcp', '--servers-json', temp_config_path, '--model', model, '--host', ollama_host]
                logging.info(f"Executing command: {' '.join(command)}")

                subprocess.Popen(command)

            except FileNotFoundError:
                error_msg = f"Could not find terminal '{terminal}'. Please install it or configure a different one."
                logging.error(error_msg)
                self.notify(error_msg, severity="error", timeout=10)
            except Exception as e:
                error_msg = f"Failed to launch chat: {e}"
                logging.error(error_msg, exc_info=True)
                self.notify(error_msg, severity="error", timeout=10)

        self.push_screen(InputScreen("Enter Ollama Model name:", default_value="llama3"), launch)


    def set_env_var(self):
        env_table = self.query_one("#env_table")
        if not env_table.is_valid_row_index(env_table.cursor_row) or not self.selected_server:
            return

        var_name = env_table.get_row_at(env_table.cursor_row)[0]

        def set_value(value: str):
            logging.info(f"Setting env var '{var_name}' for server '{self.selected_server}'")
            set_secret(self.selected_server, var_name, value)
            self.update_env_tab()

        self.push_screen(
            InputScreen(f"Enter value for {var_name}", is_password=is_secret(var_name)),
            set_value
        )

    def clear_env_var(self):
        env_table = self.query_one("#env_table")
        if not env_table.is_valid_row_index(env_table.cursor_row) or not self.selected_server:
            return

        var_name = env_table.get_row_at(env_table.cursor_row)[0]
        logging.info(f"Clearing env var '{var_name}' for server '{self.selected_server}'")
        delete_secret(self.selected_server, var_name)
        self.update_env_tab()

    def get_env_for_server(self, server: str) -> dict:
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
        try:
            env = self.get_env_for_server(server)
            process = subprocess.Popen(
                ['npx', '@smithery/cli', 'run', server, '--client', 'gemini-cli'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, # Capture stderr separately
                text=True,
                env=env,
                bufsize=1,
                universal_newlines=True
            )
            self.running_processes[server] = (process, None)
            self.server_logs[server] = f"--- Starting server {server} ---\n"
            self.action_refresh_servers()
        except Exception as e:
            error_msg = f"Failed to start server {server}: {e}"
            logging.error(error_msg, exc_info=True)
            self.notify(error_msg, severity="error", timeout=10)

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
        log_view.write(self.server_logs.get(self.selected_server, "No logs available for this server."))
        self.query_one(TabbedContent).active = "logs"

    def update_logs(self) -> None:
        for server, (process, url) in list(self.running_processes.items()):
            # Read from stdout
            if process.stdout:
                for line in iter(process.stdout.readline, ''):
                    if not line: break
                    self.server_logs[server] += f"[stdout] {line}"
                    if url is None:
                        match = re.search(r'Listening on (http://localhost:\d+)', line)
                        if match:
                            new_url = match.group(1)
                            self.running_processes[server] = (process, new_url)
                            self.action_refresh_servers()
                            logging.info(f"Discovered URL for server {server}: {new_url}")
                    if self.selected_server == server and self.query_one(TabbedContent).active == "logs":
                        self.query_one("#log_view").write(line)

            # Read from stderr
            if process.stderr:
                for line in iter(process.stderr.readline, ''):
                    if not line: break
                    self.server_logs[server] += f"[stderr] {line}"
                    if self.selected_server == server and self.query_one(TabbedContent).active == "logs":
                        self.query_one("#log_view").write(line)


    def install_server_from_registry(self):
        if not self.selected_registry_server:
            return

        logging.info(f"Installing server: {self.selected_registry_server}")
        try:
            install_server(self.selected_registry_server)
            self.notify(f"Successfully installed {self.selected_registry_server}", severity="information")
            self.action_refresh_servers()
        except Exception as e:
            error_msg = f"Error installing server: {e}"
            logging.error(error_msg, exc_info=True)
            self.notify(error_msg, severity="error", timeout=10)


    def uninstall_selected_server(self):
        if not self.selected_server:
            return

        logging.info(f"Uninstalling server: {self.selected_server}")
        try:
            if self.selected_server in self.running_processes:
                self.stop_server()
            uninstall_server(self.selected_server)
            self.notify(f"Successfully uninstalled {self.selected_server}", severity="information")
            self.action_refresh_servers()
            self.selected_server = None
            self.update_installed_buttons()
            self.update_env_tab()
        except Exception as e:
            error_msg = f"Error uninstalling server: {e}"
            logging.error(error_msg, exc_info=True)
            self.notify(error_msg, severity="error", timeout=10)


def main():
    app = MCPCentralTUI()
    app.run()

if __name__ == "__main__":
    main()
