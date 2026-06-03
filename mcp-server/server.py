from fastmcp import FastMCP
from tools.availability import check_my_availability
from tools.memory import get_my_preferences, save_to_my_memory
from tools.sessions import get_session_thread, send_message, propose_time, accept_proposal, reject_proposal
from tools.bookings import get_my_meeting_history
from tools.users import get_user_by_username

mcp = FastMCP("timetomeet")

mcp.tool()(check_my_availability)
mcp.tool()(get_my_preferences)
mcp.tool()(save_to_my_memory)
mcp.tool()(get_session_thread)
mcp.tool()(send_message)
mcp.tool()(propose_time)
mcp.tool()(accept_proposal)
mcp.tool()(reject_proposal)
mcp.tool()(get_my_meeting_history)
mcp.tool()(get_user_by_username)

if __name__ == "__main__":
    import os
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.environ.get("PORT", 8001)))
