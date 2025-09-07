import pytest
from unittest.mock import MagicMock, AsyncMock
from mcp_client_for_ollama.client import MCPClient
from mcp_client_for_ollama.config.defaults import default_config

@pytest.fixture
def mock_ollama_client():
    """Fixture for a mocked Ollama client."""
    return AsyncMock()

@pytest.fixture
def client(mock_ollama_client):
    """Fixture for an MCPClient instance with mocked dependencies."""
    # Mock the rich console to prevent actual output during tests
    mock_console = MagicMock()

    # Create an instance of MCPClient
    mcp_client = MCPClient()
    mcp_client.console = mock_console
    mcp_client.ollama = mock_ollama_client

    # Mock the tool and server managers
    mcp_client.tool_manager = MagicMock()
    mcp_client.server_connector = MagicMock()
    mcp_client.hil_manager = MagicMock()

    return mcp_client

def test_reset_configuration(client):
    """Test that reset_configuration correctly resets all settings to their defaults."""
    # 1. Modify the configuration from the default values
    client.retain_context = False
    client.thinking_mode = False
    client.show_thinking = True
    client.show_tool_execution = False
    client.show_metrics = True
    client.hil_manager.is_enabled.return_value = False
    client.hil_manager.set_enabled(False)

    # 2. Call the reset_configuration method
    client.reset_configuration()

    # 3. Get the default configuration
    defaults = default_config()

    # 4. Assert that all the configuration settings are reset to their default values
    assert client.retain_context == defaults["contextSettings"]["retainContext"]
    assert client.thinking_mode == defaults["modelSettings"]["thinkingMode"]
    assert client.show_thinking == defaults["modelSettings"]["showThinking"]
    assert client.show_tool_execution == defaults["displaySettings"]["showToolExecution"]
    assert client.show_metrics == defaults["displaySettings"]["showMetrics"]
    client.hil_manager.set_enabled.assert_called_with(defaults["hilSettings"]["enabled"])
