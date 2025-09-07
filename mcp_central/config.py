import json
from pathlib import Path
import keyring
import os
import keyring.backends.fail

def init_keyring():
    """
    Initializes the keyring backend. If D-Bus is not available, it sets
    the backend to the 'fail' backend to prevent hanging.
    """
    if 'DBUS_SESSION_BUS_ADDRESS' not in os.environ:
        print("Warning: D-Bus session address not found. Keyring will be disabled.")
        kr = keyring.backends.fail.Keyring()
        keyring.set_keyring(kr)

CONFIG_DIR = Path.home() / '.config' / 'mcp-central'
CONFIG_FILE = CONFIG_DIR / 'settings.json'
SERVICE_NAME = 'mcp-central'

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            # Ensure new keys have default values if they are missing
            config.setdefault('custom_servers_file', '')
            return config
    return {"servers": [], "api_key": "", "ollama_host": "http://localhost:11434", "terminal": "konsole", "custom_servers_file": ""}

def save_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

def get_secret(server_name, var_name):
    return keyring.get_password(SERVICE_NAME, f"{server_name}_{var_name}")

def set_secret(server_name, var_name, value):
    keyring.set_password(SERVICE_NAME, f"{server_name}_{var_name}", value)

def delete_secret(server_name, var_name):
    try:
        keyring.delete_password(SERVICE_NAME, f"{server_name}_{var_name}")
    except keyring.errors.PasswordNotFoundError:
        pass # It's okay if the secret doesn't exist

def is_secret(var_name):
    return any(word in var_name.lower() for word in ['key', 'token', 'secret', 'password'])
