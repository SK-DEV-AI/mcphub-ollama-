import subprocess
import re
import requests
import os
from .config import load_config

def run_smithery_command(cmd):
    try:
        result = subprocess.run(['npx', '@smithery/cli'] + cmd, capture_output=True, text=True, check=False, env=os.environ)
        if result.return_code != 0:
            raise RuntimeError(result.stderr or result.stdout)
        return result.stdout.strip()
    except FileNotFoundError:
        raise RuntimeError("Smithery CLI not found. Is Node.js and npx installed and in your PATH?")
    except Exception as e:
        raise RuntimeError(f"Smithery CLI error: {str(e)}")

def list_installed_servers():
    try:
        output = run_smithery_command(['list', 'servers'])
        return output.splitlines() if output else []
    except RuntimeError:
        return []

def install_server(package):
    run_smithery_command(['install', package])

def uninstall_server(package):
    run_smithery_command(['uninstall', package])

def get_registry_servers(api_key, query=''):
    config = load_config()
    url = "https://registry.smithery.ai/servers"
    headers = {"Authorization": f"Bearer {api_key or config.get('api_key', '')}"}
    params = {"q": query}
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        return data.get('servers', [])
    except requests.RequestException as e:
        raise RuntimeError(f"Failed to fetch from registry: {e}")

def get_server_env_vars(server_id):
    try:
        output = run_smithery_command(['inspect', server_id])
        match = re.search(r'Required env: (.*)', output)
        if match:
            vars_str = match.group(1).strip()
            if vars_str:
                return [v.strip() for v in vars_str.split(',') if v.strip()]
        return []
    except RuntimeError:
        return []
