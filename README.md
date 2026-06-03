# TimeToMeet

An AI-powered scheduling platform where every user has a personal AI agent. To meet
someone, you tell your agent in plain language — and it negotiates **directly with the other
people's agents**, in real time, to find a time that works for everyone. You only step in to
approve or reject the result.

It is not "find the overlapping free slots." Each agent advocates for its own user, reasons
over their availability and preferences, and reaches consensus through a private agent-to-agent
negotiation that the humans never see.

---

## How it works

```
You: "set up a 30 minute roadmap sync with @bob and @carol on Thursday"

Your agent:  Reached out to Bob and Carol for a 30-minute sync on Thursday.
Your agent:  Lined up a time that works — take a look below.

             ┌───────────────────────────────────────────┐
             │ Roadmap sync · @bob, @carol                 │
             │ Proposed: Thu, Jun 4, 12:00 PM EDT          │
             │   [ Approve ]   [ Reject ]                  │
             └───────────────────────────────────────────┘
```

- You talk to **your own agent** in a single continuous chat.
- Your agent and the other participants' agents negotiate on a private thread.
- You see your agent's running "what's happening" narration — never the other agents' raw
  messages, and never anyone else's calendar.
- When the agents agree, everyone approves or rejects the proposed time in-app.

### Privacy model

A user only ever sees their **own** agent. The inter-agent negotiation thread is never shown
to humans, and agents negotiate by **proposing and countering specific times** rather than
broadcasting calendars — so one person's availability never enters another person's agent.
This is enforced structurally (the data never reaches the other agent), not by asking agents
to keep secrets, so it can't be jailbroken out of an agent that never had the information.

---

## Architecture

```
┌─────────────────────────────────────┐
│         Next.js 14 Frontend         │   single-stream chat, WebSockets,
│   (React, Tailwind, Web Speech)     │   Web Speech API for voice in/out
└──────────────┬──────────────────────┘
               │ HTTP + WebSocket
┌──────────────▼──────────────────────┐
│         FastAPI Backend             │   JWT auth, WebSocket manager,
│  - Home + negotiation agents        │   negotiation orchestrator,
│  - LangChain AgentExecutors         │   session lifecycle service
│  - MCP client (per-user identity)   │
└──────────────┬──────────────────────┘
               │ MCP Protocol (streamable HTTP)
┌──────────────▼──────────────────────┐
│         MCP Server (FastMCP)        │   all user-scoped tools; identity is
│  - availability / memory / sessions │   bound to the connection via an
│  - users / bookings                 │   X-User-Id header, never an LLM arg
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│            PostgreSQL                │
└─────────────────────────────────────┘
```

**Key principle:** the LangChain agents are MCP clients — they can't touch the database
directly. Every action is an MCP tool call, and each tool is scoped to the calling user by an
`X-User-Id` header (validated server-side), so an agent can only ever act for its own user.

### Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14, React, Tailwind CSS |
| Backend | FastAPI (Python 3.11) |
| Agents | LangChain `AgentExecutor` (tool-calling) |
| LLM | Claude (`claude-sonnet-4-6`) via `langchain-anthropic` |
| MCP server | FastMCP (streamable HTTP) |
| Database | PostgreSQL 16 |
| Auth | Email/password, JWT (python-jose + passlib/bcrypt) |
| Real-time | FastAPI WebSockets |
| Voice | Web Speech API (STT) + SpeechSynthesis (TTS), browser-side |
| Email | SMTP (Mailpit for local dev; real Gmail/STARTTLS when configured) |
| Calendar | Google Calendar via per-user OAuth — real free/busy + event creation; falls back to DB-only when a user hasn't connected |

---

## Project layout

```
timetomeet/
├── backend/            FastAPI app: routers, auth, websocket, agents, services, models
│   ├── app/
│   │   ├── agents/       prompts, scheduling/home agents, negotiation orchestrator
│   │   ├── routers/      auth, users, availability, sessions, bookings, feed
│   │   ├── services/     session lifecycle (create/approve/reject/book), chat (home channel)
│   │   ├── websocket/    connection manager + /ws endpoint
│   │   └── models/       SQLAlchemy ORM
│   └── alembic/         migrations
├── mcp-server/         FastMCP server + user-scoped tools (identity via X-User-Id header)
├── frontend/           Next.js single-stream UI
└── docker-compose.yml  postgres, mailpit, mcp-server, backend, frontend
```

---

## Running locally

Requires Docker (Docker Desktop, OrbStack, etc.) with Docker Compose.

### 1. Configure environment

Copy the example env files and fill in your values:

```bash
cp backend/.env.example      backend/.env
cp mcp-server/.env.example   mcp-server/.env
cp frontend/.env.local.example frontend/.env.local
```

Then set `ANTHROPIC_API_KEY` in `backend/.env` (get one at https://console.anthropic.com).
The defaults wire the services together for local Docker; `JWT_SECRET` should be changed for
anything beyond local dev.

### 2. Start the stack

```bash
docker-compose up -d --build
docker-compose run --rm backend alembic upgrade head   # apply DB migrations
```

Services:
- Frontend — http://localhost:3000
- Backend API — http://localhost:8080
- MCP server — http://localhost:8001
- Mailpit (catches all dev email) — http://localhost:8025
- PostgreSQL — localhost:5432

### 3. Use it

Sign up two or more users (each in their own browser/profile so they have separate sessions),
set availability under the settings drawer, then tell your agent who you'd like to meet —
e.g. *"set up a 30 minute sync with @bob on Thursday afternoon."*

### (Optional) connect Google Calendar

Set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in `backend/.env` (Web OAuth client, redirect
URI `http://localhost:8080/auth/google/callback`, Calendar API enabled). A **Connect Google
Calendar** option then appears in the settings drawer. Once connected, availability is
intersected with the user's real free/busy and confirmed meetings are written to their calendar.

---

## Testing / evaluation

`backend/eval/run_eval.py` runs real end-to-end negotiations and independently verifies the
results from the database — catching hallucinated slots, checking timing-constraint adherence
and preference accuracy, and confirming the agents escalate (rather than invent a time) when no
overlap exists:

```bash
docker-compose run --rm backend python -m eval.run_eval
```

See **[SOLUTION.md](SOLUTION.md)** for the full solution narrative and design rationale.

---

## Environment variables

**backend/.env**

```
DATABASE_URL=postgresql+asyncpg://timetomeet:timetomeet@postgres:5432/timetomeet
JWT_SECRET=<change me>
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=10080
MCP_SERVER_URL=http://mcp-server:8001
ANTHROPIC_API_KEY=<your key>
SMTP_HOST=mailpit
SMTP_PORT=1025
FRONTEND_URL=http://localhost:3000
```

**mcp-server/.env**

```
DATABASE_URL=postgresql+asyncpg://timetomeet:timetomeet@postgres:5432/timetomeet
BACKEND_URL=http://backend:8080
```

**frontend/.env.local**

```
NEXT_PUBLIC_BACKEND_URL=http://localhost:8080
NEXT_PUBLIC_WS_URL=ws://localhost:8080
```

> `.env` files are gitignored. Never commit real keys — only the `.env.example` templates.

---

## Notable design decisions

- **Separate MCP server.** All business logic and DB access live behind deterministic,
  user-scoped MCP tools, so the AI layer is auditable, testable in isolation, and swappable.
- **Identity on the connection, not the prompt.** Each agent connects to the MCP server with
  its user's `X-User-Id` header; tools read the caller from there, so the model can't act as a
  different user (and can't get it wrong).
- **Stateless agents.** Agents are built per turn and load their context from the database;
  there are no long-lived agent processes, which keeps the system crash-safe and scalable.
- **Custom async orchestrator (not LangGraph).** Negotiation is open-ended — variable turns and
  tool use — so a plain async round-robin loop fits better than a fixed graph.
- **Calendar is stubbed.** Bookings are stored in the DB; a Google Calendar integration
  (per-user OAuth, real free/busy, real events) is a planned next milestone and only changes
  the implementation of the availability/booking tools — not the agent or tool contracts.

---

## Planned milestones

- Per-user Google Calendar OAuth: real free/busy and event creation.
- A pluggable calendar-provider seam (Google first, others later).
- Recurring meetings, richer preference learning, and analytics.
