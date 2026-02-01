# mcp_manager.py
import asyncio
import os
import sys
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import config

class MCPManager:
    def __init__(self):
        self.exit_stack = AsyncExitStack()
        self.sessions: dict[str, ClientSession] = {}
        
    async def connect_servers(self):
        """Connects to all required MCP servers defined in configuration"""
        
        # Validation
        missing = [var for var in config.REQUIRED_ENV_VARS if not os.environ.get(var)]
        if missing:
            print(f"⚠️ [System] Warning: Missing environment variables: {missing}")

        # Server 1: Octocode
        octocode_params = StdioServerParameters(
            command="npx",
            args=["-y", "octocode-mcp@latest"],
            env=os.environ.copy()
        )
        
        # Server 2: Context7
        context7_params = StdioServerParameters(
            command="npx",
            args=["-y", "@upstash/context7-mcp@latest"],
            env=os.environ.copy()
        )

        print("🔌 [System] Connecting to servers...")
        await self._connect("octocode", octocode_params)
        await self._connect("context7", context7_params)
        
    async def _connect(self, name: str, params: StdioServerParameters):
        try:
            transport = await self.exit_stack.enter_async_context(stdio_client(params))
            session = await self.exit_stack.enter_async_context(
                ClientSession(transport[0], transport[1])
            )
            await session.initialize()
            self.sessions[name] = session
            print(f"✅ [System] Connected to {name}")
        except Exception as e:
            print(f"❌ [System] Failed to connect to {name}: {e}")

    async def cleanup(self):
        print("🧹 [System] Cleaning up MCP connections...")
        try:
            await self.exit_stack.aclose()
        except Exception as e:
            # Swallow the expected BrokenResourceError/ExceptionGroup on exit
            pass
