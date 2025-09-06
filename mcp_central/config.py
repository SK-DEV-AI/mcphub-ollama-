import json
from pathlib import Path
import keyring
import os

CONFIG_DIR = Path.home() / '.config' / 'mcp-central'
CONFIG_FILE = CONFIG_DIR / 'settings.json'
SERVICE_NAME = 'mcp-central'

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {"servers": [], "api_key": "", "ollama_host": "http://localhost:11434", "terminal": "konsole"}

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
