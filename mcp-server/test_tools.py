"""Quick smoke test — runs against the live MCP server.

Identity is now bound to the connection via the X-User-Id header, so user-scoped
tools no longer take a user_id argument.
"""
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"


async def main():
    headers = {"X-User-Id": TEST_USER_ID}
    async with streamablehttp_client("http://mcp-server:8001/mcp", headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            print(f"Registered tools ({len(tool_names)}): {tool_names}")
            expected = {
                "check_my_availability", "get_my_preferences", "save_to_my_memory",
                "get_session_thread", "send_message", "propose_time",
                "accept_proposal", "reject_proposal",
                "get_my_meeting_history", "get_user_by_username",
            }
            missing = expected - set(tool_names)
            assert not missing, f"Missing tools: {missing}"
            print("All tools registered.")

            result = await session.call_tool("get_user_by_username", {"username": "alice"})
            print(f"get_user_by_username: {result.content[0].text}")

            result = await session.call_tool("get_my_preferences", {})
            print(f"get_my_preferences: {result.content[0].text}")

            result = await session.call_tool("save_to_my_memory", {
                "key": "preferred_meeting_time", "value": "mornings before 11am",
            })
            print(f"save_to_my_memory: {result.content[0].text}")

            result = await session.call_tool("check_my_availability", {
                "date": "2026-06-08", "duration_minutes": 30,
            })
            print(f"check_my_availability: {result.content[0].text}")

            print("\nAll tests passed!")


if __name__ == "__main__":
    asyncio.run(main())
