from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


def _resolve_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    """Expand ${ENV_NAME} placeholders without persisting secret values."""
    resolved: dict[str, str] = {}
    for key, value in (headers or {}).items():
        text = str(value)
        resolved[str(key)] = re.sub(
            r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}',
            lambda match: os.getenv(match.group(1), match.group(0)),
            text,
        )
    return resolved


def _resolve_env(values: dict[str, Any] | None) -> dict[str, str]:
    """Expand ${ENV_NAME} placeholders for stdio MCP child processes."""
    resolved: dict[str, str] = {}
    for key, value in (values or {}).items():
        text = str(value)
        resolved[str(key)] = re.sub(
            r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}',
            lambda match: os.getenv(match.group(1), match.group(0)),
            text,
        )
    return resolved


async def test_mcp(config: dict[str, Any]) -> dict[str, Any]:
    """Connect to an MCP server and list its tools when the SDK is installed."""
    load_dotenv(Path(__file__).resolve().parent.parent / '.env', override=True)
    client = None
    try:
        from agentscope.mcp import HttpMCPConfig, MCPClient, StdioMCPConfig
    except ImportError as exc:
        return {'ok': False, 'error': 'AgentScope MCP client is not installed', 'detail': str(exc), 'tools': []}
    try:
        transport = config['transport']
        if transport == 'stdio':
            command = str(config.get('command') or '').strip()
            if not command:
                return {'ok': False, 'error': 'stdio MCP 未配置启动命令', 'tools': []}
            if not shutil.which(command):
                return {
                    'ok': False,
                    'error': f'找不到 MCP 启动命令“{command}”。请确认命令已安装，或填写可执行文件的完整路径。',
                    'tools': [],
                }
            client = MCPClient(
                name=config['id'],
                is_stateful=True,
                mcp_config=StdioMCPConfig(
                    command=command,
                    args=config.get('args', []),
                    env=_resolve_env(config.get('env')) or None,
                ),
                enable_tools=config.get('allowed_tools') or None,
            )
        else:
            client = MCPClient(
                name=config['id'],
                is_stateful=transport != 'sse',
                mcp_config=HttpMCPConfig(url=config['url'], headers=_resolve_headers(config.get('headers')) or None),
                enable_tools=config.get('allowed_tools') or None,
            )
        if client.is_stateful:
            await client.connect()
        tools = await client.list_tools()
        if client.is_stateful:
            await client.close()
        return {'ok': True, 'tools': [getattr(tool, 'name', str(tool)) for tool in tools], 'count': len(tools)}
    except Exception as exc:
        try:
            if client and client.is_stateful:
                await client.close()
        except Exception:
            pass
        return {'ok': False, 'error': str(exc), 'tools': []}
