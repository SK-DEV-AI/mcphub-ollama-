import asyncio
import re
import httpx
import os
from .config import load_config

async def run_smithery_command(cmd):
    try:
        command = ['npx', '--yes', '@smithery/cli'] + cmd + ['--client', 'gemini-cli']
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError((stderr or stdout).decode().strip())
        return stdout.decode().strip()
    except FileNotFoundError:
        raise RuntimeError("Smithery CLI not found. Is Node.js and npx installed and in your PATH?")
    except Exception as e:
        raise RuntimeError(f"Smithery CLI error: {str(e)}")

async def list_installed_servers():
    output = await run_smithery_command(['list', 'servers'])
    return output.splitlines() if output else []

async def install_server(package):
    await run_smithery_command(['install', package])

async def uninstall_server(package):
    await run_smithery_command(['uninstall', package])

async def get_registry_servers(api_key, query=''):
    config = load_config()
    url = "https://registry.smithery.ai/servers"
    headers = {"Authorization": f"Bearer {api_key or config.get('api_key', '')}"}
    params = {"q": query}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get('servers', [])
    except httpx.RequestError as e:
        raise RuntimeError(f"Failed to fetch from registry: {e}")

async def get_server_env_vars(server_id):
    try:
        output = await run_smithery_command(['inspect', server_id])
        match = re.search(r'Required env: (.*)', output)
        if match:
            vars_str = match.group(1).strip()
            if vars_str:
                return [v.strip() for v in vars_str.split(',') if v.strip()]
        return []
    except RuntimeError:
        return []
