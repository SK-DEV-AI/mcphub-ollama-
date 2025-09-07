import asyncio
import os
from contextlib import AsyncExitStack
from typing import List, Optional

import ollama

# We will need to adjust these imports as we refactor
from .chat_client.config.manager import ConfigManager
from .chat_client.utils.constants import DEFAULT_MODEL, DEFAULT_OLLAMA_HOST
from .chat_client.server.connector import ServerConnector
from .chat_client.models.manager import ModelManager
from .chat_client.models.config_manager import ModelConfigManager
from .chat_client.tools.manager import ToolManager
from .chat_client.utils.streaming import StreamingManager
from .chat_client.utils.tool_display import ToolDisplayManager
from .chat_client.utils.hil_manager import HumanInTheLoopManager

class ChatService:
    """A service to handle the logic of the chat client."""

    def __init__(self, app, hil_callback, model: str = DEFAULT_MODEL, host: str = DEFAULT_OLLAMA_HOST):
        self.app = app
        self.hil_callback = hil_callback
        self.ollama = ollama.AsyncClient(host=host)
        self.chat_history = []
        self.sessions = {}
        self.exit_stack = AsyncExitStack()

        # Configurable settings
        self.retain_context = True
        self.thinking_mode = True
        self.show_thinking = False
        self.show_tool_execution = True
        self.show_metrics = False
        self.actual_token_count = 0

        # Managers
        self.config_manager = ConfigManager(console=None)
        self.model_manager = ModelManager(console=None, default_model=model, ollama=self.ollama)
        self.model_config_manager = ModelConfigManager(console=None)
        self.server_connector = ServerConnector(self.exit_stack, console=None)
        self.tool_manager = ToolManager(console=None, server_connector=self.server_connector)
        self.streaming_manager = StreamingManager(console=None)

    def save_configuration(self, config_name=None) -> str:
        """Save current tool configuration and model settings to a file"""
        # Build config data
        config_data = {
            "model": self.model_manager.get_current_model(),
            "enabledTools": self.tool_manager.get_enabled_tools(),
            "contextSettings": {
                "retainContext": self.retain_context
            },
            "modelSettings": {
                "thinkingMode": self.thinking_mode,
                "showThinking": self.show_thinking
            },
            "modelConfig": self.model_config_manager.get_config(),
            "displaySettings": {
                "showToolExecution": self.show_tool_execution,
                "showMetrics": self.show_metrics
            },
            "hilSettings": {
                "enabled": True # HIL is now TUI-driven, but we can save a placeholder
            }
        }
        success = self.config_manager.save_configuration(config_data, config_name)
        return f"Configuration '{config_name or 'default'}' saved." if success else "Failed to save configuration."

    def load_configuration(self, config_name=None) -> str:
        """Load tool configuration and model settings from a file"""
        config_data = self.config_manager.load_configuration(config_name)

        if not config_data:
            return f"Configuration '{config_name or 'default'}' not found."

        # Apply the loaded configuration
        if "model" in config_data:
            self.model_manager.set_model(config_data["model"])

        if "enabledTools" in config_data:
            available_tool_names = {tool.name for tool in self.tool_manager.get_available_tools()}
            for tool_name, enabled in config_data["enabledTools"].items():
                if tool_name in available_tool_names:
                    self.tool_manager.set_tool_status(tool_name, enabled)
                    self.server_connector.set_tool_status(tool_name, enabled)

        if "contextSettings" in config_data:
            self.retain_context = config_data["contextSettings"].get("retainContext", True)

        if "modelSettings" in config_data:
            self.thinking_mode = config_data["modelSettings"].get("thinkingMode", True)
            self.show_thinking = config_data["modelSettings"].get("showThinking", False)

        if "modelConfig" in config_data:
            self.model_config_manager.set_config(config_data["modelConfig"])

        if "displaySettings" in config_data:
            self.show_tool_execution = config_data["displaySettings"].get("showToolExecution", True)
            self.show_metrics = config_data["displaySettings"].get("showMetrics", False)

        return f"Configuration '{config_name or 'default'}' loaded successfully."

    async def get_available_models(self) -> list:
        """Get a list of available Ollama models."""
        return await self.model_manager.list_ollama_models()

    def set_model(self, model_name: str):
        """Set the current model."""
        self.model_manager.set_model(model_name)

    def set_enabled_tools(self, enabled_tools: dict):
        """Set the enabled status of tools."""
        self.tool_manager.set_enabled_tools(enabled_tools)

    def set_model_config(self, config: dict):
        """Set the model configuration."""
        self.model_config_manager.set_config(config)

    def clear_history(self) -> str:
        """Clears the chat history."""
        count = len(self.chat_history)
        self.chat_history.clear()
        self.actual_token_count = 0
        return f"Chat history cleared ({count} messages)."

    async def connect_to_servers(self, server_urls=None, config_path=None):
        """Connect to one or more MCP servers using the ServerConnector"""
        # Disconnect from any existing servers before connecting to new ones
        await self.server_connector.disconnect_all_servers()

        sessions, available_tools, enabled_tools = await self.server_connector.connect_to_servers(
            server_urls=server_urls,
            config_path=config_path,
        )

        # Store the results
        self.sessions = sessions
        self.tool_manager.set_available_tools(available_tools)
        self.tool_manager.set_enabled_tools(enabled_tools)


    async def supports_thinking_mode(self) -> bool:
        """Check if the current model supports thinking mode by checking its capabilities

        Returns:
            bool: True if the current model supports thinking mode, False otherwise
        """
        try:
            current_model = self.model_manager.get_current_model()
            # Query the model's capabilities using ollama.show()
            model_info = await self.ollama.show(current_model)

            # Check if the model has 'thinking' capability
            if 'capabilities' in model_info and model_info['capabilities']:
                return 'thinking' in model_info['capabilities']

            return False
        except Exception:
            # If we can't determine capabilities, assume no thinking support
            return False

    async def process_query(self, query: str) -> str:
        """Process a query using Ollama and available tools"""
        # Create base message with current query
        current_message = {
            "role": "user",
            "content": query
        }

        # Build messages array based on context retention setting
        if self.retain_context and self.chat_history:
            # Include previous messages for context
            messages = []
            for entry in self.chat_history:
                # Add user message
                messages.append({
                    "role": "user",
                    "content": entry["query"]
                })
                # Add assistant response
                messages.append({
                    "role": "assistant",
                    "content": entry["response"]
                })
            # Add the current query
            messages.append(current_message)
        else:
            # No context retention - just use current query
            messages = [current_message]

        # Add system prompt if one is configured
        system_prompt = self.model_config_manager.get_system_prompt()
        if system_prompt:
            messages.insert(0, {
                "role": "system",
                "content": system_prompt
            })

        # Get enabled tools from the tool manager
        enabled_tool_objects = self.tool_manager.get_enabled_tool_objects()

        if not enabled_tool_objects:
            # self.console.print("[yellow]Warning: No tools are enabled. Model will respond without tool access.[/yellow]")
            pass

        available_tools = [{
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema
            }
        } for tool in enabled_tool_objects]

        # Get current model from the model manager
        model = self.model_manager.get_current_model()

        # Get model options in Ollama format
        model_options = self.model_config_manager.get_ollama_options()

        # Prepare chat parameters
        chat_params = {
            "model": model,
            "messages": messages,
            "stream": True,
            "tools": available_tools,
            "options": model_options
        }

        # Add thinking parameter if thinking mode is enabled and model supports it
        if await self.supports_thinking_mode():
            chat_params["think"] = self.thinking_mode

        # Initial Ollama API call with the query and available tools
        stream = await self.ollama.chat(**chat_params)

        # Process the streaming response with thinking mode support
        response_text = ""
        tool_calls = []
        response_text, tool_calls, metrics = await self.streaming_manager.process_streaming_response(
            stream,
            thinking_mode=self.thinking_mode,
            show_thinking=self.show_thinking,
            show_metrics=self.show_metrics
        )

        # Update actual token count from metrics if available
        if metrics and metrics.get('eval_count'):
            self.actual_token_count += metrics['eval_count']
        # Check if there are any tool calls in the response
        if len(tool_calls) > 0 and self.tool_manager.get_enabled_tool_objects():
            for tool in tool_calls:
                tool_name = tool.function.name
                tool_args = tool.function.arguments

                # Parse server name and actual tool name from the qualified name
                server_name, actual_tool_name = tool_name.split('.', 1) if '.' in tool_name else (None, tool_name)

                if not server_name or server_name not in self.sessions:
                    # self.console.print(f"[red]Error: Unknown server for tool {tool_name}[/red]")
                    continue

                should_execute = await self.hil_callback(tool_name, tool_args)

                if not should_execute:
                    tool_response = "Tool call was skipped by user"
                    messages.append({
                        "role": "tool",
                        "content": tool_response,
                        "name": tool_name
                    })
                    continue

                # Call the tool on the specified server
                result = await self.sessions[server_name]["session"].call_tool(actual_tool_name, tool_args)
                tool_response = f"{result.content[0].text}"

                messages.append({
                    "role": "tool",
                    "content": tool_response,
                    "name": tool_name
                })

            # Get stream response from Ollama with the tool results
            chat_params_followup = {
                "model": model,
                "messages": messages,
                "stream": True,
                "options": model_options
            }

            # Add thinking parameter if thinking mode is enabled and model supports it
            if await self.supports_thinking_mode():
                chat_params_followup["think"] = self.thinking_mode

            stream = await self.ollama.chat(**chat_params_followup)

            # Process the streaming response with thinking mode support
            response_text, _, followup_metrics = await self.streaming_manager.process_streaming_response(
                stream,
                thinking_mode=self.thinking_mode,
                show_thinking=self.show_thinking,
                show_metrics=self.show_metrics
            )

            # Update actual token count from followup metrics if available
            if followup_metrics and followup_metrics.get('eval_count'):
                self.actual_token_count += followup_metrics['eval_count']

        if not response_text:
            # self.console.print("[red]No content response received.[/red]")
            response_text = ""

        # Append query and response to chat history
        self.chat_history.append({"query": query, "response": response_text})

        return response_text
