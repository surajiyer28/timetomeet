"""TimeToMeet evaluation harness.

Runs real, end-to-end agent negotiations against known scenarios and INDEPENDENTLY verifies
the outcome — the agents get no credit for "looking right", only for being right.

Three things are measured, mapping to the challenge's testing bonus:

  * Hallucination detection — for every PROPOSED time we recompute, straight from the
    database, whether that exact slot is genuinely inside EVERY participant's availability
    grid (in their own timezone) and free of conflicts. A proposal outside the real overlap
    is a hallucination and fails. When no overlap exists, the agents must ESCALATE rather
    than invent a time.
  * Constraint adherence — a requested timing ("Thursday") must land on that day.
  * Preference accuracy — a stored preference ("prefers afternoons") must shape the result.

Run inside the backend container:
    docker-compose run --rm backend python -m eval.run_eval
"""
import asyncio
import uuid
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.agents.orchestrator import run_negotiation
from app.agents.scheduling_agent import _tz  # reuse the alias-aware tz resolver

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


# --------------------------------------------------------------------------- setup helpers

async def _reset_eval_users(db):
    """Remove all eval users and everything they created. Matched by the dedicated @eval.local
    email domain so real users are never touched. Order matters: bookings and sessions reference
    users via non-cascading FKs, so clear them before the users."""
    eval_ids = "SELECT id FROM users WHERE email LIKE '%@eval.local'"
    # Any session an eval user touches (as initiator OR participant).
    eval_sessions = f"SELECT session_id FROM session_participants WHERE user_id IN ({eval_ids})"
    await db.execute(text(f"DELETE FROM bookings WHERE session_id IN ({eval_sessions})"))
    await db.execute(text(f"DELETE FROM scheduling_sessions WHERE id IN ({eval_sessions}) OR initiated_by IN ({eval_ids})"))
    await db.execute(text("DELETE FROM users WHERE email LIKE '%@eval.local'"))
    await db.commit()


async def _make_user(db, username: str, tz: str, avail: dict[int, tuple[str, str]],
                     prefs: dict[str, str] | None = None) -> str:
    """avail: {weekday: (start, end)} in local time. Days omitted are unavailable."""
    uid = str(uuid.uuid4())
    await db.execute(
        text("""INSERT INTO users (id, email, password_hash, name, username, timezone)
                VALUES (:id, :email, 'x', :name, :uname, :tz)"""),
        {"id": uid, "email": f"{username}@eval.local", "name": username, "uname": username, "tz": tz},
    )
    for dow, (s, e) in avail.items():
        await db.execute(
            text("""INSERT INTO availability (id, user_id, day_of_week, start_time, end_time, is_available)
                    VALUES (gen_random_uuid(), :uid, :dow, :s, :e, true)"""),
            {"uid": uid, "dow": dow, "s": dtime.fromisoformat(s), "e": dtime.fromisoformat(e)},
        )
    for k, v in (prefs or {}).items():
        await db.execute(
            text("""INSERT INTO agent_memory (id, user_id, key, value, updated_at)
                    VALUES (gen_random_uuid(), :uid, :k, :v, now())"""),
            {"uid": uid, "k": k, "v": v},
        )
    await db.commit()
    return uid


async def _make_session(db, initiator: str, others: list[str],
                        duration: int = 30, timing_note: str | None = None) -> str:
    sid = str(uuid.uuid4())
    now = datetime.now(ZoneInfo("UTC"))
    await db.execute(
        text("""INSERT INTO scheduling_sessions (id, initiated_by, purpose, duration_minutes,
                    timing_note, status, created_at, updated_at)
                VALUES (:id, :by, 'Eval meeting', :dur, :tn, 'NEGOTIATING', :now, :now)"""),
        {"id": sid, "by": initiator, "dur": duration, "tn": timing_note, "now": now},
    )
    await db.execute(
        text("""INSERT INTO session_participants (id, session_id, user_id, role, approval_status)
                VALUES (gen_random_uuid(), :s, :u, 'INITIATOR', 'PENDING')"""),
        {"s": sid, "u": initiator},
    )
    for u in others:
        await db.execute(
            text("""INSERT INTO session_participants (id, session_id, user_id, role, approval_status)
                    VALUES (gen_random_uuid(), :s, :u, 'PARTICIPANT', 'PENDING')"""),
            {"s": sid, "u": u},
        )
    await db.commit()
    return sid


# --------------------------------------------------------------- independent ground-truth check

async def _slot_is_genuinely_free(db, user_id: str, start_utc: datetime, end_utc: datetime) -> tuple[bool, str]:
    """The core anti-hallucination check: is [start,end) really inside this user's availability
    grid (their tz) and free of confirmed bookings? Computed from the DB, not from the agent."""
    row = (await db.execute(text("SELECT timezone FROM users WHERE id = :id"), {"id": user_id})).mappings().first()
    tz = _tz(row["timezone"])
    s_local, e_local = start_utc.astimezone(tz), end_utc.astimezone(tz)

    # Both ends must fall on the same local day inside one availability window.
    if s_local.date() != e_local.date():
        return False, "spans midnight in user's tz"
    grid = (await db.execute(
        text("""SELECT start_time, end_time, is_available FROM availability
                WHERE user_id = :id AND day_of_week = :dow"""),
        {"id": user_id, "dow": s_local.weekday()},
    )).mappings().first()
    if not grid or not grid["is_available"]:
        return False, f"not available on {DAYS[s_local.weekday()]}"
    if not (grid["start_time"] <= s_local.time() and e_local.time() <= grid["end_time"]):
        return False, f"{s_local.time()}–{e_local.time()} outside grid {grid['start_time']}–{grid['end_time']} ({DAYS[s_local.weekday()]})"

    conflict = (await db.execute(
        text("""SELECT 1 FROM bookings b JOIN booking_participants bp ON bp.booking_id = b.id
                WHERE bp.user_id = :id AND b.status = 'CONFIRMED'
                  AND b.start_time < :end AND b.end_time > :start LIMIT 1"""),
        {"id": user_id, "start": start_utc, "end": end_utc},
    )).first()
    if conflict:
        return False, "overlaps an existing booking"
    return True, "ok"


async def _final(db, sid: str) -> dict:
    s = (await db.execute(
        text("SELECT status, proposed_start, proposed_end, timing_note FROM scheduling_sessions WHERE id = :id"),
        {"id": sid},
    )).mappings().first()
    parts = (await db.execute(
        text("SELECT user_id FROM session_participants WHERE session_id = :id"), {"id": sid}
    )).mappings().all()
    return {"status": s["status"], "start": s["proposed_start"], "end": s["proposed_end"],
            "timing_note": s["timing_note"], "participants": [str(p["user_id"]) for p in parts]}


# --------------------------------------------------------------------------------- scenarios

async def scenario(db, name: str, *, users: list[dict], duration: int, timing_note: str | None,
                   expect: str, checks) -> bool:
    print(f"\n{BOLD}▶ {name}{RESET}")
    await _reset_eval_users(db)  # each scenario is self-contained; reuse the same usernames cleanly
    ids = {}
    for u in users:
        ids[u["username"]] = await _make_user(db, u["username"], u["tz"], u["avail"], u.get("prefs"))
    initiator = users[0]["username"]
    sid = await _make_session(db, ids[initiator], [ids[u["username"]] for u in users[1:]],
                              duration=duration, timing_note=timing_note)

    await run_negotiation(sid)
    res = await _final(db, sid)
    print(f"  {DIM}status={res['status']} proposed={res['start']}{RESET}")

    ok = True
    # Outcome expectation (PROPOSED vs ESCALATED)
    if res["status"] != expect:
        print(f"  {RED}✗ expected {expect}, got {res['status']}{RESET}")
        ok = False
    else:
        print(f"  {GREEN}✓ reached {expect}{RESET}")

    for label, passed, detail in await checks(db, res, ids, duration):
        mark = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
        print(f"  {mark} {label}{('' if passed else f'  {DIM}{detail}{RESET}')}")
        ok = ok and passed
    return ok


async def _no_hallucination(db, res, ids, duration):
    """Every participant must genuinely be free at the proposed slot."""
    out = []
    if res["status"] != "PROPOSED" or not res["start"]:
        return out  # nothing proposed; handled by the escalation expectation
    start, end = res["start"], res["end"]
    if (end - start) != timedelta(minutes=duration):
        out.append(("proposed block matches requested duration", False, f"{(end-start)} != {duration}m"))
    for uid in res["participants"]:
        free, why = await _slot_is_genuinely_free(db, uid, start, end)
        out.append((f"slot genuinely free for participant", free, why))
    out.append(("not in the past", start > datetime.now(ZoneInfo("UTC")) - timedelta(minutes=1), "proposed in the past"))
    return out


async def main():
    print(f"{BOLD}TimeToMeet — evaluation harness{RESET}")
    results = []
    async with AsyncSessionLocal() as db:
        await _reset_eval_users(db)

        # 1) Happy path: real overlap exists, agents must find a genuinely-free slot.
        async def c1(db, res, ids, dur):
            return await _no_hallucination(db, res, ids, dur)
        results.append(("Overlap exists → valid, non-hallucinated proposal", await scenario(
            db, "1. No hallucination on the happy path",
            users=[
                {"username": "eval_a", "tz": "America/New_York", "avail": {i: ("09:00", "17:00") for i in range(5)}},
                {"username": "eval_b", "tz": "America/Chicago",  "avail": {i: ("09:00", "17:00") for i in range(5)}},
            ],
            duration=30, timing_note=None, expect="PROPOSED", checks=c1)))

        # 2) Timing constraint: "Thursday" must land on Thursday for the initiator.
        async def c2(db, res, ids, dur):
            out = await _no_hallucination(db, res, ids, dur)
            if res["start"]:
                tz = _tz("America/New_York")
                wd = res["start"].astimezone(tz).weekday()
                out.append(("honored 'Thursday'", wd == 3, f"landed on {DAYS[wd]}"))
            return out
        results.append(("Timing constraint respected", await scenario(
            db, "2. Constraint adherence — 'Thursday'",
            users=[
                {"username": "eval_a", "tz": "America/New_York", "avail": {i: ("09:00", "17:00") for i in range(5)}},
                {"username": "eval_b", "tz": "America/New_York", "avail": {i: ("09:00", "17:00") for i in range(5)}},
            ],
            duration=30, timing_note="Thursday", expect="PROPOSED", checks=c2)))

        # 3) Preference accuracy: initiator prefers afternoons → proposal should be PM local.
        async def c3(db, res, ids, dur):
            out = await _no_hallucination(db, res, ids, dur)
            if res["start"]:
                tz = _tz("America/New_York")
                hr = res["start"].astimezone(tz).hour
                out.append(("applied 'prefers afternoons' (proposed PM)", hr >= 12, f"proposed at {hr}:00 local"))
            return out
        results.append(("Stored preference influenced outcome", await scenario(
            db, "3. Preference accuracy — afternoons",
            users=[
                {"username": "eval_a", "tz": "America/New_York", "avail": {i: ("09:00", "17:00") for i in range(5)},
                 "prefs": {"preferred_time_of_day": "strongly prefers afternoon meetings, after 1pm"}},
                {"username": "eval_b", "tz": "America/New_York", "avail": {i: ("09:00", "17:00") for i in range(5)}},
            ],
            duration=30, timing_note=None, expect="PROPOSED", checks=c3)))

        # 4) No overlap anywhere → must escalate, NOT fabricate a time.
        async def c4(db, res, ids, dur):
            return [("did not fabricate a time", res["start"] is None, f"invented {res['start']}")]
        results.append(("No overlap → correct escalation (no hallucination)", await scenario(
            db, "4. Anti-hallucination — impossible meeting",
            users=[
                # eval_a free Mondays 9–10 ET == 14:00–15:00 UTC
                {"username": "eval_a", "tz": "America/New_York", "avail": {0: ("09:00", "10:00")}},
                # eval_b free Mondays 9–10 PT == 16:00–17:00 UTC → no overlap with eval_a
                {"username": "eval_b", "tz": "America/Los_Angeles", "avail": {0: ("09:00", "10:00")}},
            ],
            duration=30, timing_note=None, expect="ESCALATED", checks=c4)))

        await _reset_eval_users(db)

    print(f"\n{BOLD}── Summary ──{RESET}")
    passed = sum(1 for _, ok in results if ok)
    for label, ok in results:
        print(f"  {(GREEN+'PASS'+RESET) if ok else (RED+'FAIL'+RESET)}  {label}")
    print(f"\n{BOLD}{passed}/{len(results)} scenarios passed{RESET}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
