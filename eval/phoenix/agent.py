"""
GsaGrajAgent — thin wrapper that drives the gsa_graj_tools MCP server
over stdio and returns a plain-text response for each user message.

Used by the Phoenix evaluation harness (run_experiment.py).
Environment variables required:
  USAI_API_KEY   — API key for the LLM provider
  USAI_BASE_URL  — Base URL for the LLM provider (OpenAI-compatible)
  AGENT_MODEL    — Model identifier, e.g. "openai/gpt-4o"
  PG_HOST        — PostgreSQL host (default: localhost)
  PG_PORT        — PostgreSQL port (default: 5432)
  PG_DB          — PostgreSQL database name (default: wxodb)
  PG_USER        — PostgreSQL username (default: wxouser)
  PG_PASS        — PostgreSQL password (default: wxopass)
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path
from typing import Optional

from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import OpenAI

# ── Paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT   = Path(__file__).resolve().parent.parent.parent
SERVER_CWD  = REPO_ROOT / "toolkits" / "gsa_graj_tools"
SERVER_CMD  = "python"
SERVER_ARGS = ["server.py"]

# ── LLM client ────────────────────────────────────────────────────────────────

def _llm_client() -> OpenAI:
    return OpenAI(
        api_key=os.environ["USAI_API_KEY"],
        base_url=os.environ["USAI_BASE_URL"],
    )


def _agent_model() -> str:
    return os.environ.get("AGENT_MODEL", "openai/gpt-4o")


# ── MCP server parameters ─────────────────────────────────────────────────────

def _server_params() -> StdioServerParameters:
    """Build MCP stdio parameters, forwarding PostgreSQL env vars."""
    env = {
        **os.environ,
        "PG_HOST": os.environ.get("PG_HOST", "localhost"),
        "PG_PORT": os.environ.get("PG_PORT", "5432"),
        "PG_DB":   os.environ.get("PG_DB",   "wxodb"),
        "PG_USER": os.environ.get("PG_USER", "wxouser"),
        "PG_PASS": os.environ.get("PG_PASS", "wxopass"),
    }
    return StdioServerParameters(
        command=SERVER_CMD,
        args=SERVER_ARGS,
        cwd=str(SERVER_CWD),
        env=env,
    )


# ── Agent class ───────────────────────────────────────────────────────────────

class GsaGrajAgent:
    """Drive one conversation turn through the MCP server + LLM."""

    def __init__(self, system_prompt: Optional[str] = None) -> None:
        prompt_path = Path(__file__).parent / "prompts" / "system_prompt_v1.txt"
        self.system_prompt = system_prompt or prompt_path.read_text()
        self._client = _llm_client()
        self._model  = _agent_model()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, user_message: str) -> str:
        """Send *user_message* to the agent and return the final response."""
        import asyncio
        return asyncio.run(self._arun(user_message))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _arun(self, user_message: str) -> str:
        async with stdio_client(_server_params()) as (read, write):
            from mcp.client.session import ClientSession
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await self._list_tools(session)
                return await self._chat_loop(session, tools, user_message)

    async def _list_tools(self, session) -> list[dict]:
        """Retrieve the MCP tool list and convert to OpenAI function schema."""
        result = await session.list_tools()
        openai_tools = []
        for tool in result.tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema or {"type": "object", "properties": {}},
                },
            })
        return openai_tools

    async def _chat_loop(self, session, tools: list[dict], user_message: str) -> str:
        """Run the ReAct loop until the model produces a final text response."""
        messages = [
            {"role": "system",  "content": self.system_prompt},
            {"role": "user",    "content": user_message},
        ]

        for _ in range(10):  # max tool-call rounds
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=tools or None,
                tool_choice="auto" if tools else None,
            )
            choice = response.choices[0]

            if choice.finish_reason == "tool_calls":
                # Append assistant message with tool_calls
                messages.append(choice.message.model_dump(exclude_unset=False))
                # Execute each tool call
                for tc in choice.message.tool_calls:
                    import json
                    tool_result = await session.call_tool(
                        tc.function.name,
                        arguments=json.loads(tc.function.arguments or "{}"),
                    )
                    content = (
                        tool_result.content[0].text
                        if tool_result.content
                        else ""
                    )
                    messages.append({
                        "role":         "tool",
                        "tool_call_id": tc.id,
                        "content":      content,
                    })
            else:
                # Final text response
                return choice.message.content or ""

        return "Agent reached maximum tool-call rounds without a final answer."
