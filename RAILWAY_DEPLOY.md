# Deploying TimeToMeet to Railway (free HTTPS subdomains)

This deploys the 3 app services + managed Postgres from the GitHub repo. Email uses your
Gmail SMTP (no Mailpit in prod). The repo is already Railway-ready:
- each service honors Railway's injected `$PORT`,
- the backend runs `alembic upgrade head` on boot (schema is created automatically),
- the frontend bakes the public URLs at build time via build args.

You'll do the dashboard steps (I can't reach your Railway account); the exact values are below.

---

## 1. Create the project + database
1. railway.app → **New Project → Deploy from GitHub repo** → pick `surajiyer28/timetomeet`.
   (Cancel/ignore the auto-created service for a moment — we'll add three explicitly.)
2. **+ New → Database → PostgreSQL**. Leave it; we'll reference it.

## 2. Create three services from the same repo
For each, **+ New → GitHub Repo → timetomeet**, then in the service's **Settings**:

| Service name | Settings → **Root Directory** |
|---|---|
| `mcp-server` | `mcp-server` |
| `backend`    | `backend` |
| `frontend`   | `frontend` |

Railway auto-detects each folder's Dockerfile.

## 3. Generate public domains
For **each** of the three services: **Settings → Networking → Generate Domain**. Note the URLs:
- MCP:      `https://mcp-XXXX.up.railway.app`
- BACKEND:  `https://backend-XXXX.up.railway.app`
- FRONTEND: `https://frontend-XXXX.up.railway.app`

## 4. Set environment variables

Use a single shared `DATABASE_URL` (asyncpg scheme, private network — no SSL hassle):

```
postgresql+asyncpg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/${{Postgres.PGDATABASE}}
```

**mcp-server → Variables**
```
DATABASE_URL = postgresql+asyncpg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/${{Postgres.PGDATABASE}}
BACKEND_URL  = https://backend-XXXX.up.railway.app
```

**backend → Variables**
```
DATABASE_URL        = postgresql+asyncpg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/${{Postgres.PGDATABASE}}
JWT_SECRET          = <paste a long random string>
JWT_ALGORITHM       = HS256
JWT_EXPIRE_MINUTES  = 10080
MCP_SERVER_URL      = https://mcp-XXXX.up.railway.app
ANTHROPIC_API_KEY   = <your key>
FRONTEND_URL        = https://frontend-XXXX.up.railway.app
GOOGLE_CLIENT_ID    = <your id>
GOOGLE_CLIENT_SECRET= <your secret>
GOOGLE_REDIRECT_URI = https://backend-XXXX.up.railway.app/auth/google/callback
SMTP_HOST           = smtp.gmail.com
SMTP_PORT           = 587
SMTP_USER           = <your gmail>
SMTP_PASSWORD       = <gmail app password, no spaces>
SMTP_FROM           = TimeToMeet <your gmail>
```

**frontend → Variables** (these are read as build args by the Dockerfile, so a redeploy bakes them in)
```
NEXT_PUBLIC_BACKEND_URL = https://backend-XXXX.up.railway.app
NEXT_PUBLIC_WS_URL      = wss://backend-XXXX.up.railway.app
```

## 5. Update Google OAuth for the public URL
Google Cloud Console → **APIs & Services → Credentials →** your OAuth client →
**Authorized redirect URIs → Add**:
```
https://backend-XXXX.up.railway.app/auth/google/callback
```
Save. (Keep the localhost one too for local dev.)

## 6. Redeploy
Trigger a redeploy of **frontend** (so the build picks up the `NEXT_PUBLIC_*` values) and
**backend** (so it has the URLs/secrets). Watch logs:
- backend should log `Running upgrade ... -> 005` then `Uvicorn running`.
- mcp-server should log the FastMCP banner + `Uvicorn running`.

## 7. Use it
Open the **frontend** URL, sign up a couple of users (real email addresses if you want booking
emails to land), set availability, and schedule. Connect Google Calendar from the settings
drawer (it now uses the public callback).

---

### Notes / gotchas
- **Inter-service calls** use the public HTTPS URLs (`MCP_SERVER_URL`, `BACKEND_URL`) — simplest
  and reliable. The MCP client talks to `${MCP_SERVER_URL}/mcp`.
- **Cost control:** every negotiation is several Claude calls. Keep the app to your own test
  users; don't share the URL widely or it can burn Anthropic credits.
- **Email to fake addresses** (`@test.com`) will bounce silently. Use real inboxes for any
  account whose confirmation emails you want to actually receive.
- **First request may be slow** if a service cold-starts; just retry.
