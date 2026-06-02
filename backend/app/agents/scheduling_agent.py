from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy import text
from langchain_anthropic import ChatAnthropic
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from app.config import settings
from app.database import AsyncSessionLocal
from app.agents.prompts import build_system_prompt, build_home_prompt

_TZ_ALIASES = {
    "America/Indianapolis": "America/Indiana/Indianapolis",
    "America/Louisville": "America/Kentucky/Louisville",
    "America/Knox_IN": "America/Indiana/Knox",
    "America/Fort_Wayne": "America/Indiana/Indianapolis",
}


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(_TZ_ALIASES.get(name, name))
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


async def _load_context(user_id: str, session_id: str) -> dict:
    """Loads everything both the negotiation and personal prompts may need."""
    async with AsyncSessionLocal() as db:
        user = (await db.execute(
            text("SELECT name, username, timezone FROM users WHERE id = :id"),
            {"id": user_id},
        )).mappings().first()
        if not user:
            raise ValueError(f"User {user_id} not found")

        avail_rows = (await db.execute(
            text("SELECT day_of_week, start_time, end_time, is_available FROM availability WHERE user_id = :id ORDER BY day_of_week"),
            {"id": user_id},
        )).mappings().all()
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        avail_parts = [f"{days[r['day_of_week']]} {r['start_time']}–{r['end_time']}"
                       for r in avail_rows if r["is_available"]]
        availability_summary = ", ".join(avail_parts) if avail_parts else "No availability set"

        prefs = (await db.execute(
            text("SELECT key, value FROM agent_memory WHERE user_id = :id ORDER BY updated_at DESC LIMIT 10"),
            {"id": user_id},
        )).mappings().all()
        preferences = "; ".join(f"{r['key']}: {r['value']}" for r in prefs) or "None stored"

        hist = (await db.execute(
            text("""
                SELECT b.title, b.start_time FROM bookings b
                JOIN booking_participants bp ON bp.booking_id = b.id
                WHERE bp.user_id = :id AND b.status = 'CONFIRMED'
                ORDER BY b.start_time DESC LIMIT 5
            """),
            {"id": user_id},
        )).mappings().all()
        meeting_history = "; ".join(f"{r['title']} at {r['start_time'].strftime('%Y-%m-%d %H:%M')}" for r in hist) or "No recent meetings"

        sess = (await db.execute(
            text("SELECT purpose, duration_minutes, status, proposed_start, proposed_end, timing_note FROM scheduling_sessions WHERE id = :sid"),
            {"sid": session_id},
        )).mappings().first()

        others = (await db.execute(
            text("""
                SELECT u.username, u.timezone FROM session_participants sp
                JOIN users u ON u.id = sp.user_id
                WHERE sp.session_id = :sid AND sp.user_id != :uid
            """),
            {"sid": session_id, "uid": user_id},
        )).mappings().all()
        other_participants = ", ".join(f"@{o['username']} ({o['timezone']})" for o in others) or "none"

    tz = _tz(user["timezone"])
    current_date = datetime.now(tz).strftime("%A, %Y-%m-%d")
    proposed_time = sess["proposed_start"].isoformat() if sess and sess["proposed_start"] else "none yet"

    return {
        "user_name": user["name"],
        "username": user["username"],
        "timezone": user["timezone"],
        "current_date": current_date,
        "availability_summary": availability_summary,
        "preferences": preferences,
        "meeting_history": meeting_history,
        "session_id": session_id,
        "purpose": (sess["purpose"] if sess else None) or "Meeting",
        "duration_minutes": (sess["duration_minutes"] if sess else None) or 30,
        "other_participants": other_participants,
        "session_status": sess["status"] if sess else "UNKNOWN",
        "proposed_time": proposed_time,
        "timing_note": (sess["timing_note"] if sess else None) or "",
    }


async def _build_executor(user_id: str, system_prompt: str, extra_tools: list | None = None) -> AgentExecutor:
    """Builds a tool-calling agent whose MCP connection is bound to this user's identity.
    `extra_tools` are local (in-process) LangChain tools merged with the MCP tools."""
    mcp_client = MultiServerMCPClient({
        "timetomeet": {
            "url": f"{settings.mcp_server_url}/mcp",
            "transport": "streamable_http",
            "headers": {"X-User-Id": user_id},
        }
    })
    tools = await mcp_client.get_tools()
    if extra_tools:
        tools = tools + extra_tools

    llm = ChatAnthropic(model="claude-sonnet-4-6", api_key=settings.anthropic_api_key, max_tokens=2048)
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ])
    agent = create_tool_calling_agent(llm=llm, tools=tools, prompt=prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=True, max_iterations=15, handle_parsing_errors=True)


async def run_agent_turn(user_id: str, session_id: str) -> str:
    """Builds a fresh negotiation agent and runs one turn. Returns the agent's short
    user-facing 'what's happening' note (its final text), to be shown only to its own user."""
    ctx = await _load_context(user_id, session_id)
    system_prompt = build_system_prompt(
        user_name=ctx["user_name"], username=ctx["username"], timezone=ctx["timezone"],
        current_date=ctx["current_date"], availability_summary=ctx["availability_summary"],
        preferences=ctx["preferences"], meeting_history=ctx["meeting_history"],
        session_id=ctx["session_id"], purpose=ctx["purpose"],
        duration_minutes=ctx["duration_minutes"], other_participants=ctx["other_participants"],
        timing_note=ctx["timing_note"],
    )
    executor = await _build_executor(user_id, system_prompt)
    result = await executor.ainvoke({
        "input": "It is your turn. Review the session thread and take the appropriate action to advance the negotiation."
    })
    return _as_text(result.get("output"))


async def _load_home_context(user_id: str) -> dict:
    """Profile, availability, preferences, and the user's current meetings (for routing)."""
    from app.services.session_lifecycle import list_my_activity

    async with AsyncSessionLocal() as db:
        user = (await db.execute(
            text("SELECT name, username, timezone FROM users WHERE id = :id"),
            {"id": user_id},
        )).mappings().first()
        if not user:
            raise ValueError(f"User {user_id} not found")

        avail_rows = (await db.execute(
            text("SELECT day_of_week, start_time, end_time, is_available FROM availability WHERE user_id = :id ORDER BY day_of_week"),
            {"id": user_id},
        )).mappings().all()
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        avail_parts = [f"{days[r['day_of_week']]} {r['start_time']}–{r['end_time']}"
                       for r in avail_rows if r["is_available"]]
        availability_summary = ", ".join(avail_parts) if avail_parts else "No availability set"

        prefs = (await db.execute(
            text("SELECT key, value FROM agent_memory WHERE user_id = :id ORDER BY updated_at DESC LIMIT 10"),
            {"id": user_id},
        )).mappings().all()
        preferences = "; ".join(f"{r['key']}: {r['value']}" for r in prefs) or "None stored"

    activity = await list_my_activity(user_id)
    lines = []
    for s in activity["active_negotiations"]:
        when = f", proposed {s['proposed_start']}" if s["proposed_start"] else ""
        lines.append(f"- [{s['status']}] session_id={s['session_id']} with {', '.join('@'+u for u in s['with'])}"
                     f" — {s['purpose'] or 'meeting'}{when}")
    for b in activity["upcoming_meetings"]:
        lines.append(f"- [CONFIRMED] {b['title']} at {b['start']} with {', '.join('@'+u for u in b['with'])}")
    active_meetings = "\n".join(lines) if lines else "(none yet)"

    tz = _tz(user["timezone"])
    return {
        "user_name": user["name"],
        "username": user["username"],
        "timezone": user["timezone"],
        "current_date": datetime.now(tz).strftime("%A, %Y-%m-%d"),
        "availability_summary": availability_summary,
        "preferences": preferences,
        "active_meetings": active_meetings,
    }


def _home_tools(user_id: str) -> list:
    """Local, in-process tools for the home agent, bound to this user."""
    from app.services.session_lifecycle import create_meeting, cancel_meeting, list_my_activity

    async def start_meeting(participant_usernames: list[str], purpose: str = "Meeting",
                            duration_minutes: int = 30, timing_preference: str = "") -> str:
        """Start a new meeting and let the agents negotiate. participant_usernames are @handles
        (without the @ is fine). timing_preference captures any date/time the user asked for, in
        plain words (e.g. "Thursday", "next week", "Tuesday afternoon", "after 3pm") — always pass
        it along if the user mentioned when. Returns who was contacted, or which handles weren't found."""
        res = await create_meeting(user_id, participant_usernames, purpose, duration_minutes, timing_preference or None)
        if "error" in res:
            return f"Couldn't start it: {res['error']}. Unknown handles: {', '.join(res.get('unknown', [])) or 'none'}."
        when = f" for {timing_preference}" if timing_preference else ""
        msg = f"Started a {duration_minutes}-minute meeting{when} and reached out to {', '.join('@'+u for u in res['participants'])}."
        if res.get("unknown"):
            msg += f" I couldn't find: {', '.join('@'+u for u in res['unknown'])}."
        return msg

    async def cancel_meeting_tool(session_id: str) -> str:
        """Cancel one of the user's meetings by its session_id."""
        res = await cancel_meeting(user_id, session_id)
        return res.get("error") or "Cancelled that meeting."

    async def list_my_meetings() -> str:
        """List the user's upcoming confirmed meetings and in-progress negotiations."""
        import json
        return json.dumps(await list_my_activity(user_id))

    return [
        StructuredTool.from_function(coroutine=start_meeting, name="start_meeting",
            description="Start a new meeting with one or more @handles; agents negotiate the time automatically."),
        StructuredTool.from_function(coroutine=cancel_meeting_tool, name="cancel_meeting",
            description="Cancel one of the user's meetings by session_id."),
        StructuredTool.from_function(coroutine=list_my_meetings, name="list_my_meetings",
            description="List the user's upcoming meetings and in-progress negotiations."),
    ]


async def run_home_agent_turn(user_id: str, user_message: str) -> str:
    """The user's personal assistant. Handles natural-language scheduling, calendar questions,
    relaying guidance, and cancellations. Returns a short natural-language reply."""
    ctx = await _load_home_context(user_id)
    system_prompt = build_home_prompt(
        user_name=ctx["user_name"], username=ctx["username"], timezone=ctx["timezone"],
        current_date=ctx["current_date"], availability_summary=ctx["availability_summary"],
        preferences=ctx["preferences"], active_meetings=ctx["active_meetings"],
    )
    executor = await _build_executor(user_id, system_prompt, extra_tools=_home_tools(user_id))
    result = await executor.ainvoke({"input": user_message})
    return _as_text(result.get("output")) or "Done."


def _as_text(output) -> str:
    """LangChain/Anthropic may return the answer as a plain string or as a list of
    content blocks. Normalize to a single string for the AGENT_VOICE channel."""
    if isinstance(output, str):
        return output.strip()
    if isinstance(output, list):
        parts = []
        for block in output:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(p for p in parts if p).strip()
    return str(output).strip() if output else ""
