#!/usr/bin/env python3
import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

server = Server("test-mcp")

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [types.Tool(name="hello", description="Says hello", inputSchema={"type": "object", "properties": {}})]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    return [types.TextContent(type="text", text="Hello from test MCP!")]

async def main():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
