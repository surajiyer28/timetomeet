# TimeToMeet — Full System Specification

## Overview

TimeToMeet is a production-grade AI-powered scheduling platform where every user has a personal AI scheduling agent. When you want to meet someone, your agent negotiates directly with their agent — autonomously, in real-time — to find the best time for everyone. Users watch the negotiation happen live and only step in to approve, reject, or clarify.

This is not "find overlapping free slots." The agents reason over preferences, history, and constraints to advocate for their user and reach an intelligent consensus.

---

## Core User Flow

1. User signs up, sets their availability grid and gets a unique `@username` handle.
2. User opens the app and says (or types) to their agent: *"Schedule a 30-minute product review with @bob and @alice."*
3. Agent clarifies if needed ("Is this one meeting with all three of you, or separate meetings?").
4. Agent initiates a negotiation session. Bob's and Alice's agents are invoked server-side — regardless of whether Bob or Alice are currently online.
5. All agents negotiate autonomously via a shared message thread, visible to all participants in real-time.
6. Agents reach a proposed time. All participants receive an in-app notification and email to approve or reject.
7. If any participant rejects, agents re-negotiate with the rejection reason as context.
8. Once all approve, the booking is confirmed and stored.

---

## Group vs. Separate Meetings

- **"Schedule with Bob and Alice"** → one session, all three in the same meeting.
- **"Schedule with Bob and Alice separately"** → two independent sessions, two separate 1:1 negotiations.
- **Ambiguous requests** → Agent asks the initiating user to clarify before doing anything.

---

## Architecture

```
┌─────────────────────────────────────┐
│         Next.js 14 Frontend         │
│   (React, Tailwind, WebSockets,     │
│    Web Speech API, SpeechSynthesis) │
└──────────────┬──────────────────────┘
               │ HTTP + WebSocket
┌──────────────▼──────────────────────┐
│         FastAPI Backend             │
│  - Email/password auth (JWT)        │
│  - WebSocket connection manager     │
│  - Session orchestration loop       │
│  - LangChain Agents (MCP clients)   │
│  - REST API for frontend            │
└──────────────┬──────────────────────┘
               │ MCP Protocol (HTTP/SSE)
┌──────────────▼──────────────────────┐
│         MCP Server (FastMCP)        │
│  - All business logic               │
│  - All database access              │
│  - Deterministic tool definitions   │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│      PostgreSQL (Supabase)          │
└─────────────────────────────────────┘
```

**Key principle:** LangChain agents are MCP clients. They cannot touch the database directly. Every action the AI takes goes through an MCP tool call. The core system is fully deterministic — the AI layer is fully abstracted on top of it.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 + React + Tailwind CSS |
| Backend | FastAPI (Python 3.11) |
| Agent Framework | LangChain AgentExecutor |
| LLM | Claude claude-sonnet-4-6 (Anthropic) — configurable |
| MCP Server | FastMCP (Python) |
| Database | PostgreSQL via Supabase |
| Auth | Email/password with JWT (python-jose + passlib) |
| Real-time | WebSockets (FastAPI native) |
| Voice Input | Web Speech API (browser STT) |
| Voice Output | Browser SpeechSynthesis API (TTS) |
| Email | SMTP (approval notifications + booking confirmations) |
| Calendar | Stubbed — DB bookings only (Google Calendar integration is a future milestone) |

---

## Database Schema

```sql
-- Users
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  name TEXT NOT NULL,
  username TEXT UNIQUE NOT NULL,   -- e.g. "suraj" → handle @suraj
  timezone TEXT NOT NULL,           -- auto-detected from browser on signup
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Availability grid (per user, per day of week)
CREATE TABLE availability (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  day_of_week INT NOT NULL,         -- 0=Monday, 6=Sunday
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  is_available BOOL NOT NULL DEFAULT true,
  UNIQUE(user_id, day_of_week)
);

-- Agent long-term memory (preferences, learned facts)
CREATE TABLE agent_memory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id, key)
);

-- Scheduling sessions
CREATE TABLE scheduling_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  initiated_by UUID NOT NULL REFERENCES users(id),
  purpose TEXT,                     -- meeting title/purpose, may be null until agent asks
  duration_minutes INT,             -- null until specified
  status TEXT NOT NULL DEFAULT 'INITIATED',
  -- INITIATED | NEGOTIATING | PROPOSED | PENDING_APPROVAL | CONFIRMED
  -- | RE_NEGOTIATING | ESCALATED | CANCELLED | EXPIRED
  proposed_start TIMESTAMPTZ,       -- set when agents agree
  proposed_end TIMESTAMPTZ,
  escalation_reason TEXT,           -- populated when status = ESCALATED
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Session participants (supports N participants for group meetings)
CREATE TABLE session_participants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES scheduling_sessions(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id),
  role TEXT NOT NULL DEFAULT 'PARTICIPANT',   -- INITIATOR | PARTICIPANT
  approval_status TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING | APPROVED | REJECTED
  rejection_reason TEXT,
  joined_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(session_id, user_id)
);

-- Session messages (shared negotiation thread, visible to all participants)
CREATE TABLE session_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES scheduling_sessions(id) ON DELETE CASCADE,
  sender_user_id UUID NOT NULL REFERENCES users(id),
  sender_type TEXT NOT NULL,         -- AGENT | USER
  content TEXT NOT NULL,             -- natural language message
  message_type TEXT NOT NULL,        -- INFO | PROPOSE | COUNTER | ACCEPT | REJECT | CLARIFY | ESCALATE
  metadata JSONB,
  -- e.g. { "proposed_slots": ["2026-06-05T14:00:00-05:00"], "reasoning": "..." }
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Confirmed bookings
CREATE TABLE bookings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES scheduling_sessions(id),
  title TEXT NOT NULL,
  start_time TIMESTAMPTZ NOT NULL,
  end_time TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL DEFAULT 'CONFIRMED',  -- CONFIRMED | CANCELLED
  calendar_event_id TEXT,            -- stub: always null for now
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Booking participants (who is in the confirmed meeting)
CREATE TABLE booking_participants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  booking_id UUID NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id),
  UNIQUE(booking_id, user_id)
);
```

---

## MCP Server

Runs as a separate FastMCP service. All tools are **user-scoped** — an agent can only call tools for its own user. The `user_id` passed to each tool must match the agent's identity (validated by the MCP server).

### Tool Definitions

```python
# --- Availability ---

@mcp.tool()
async def check_my_availability(
    user_id: str,
    date: str,             # YYYY-MM-DD
    duration_minutes: int  # e.g. 30 or 60
) -> dict:
    """
    Returns free time slots for the given user on the given date,
    filtered to their availability grid and excluding existing bookings.
    Slots are returned in the user's local timezone.
    """

# --- Agent Memory ---

@mcp.tool()
async def get_my_preferences(user_id: str) -> dict:
    """
    Returns all stored agent memory entries for the user.
    Includes preferences like preferred meeting times, communication style, etc.
    """

@mcp.tool()
async def save_to_my_memory(user_id: str, key: str, value: str) -> dict:
    """
    Saves or updates a preference or learned fact for the user's agent memory.
    """

@mcp.tool()
async def get_my_meeting_history(user_id: str, limit: int = 10) -> dict:
    """
    Returns the user's recent confirmed bookings for context.
    """

# --- Session / Negotiation ---

@mcp.tool()
async def get_session_thread(session_id: str) -> dict:
    """
    Returns all messages in the negotiation thread for a session,
    ordered chronologically.
    """

@mcp.tool()
async def send_message(
    session_id: str,
    sender_user_id: str,
    content: str,
    message_type: str,   # INFO | PROPOSE | COUNTER | ACCEPT | REJECT | CLARIFY | ESCALATE
    metadata: dict = {}
) -> dict:
    """
    Posts a message to the session negotiation thread.
    Triggers a WebSocket broadcast to all participants.
    """

@mcp.tool()
async def propose_time(
    session_id: str,
    sender_user_id: str,
    proposed_slots: list[str],  # ISO 8601 datetime strings
    reasoning: str
) -> dict:
    """
    Posts a structured time proposal to the session thread.
    Sets session status to PROPOSED.
    """

@mcp.tool()
async def accept_proposal(session_id: str, user_id: str) -> dict:
    """
    Records this agent's acceptance of the current proposal.
    """

@mcp.tool()
async def reject_proposal(session_id: str, user_id: str, reason: str) -> dict:
    """
    Records this agent's rejection with a reason.
    Triggers re-negotiation.
    """

# --- Users ---

@mcp.tool()
async def get_user_by_username(username: str) -> dict:
    """
    Looks up a user by their @handle. Returns id, name, username.
    Used by the initiating agent to resolve @mentions.
    """
```

---

## LangChain Agent Design

### Agent Instantiation

Agents are **stateless and instantiated per turn**. Long-term memory is loaded from the DB via MCP at the start of each turn. In-session context (the negotiation thread) is loaded via `get_session_thread`. There are no persistent agent processes.

```python
from langchain.agents import AgentExecutor, create_react_agent
from langchain_anthropic import ChatAnthropic
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.memory import ConversationBufferMemory

async def build_agent(user_id: str, session_id: str) -> AgentExecutor:
    # Load tools from MCP server
    mcp_client = MultiServerMCPClient({
        "timetomeet": {"url": MCP_SERVER_URL, "transport": "streamable_http"}
    })
    tools = await mcp_client.get_tools()

    # Load user context
    prefs = await get_preferences_from_db(user_id)
    history = await get_history_from_db(user_id)
    availability = await get_availability_summary(user_id)

    llm = ChatAnthropic(model="claude-sonnet-4-6")

    prompt = build_agent_prompt(user_id, prefs, history, availability)

    agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)
    executor = AgentExecutor(agent=agent, tools=tools, verbose=True)
    return executor
```

### Agent System Prompt Template

```
You are {user_name}'s personal scheduling agent on TimeToMeet.

ABOUT YOUR USER:
- Name: {user_name}
- Username: @{username}
- Timezone: {timezone}
- Availability: {availability_summary}
- Preferences: {preferences}
- Recent meetings: {meeting_history}

YOUR ROLE:
- Negotiate meeting times on behalf of {user_name}
- Protect their time, preferences, and schedule
- You can ONLY check your own user's availability — never another user's
- Cross-user coordination happens only through session messages
- Be concise in negotiations — agents talk to agents, not to humans
- Always include clear reasoning when proposing or rejecting times
- Save useful preferences you learn during negotiation to memory

CURRENT SESSION:
- Session ID: {session_id}
- Purpose: {purpose}
- Duration: {duration_minutes} minutes
- Other participants: {other_participants}

Start by reading the current session thread with get_session_thread, then act.
```

---

## Negotiation Orchestrator

Lives in the FastAPI backend. Runs as an async background task per session. Alternates turns between participant agents. Does NOT use LangGraph — it is a custom async loop.

```python
async def run_negotiation(session_id: str):
    session = await get_session(session_id)
    participants = await get_session_participants(session_id)
    max_turns = 10
    turn = 0

    # Initiating agent goes first, then round-robin
    agent_order = sorted(participants, key=lambda p: 0 if p.role == "INITIATOR" else 1)

    while turn < max_turns:
        current_participant = agent_order[turn % len(agent_order)]
        agent = await build_agent(current_participant.user_id, session_id)

        # Run agent turn
        result = await agent.ainvoke({
            "input": f"It is your turn. Review the session thread and take the appropriate action."
        })

        # Reload session to check if state changed via tool calls
        session = await get_session(session_id)

        if session.status == "PROPOSED":
            # All agents agreed — notify users for approval
            await notify_all_participants_for_approval(session_id)
            return

        if session.status == "ESCALATED":
            await notify_initiator_of_escalation(session_id, session.escalation_reason)
            return

        if session.status in ("CONFIRMED", "CANCELLED", "EXPIRED"):
            return

        turn += 1

    # Max turns reached with no consensus
    await escalate_session(
        session_id,
        reason="Agents could not agree on a time after 10 rounds. Please select a time manually or adjust your availability."
    )
    await notify_initiator_of_escalation(session_id)
```

### Re-negotiation

When a user rejects a proposal:
- Session status → `RE_NEGOTIATING`
- Rejection reason is saved to the session thread as a USER message
- The negotiation loop re-runs from the next agent's turn with the rejection in context
- Max turns counter resets

---

## WebSocket Protocol

Each user connects to `/ws/{user_id}` with their JWT. The connection manager tracks online users per session.

### Server → Client Events

```json
{ "type": "MESSAGE", "session_id": "...", "message": { ... } }
// New negotiation message posted to the thread

{ "type": "PROPOSAL", "session_id": "...", "proposed_start": "...", "proposed_end": "..." }
// Agents reached consensus — approval needed

{ "type": "APPROVAL_UPDATE", "session_id": "...", "user_id": "...", "status": "APPROVED" }
// Someone approved or rejected

{ "type": "CONFIRMED", "session_id": "...", "booking_id": "..." }
// All approved, booking created

{ "type": "RE_NEGOTIATING", "session_id": "...", "rejected_by": "...", "reason": "..." }
// Someone rejected, agents will try again

{ "type": "ESCALATED", "session_id": "...", "reason": "..." }
// Agents couldn't resolve, user action needed

{ "type": "AGENT_VOICE", "session_id": "...", "text": "..." }
// Agent's personal message to this user (frontend should TTS this)

{ "type": "SESSION_CREATED", "session": { ... } }
// A new session was initiated that involves this user
```

### Client → Server Events

```json
{ "type": "USER_MESSAGE", "session_id": "...", "content": "..." }
// User injects a message to guide their agent mid-negotiation

{ "type": "APPROVE", "session_id": "..." }
// User approves the proposed time

{ "type": "REJECT", "session_id": "...", "reason": "..." }
// User rejects the proposed time

{ "type": "VOICE_INPUT", "session_id": "...", "transcript": "..." }
// Browser STT transcript sent to personal agent
```

---

## Voice Interface

Voice is available in the **personal agent channel** only (the user's private conversation with their own agent). The shared negotiation thread is text only.

### STT (User → Agent)
- Web Speech API (`SpeechRecognition`)
- Continuous listening mode while session is active
- Transcripts sent to backend via WebSocket as `VOICE_INPUT` events

### TTS (Agent → User)
- Browser `SpeechSynthesis` API
- Triggered when backend sends `AGENT_VOICE` event
- Queue-based — if multiple messages arrive, they are spoken in order
- User can click to stop current speech

---

## Frontend UI

### Split View — Session Page (`/dashboard/sessions/[id]`)

```
┌──────────────────────────────────────────────────────────────┐
│ TimeToMeet                              @suraj    [+ New]     │
├────────────────────┬─────────────────────────────────────────┤
│ Sessions           │  Meeting with @bob, @alice              │
│ ────────────────── │  30 min · Product Review                │
│ @bob, @alice   🟢  │                                         │
│ @carol         ⏳  │  NEGOTIATION              [live]        │
│                    │  ───────────────────────────────────    │
│                    │  🤖 Your Agent                          │
│                    │  "Checking with Bob and Alice's         │
│                    │   agents for Thursday availability."    │
│                    │                                         │
│                    │  🤖 Bob's Agent                         │
│                    │  "Bob is free Thu 10am–12pm and         │
│                    │   2pm–4pm ET."                          │
│                    │                                         │
│                    │  🤖 Alice's Agent                       │
│                    │  "Alice is free Thu 2pm–5pm ET.         │
│                    │   She prefers afternoons."              │
│                    │                                         │
│                    │  🤖 Your Agent                          │
│                    │  "Thu 2pm ET works for all three.       │
│                    │   Proposing that time."                 │
│                    │                                         │
│                    │  ✅ PROPOSED: Thu Jun 5 · 2:00 PM ET    │
│                    │  [Approve]           [Reject]           │
│                    │ ─────────────────────────────────────   │
│                    │  YOUR AGENT                    🔊       │
│                    │                                         │
│                    │  Agent: "I found Thu 2pm that works     │
│                    │  for Bob and Alice — want to confirm?"  │
│                    │                                         │
│                    │  ┌─────────────────────────────────┐   │
│                    │  │ 🎤  speak or type to your agent  │   │
│                    │  └─────────────────────────────────┘   │
└────────────────────┴─────────────────────────────────────────┘
```

### Pages

| Route | Description |
|---|---|
| `/auth/signup` | Email, password, name, username, auto-detected timezone |
| `/auth/signin` | Email + password |
| `/dashboard` | Active sessions list, upcoming bookings |
| `/dashboard/sessions/[id]` | Split view: negotiation + personal agent chat |
| `/dashboard/availability` | Availability grid (day × time range) |
| `/dashboard/profile` | Name, handle, preferences, timezone |

### New Session Initiation

From the dashboard, clicking `[+ New]` opens a modal that connects to the user's personal agent. The user speaks or types their request (e.g., "Schedule a 30-minute product review with @bob and @alice"). The agent handles the rest.

---

## Email Notifications

Sent via SMTP for:

1. **Approval needed** — "TimeToMeet: Your agents have proposed a time. Open the app to approve."
2. **Booking confirmed** — "TimeToMeet: Meeting confirmed for [time] with [participants]."
3. **Escalation** — "TimeToMeet: Your scheduling agent needs your help. Agents couldn't agree on a time."
4. **Rejection** — "TimeToMeet: [User] rejected the proposed time. Agents are re-negotiating."

---

## Session State Machine

```
INITIATED
    │
    ▼
NEGOTIATING ──────────────────────────────► ESCALATED
    │                                          (max turns / no availability)
    ▼ (agents agree)
PROPOSED
    │
    ▼
PENDING_APPROVAL
    │                    │
    ▼ (all approve)      ▼ (any reject)
CONFIRMED            RE_NEGOTIATING
                         │
                         ▼
                     NEGOTIATING (again, with rejection context)
```

---

## Project Structure

```
timetomeet/
├── frontend/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── auth/
│   │   │   ├── signup/page.tsx
│   │   │   └── signin/page.tsx
│   │   └── dashboard/
│   │       ├── layout.tsx
│   │       ├── page.tsx                  # sessions list + upcoming bookings
│   │       ├── sessions/[id]/page.tsx    # split view
│   │       ├── availability/page.tsx
│   │       └── profile/page.tsx
│   ├── components/
│   │   ├── SessionList.tsx
│   │   ├── SessionView.tsx               # split layout wrapper
│   │   ├── NegotiationFeed.tsx           # agent-to-agent thread
│   │   ├── AgentChat.tsx                 # personal voice channel
│   │   ├── ApprovalPrompt.tsx            # approve/reject UI
│   │   ├── NewSessionModal.tsx           # initiate flow
│   │   ├── AvailabilityGrid.tsx
│   │   └── Navbar.tsx
│   ├── lib/
│   │   ├── api.ts                        # typed fetch wrapper
│   │   ├── websocket.ts                  # WS client + event handlers
│   │   ├── voice.ts                      # Web Speech API + SpeechSynthesis
│   │   └── auth.ts                       # JWT storage
│   ├── package.json
│   └── tailwind.config.ts
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py                     # env vars (Pydantic Settings)
│   │   ├── database.py                   # SQLAlchemy async engine
│   │   ├── auth.py                       # JWT issue + verify
│   │   ├── routers/
│   │   │   ├── auth.py                   # POST /auth/signup, /auth/signin
│   │   │   ├── sessions.py               # CRUD for sessions + approval endpoints
│   │   │   ├── availability.py           # GET/PUT /availability
│   │   │   ├── users.py                  # GET /users/me, GET /users/@username
│   │   │   └── bookings.py               # GET /bookings
│   │   ├── websocket/
│   │   │   ├── manager.py                # connection manager (user_id → WS)
│   │   │   └── router.py                 # /ws/{user_id} endpoint
│   │   ├── agents/
│   │   │   ├── scheduling_agent.py       # LangChain AgentExecutor builder
│   │   │   ├── prompts.py                # system prompt templates
│   │   │   └── orchestrator.py           # negotiation loop
│   │   ├── models/                       # SQLAlchemy ORM models
│   │   │   ├── user.py
│   │   │   ├── availability.py
│   │   │   ├── session.py
│   │   │   ├── message.py
│   │   │   └── booking.py
│   │   └── schemas/                      # Pydantic request/response schemas
│   ├── requirements.txt
│   └── Dockerfile
│
├── mcp-server/
│   ├── server.py                         # FastMCP app entry point
│   ├── database.py                       # SQLAlchemy async engine (shared DB)
│   ├── tools/
│   │   ├── availability.py               # check_my_availability
│   │   ├── memory.py                     # get_my_preferences, save_to_my_memory
│   │   ├── sessions.py                   # get_session_thread, send_message, propose_time, accept, reject
│   │   ├── bookings.py                   # get_my_meeting_history, create_booking
│   │   └── users.py                      # get_user_by_username
│   ├── requirements.txt
│   └── Dockerfile
│
└── docker-compose.yml
```

---

## Environment Variables

### Backend (`backend/.env`)

```
DATABASE_URL=postgresql+asyncpg://...
JWT_SECRET=<random 32-byte secret>
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=10080
MCP_SERVER_URL=http://mcp-server:8001
ANTHROPIC_API_KEY=<key>
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=<email>
SMTP_PASSWORD=<app password>
FRONTEND_URL=http://localhost:3000
```

### MCP Server (`mcp-server/.env`)

```
DATABASE_URL=postgresql+asyncpg://...
```

### Frontend (`frontend/.env.local`)

```
NEXT_PUBLIC_BACKEND_URL=http://localhost:8080
NEXT_PUBLIC_WS_URL=ws://localhost:8080
```

---

## Docker Compose

```yaml
services:
  backend:
    build: ./backend
    ports: ["8080:8080"]
    env_file: ./backend/.env
    depends_on: [mcp-server]

  mcp-server:
    build: ./mcp-server
    ports: ["8001:8001"]
    env_file: ./mcp-server/.env

  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    env_file: ./frontend/.env.local
```

---

## Key Backend Dependencies

```
# backend/requirements.txt
fastapi
uvicorn[standard]
sqlalchemy[asyncio]
asyncpg
alembic
python-jose[cryptography]
passlib[bcrypt]
langchain
langchain-anthropic
langchain-mcp-adapters
websockets
httpx
pydantic-settings
aiosmtplib
```

```
# mcp-server/requirements.txt
fastmcp
sqlalchemy[asyncio]
asyncpg
pydantic-settings
```

---

## Key Design Decisions

### Why separate MCP server?
The MCP server is the single source of truth for all business logic. Agents cannot reach the database directly — every action is a tool call with a defined contract. This makes the AI layer fully auditable, testable in isolation, and swappable.

### Why LangChain AgentExecutor (not LangGraph)?
LangGraph is for fixed, graph-defined workflows. The negotiation here is open-ended — we don't know how many turns it will take or which tools the agent will use. AgentExecutor's ReAct loop is appropriate for dynamic, multi-step reasoning.

### Why stateless agents?
Agents are instantiated per turn, loading state from the database. This makes the system horizontally scalable and crash-safe. The "memory" of the agent is the database, not an in-memory object.

### Why not check the other user's availability directly?
Each agent can only call `check_my_availability` for their own user. Cross-agent availability sharing happens through session messages — Agent A asks Agent B, Agent B checks its own user's calendar and responds. This is privacy-preserving by design and mirrors how real human scheduling works.

### Calendar integration
Stubbed in this version — bookings are stored in the database only. Google Calendar OAuth + event creation is a defined next milestone that can be dropped in without changing the agent or MCP tool contracts (only the `create_booking` implementation changes).

---

## Future Milestones (Post-MVP)

- Google Calendar OAuth + event creation (replace stub in `create_booking`)
- Timezone inference from Google Calendar (replace manual timezone in profile)
- Recurring meetings ("every Tuesday at 2pm with @bob")
- Slack / Teams notification integration
- Multi-LLM support (route different agents to different LLMs based on user preference)
- Agent analytics dashboard (preference learning accuracy, negotiation success rate)
- Mobile app (React Native)
