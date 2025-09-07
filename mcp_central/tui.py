import subprocess
import re
import logging
import json
import tempfile
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, DataTable, TabbedContent, TabPane, Button, Log, Input, Label
from textual.containers import Horizontal, Vertical, Container
from rich.panel import Panel
from .utils import list_installed_servers, get_registry_servers, install_server, uninstall_server, get_server_env_vars
from .config import load_config, save_config, get_secret, set_secret, delete_secret, is_secret, init_keyring
import os
import ollama
from contextlib import AsyncExitStack

# Imports from the mcp-client-for-ollama codebase
from mcp_client_for_ollama.server.connector import ServerConnector
from mcp_client_for_ollama.models.manager import ModelManager
from mcp_client_for_ollama.tools.manager import ToolManager
from mcp_client_for_ollama.utils.streaming import StreamingManager
from mcp_client_for_ollama.utils.tool_display import ToolDisplayManager
from mcp_client_for_ollama.utils.hil_manager import HumanInTheLoopManager

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


class MCPCentralTUI(App):
    """A Textual application to manage MCP servers."""

    BINDINGS = [
        ("d", "toggle_dark", "Toggle dark mode"),
        ("r", "refresh_servers", "Refresh Installed"),
        ("f5", "refresh_registry", "Refresh Registry"),
        ("a", "set_api_key", "Set API Key"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        # mcp-central state
        self.running_processes = {}  # server_name: (process, url)
        self.server_logs = {} # server_name: logs
        self.selected_server = None
        self.selected_registry_server = None
        self.config = load_config()

        # ollmcp state and managers
        self.exit_stack = AsyncExitStack()
        self.ollama = ollama.AsyncClient(host=self.config.get('ollama_host', 'http://localhost:11434'))
        self.server_connector = ServerConnector(self.exit_stack, self.console)
        self.model_manager = ModelManager(console=self.console, default_model="llama3", ollama=self.ollama) # Hardcode default model for now
        self.tool_manager = ToolManager(console=self.console, server_connector=self.server_connector)
        self.streaming_manager = StreamingManager(console=self.console)
        self.tool_display_manager = ToolDisplayManager(console=self.console)
        self.hil_manager = HumanInTheLoopManager(console=self.console)
        self.chat_history = []
        self.chat_sessions = {}

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
                    with Horizontal():
                        yield Button("Install Server", id="install_button", disabled=True)
                        yield Button("Set API Key", id="set_api_key_button")
            with TabPane("Environment", id="env"):
                yield DataTable(id="env_table")
                with Horizontal():
                    yield Button("Set Value", id="set_env_button", disabled=True)
                    yield Button("Clear Value", id="clear_env_button", disabled=True)
            with TabPane("Logs", id="logs"):
                yield Log(id="log_view")
            with TabPane("Chat", id="chat"):
                yield Log(id="chat_log")
                yield Input(placeholder="Enter your query...", id="chat_input")
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        logging.info("App mounted successfully.")
        init_keyring()
        logging.info("Keyring initialized.")
        self.action_refresh_servers()
        self.set_interval(1, self.update_logs)
        self.action_refresh_registry()
        logging.info("Initial data refresh actions called.")
        # Pass the textual log widget to the streaming manager now that it's mounted
        self.streaming_manager.textual_log = self.query_one("#chat_log")

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
        smithery_servers = []
        try:
            # Get servers from Smithery
            smithery_servers = list_installed_servers()
            servers.update(smithery_servers)
            logging.info(f"Successfully fetched {len(smithery_servers)} servers from Smithery: {smithery_servers}")
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

    def action_refresh_servers(self) -> None:
        """An action to refresh the list of installed servers."""
        logging.info("Action: Refreshing installed servers.")
        table = self.query_one("#server_table")
        table.clear(columns=True)
        table.add_columns("Server Name", "Status", "Source")

        all_servers = self.get_all_servers()
        # The command might return a single-element list with a message, filter that out.
        if len(all_servers) == 1 and "No installed servers found" in all_servers[0]:
            all_servers = []

        smithery_servers = {s for s in all_servers if "No installed servers found" not in s} # Re-evaluate true smithery servers after filtering

        for server in all_servers:
            status = "Running" if server in self.running_processes else "N/A"
            source = "Smithery" if server in smithery_servers else "Custom"
            # For Smithery servers, we know the status
            if source == "Smithery":
                status = "Running" if server in self.running_processes else "Stopped"

            table.add_row(server, status, source)
        self.update_installed_buttons()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "registry_search":
            self.action_refresh_registry(event.value)
        elif event.input.id == "chat_input":
            query = event.value
            event.input.clear()
            self.query_one("#chat_log").write(f"> {query}")
            await self.process_chat_query(query)

    async def process_chat_query(self, query: str):
        """Process a query using Ollama and available tools, adapted for Textual."""
        log = self.query_one("#chat_log")
        try:
            messages = [{"role": "user", "content": query}]
            # Note: Context retention from self.chat_history is not implemented here for simplicity
            # but could be added by iterating over self.chat_history and appending messages.

            enabled_tool_objects = self.tool_manager.get_enabled_tool_objects()
            available_tools = [{
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema
                }
            } for tool in enabled_tool_objects]

            if not available_tools:
                log.write("[yellow]Warning: No tools are enabled. Model will respond without tool access.[/yellow]")

            model = self.model_manager.get_current_model()
            model_options = {} # Simplified for now

            chat_params = {
                "model": model,
                "messages": messages,
                "stream": True,
                "tools": available_tools,
                "options": model_options
            }

            stream = await self.ollama.chat(**chat_params)

            response_text, tool_calls, metrics = await self.streaming_manager.process_streaming_response(
                stream, print_response=True, thinking_mode=False, show_thinking=False, show_metrics=False
            )

            if tool_calls:
                log.write("\n--- Tool Calls ---")
                for tool in tool_calls:
                    tool_name = tool.function.name
                    tool_args = tool.function.arguments
                    server_name, actual_tool_name = tool_name.split('.', 1) if '.' in tool_name else (None, tool_name)

                    if not server_name or server_name not in self.chat_sessions:
                        log.write(f"[red]Error: Unknown server for tool {tool_name}[/red]")
                        continue

                    log.write(f"Calling tool: {tool_name} with args: {tool_args}")

                    result = await self.chat_sessions[server_name].call_tool(actual_tool_name, tool_args)
                    tool_response = f"{result.content[0].text}"
                    log.write(f"Tool response: {tool_response}")

                    messages.append({
                        "role": "tool",
                        "content": tool_response,
                        "name": tool_name
                    })

                chat_params_followup = {
                    "model": model, "messages": messages, "stream": True, "options": model_options
                }
                stream = await self.ollama.chat(**chat_params_followup)
                response_text, _, _ = await self.streaming_manager.process_streaming_response(stream)

            self.chat_history.append({"query": query, "response": response_text})
            log.write("\n---")

        except Exception as e:
            logging.error(f"Error processing chat query: {e}", exc_info=True)
            log.write(Panel(f"[bold red]Error:[/bold red] {str(e)}", title="Exception", border_style="red"))

    def action_refresh_registry(self, query=""):
        logging.info(f"Action: Refreshing registry with query: '{query}'")
        table = self.query_one("#registry_table")
        table.clear(columns=True)
        table.add_columns("Name", "Description")
        try:
            servers = get_registry_servers(self.config.get('api_key'), query)
            logging.info(f"Successfully fetched {len(servers)} servers from registry.")
            for server in servers:
                table.add_row(server['qualifiedName'], server['description'])
        except Exception as e:
            logging.error(f"Error refreshing registry: {e}")
            self.bell()
            self.server_logs["registry_error"] = str(e)
            self.selected_server = "registry_error"
            self.view_logs()


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
        elif event.button.id == "set_api_key_button":
            self.action_set_api_key()

    def action_set_api_key(self):
        """Shows a screen to set the Smithery API key."""
        current_key = self.config.get('api_key', '')

        def on_submit(key: str):
            self.config['api_key'] = key
            save_config(self.config)
            logging.info("API key has been set.")
            self.action_refresh_registry()

        self.push_screen(
            InputScreen("Enter your Smithery Registry API Key:", is_password=True, default_value=current_key),
            on_submit
        )

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
            self.model_manager.set_model(model)
            self.run_worker(self.connect_and_start_chat(final_mcp_servers), exclusive=True)

        self.push_screen(InputScreen("Enter Ollama Model name:", default_value="llama3"), launch)

    async def connect_and_start_chat(self, server_configs):
        """Connect to servers and switch to chat tab."""
        log = self.query_one("#chat_log")
        log.clear()
        log.write("Connecting to servers...")
        try:
            # This logic is adapted from ollmcp's connect_to_servers
            sessions, available_tools, enabled_tools = await self.server_connector.connect_with_config(server_configs)
            self.chat_sessions = sessions
            self.tool_manager.set_available_tools(available_tools)
            self.tool_manager.set_enabled_tools(enabled_tools)
            log.write("Connection successful. Ready to chat.")
            self.query_one(TabbedContent).active = "chat"
            self.query_one("#chat_input").focus()
        except Exception as e:
            logging.error(f"Failed to connect to servers for chat: {e}", exc_info=True)
            log.write(Panel(f"[bold red]Failed to connect to servers:[/bold red]\n{e}", title="Connection Error"))

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
