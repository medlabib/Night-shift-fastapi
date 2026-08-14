# Night Shift

Fair night-shift rotas for hospital departments — a constraint-solving scheduling engine
with accounts, departments, hand-editing, PDF export and shareable links.

## Quick start

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into SECRET_KEY
docker compose up --build
```

The app is on <http://localhost:8000>, Postgres comes up alongside it, and migrations run
automatically on start. Without Docker:

```bash
pip install -r requirements.txt
export DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/nightshift"
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
alembic upgrade head
uvicorn app.main:app --reload
```

WeasyPrint needs Pango and Cairo, which the Docker image installs. Locally on Debian or
Ubuntu: `apt install libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0`.

## How rotas are built

The engine states the problem once and lets **CP-SAT** (Google OR-Tools) prove an answer,
rather than sampling random rotas and keeping the least-bad one.

**Guaranteed, never traded away:**

- exact nightly coverage, per grade when the department is graded
- booked leave is never worked
- a configurable minimum rest between shifts (`min_rest_nights`, default 1)
- a ceiling on how dense a stretch may get (`max_shifts_per_window`, default 2
  shifts in any `spread_window_nights`, default 7)
- assignments a coordinator has pinned stay pinned

**Optimised, in priority order:** an even points split, then even weekend load, then even
shift counts, then evenly spaced nights, then learned preferences — measured *within* each
grade, since comparing a consultant's load to a resident's is meaningless when each tier is
staffed separately.

### Why spacing is a rule of its own

A minimum rest gap is not enough on its own. Obeying "one night off" at every step still
permits working the 2nd, 4th, 6th, 8th and 10th and nothing for the rest of the month —
legal at each individual step, punishing as a block, and exactly what a rota coordinator
objects to. Two things prevent it: a hard cap on shifts per rolling window, and an
objective term that costs every extra shift inside that window, so among rotas with
identical totals the solver prefers the one that spreads them out. Without the second, the
totals tie and the choice is arbitrary.

Point weights: weekdays 1.0, Saturdays 1.5, Sundays and public holidays 2.0. Departments
can override them.

If a request cannot be met, the engine says why in plain language instead of quietly
leaving nights empty. Arithmetically impossible requests are refused outright; merely
tight ones return the best achievable rota with each gap and its cause attached.

| | random search (before) | CP-SAT (now) |
| --- | --- | --- |
| Points spread, 10 doctors × 30 nights | 2.0 | **0.5** |
| Balance | 91% | **97%** |
| Graded department coverage | 93% | **100%** |
| Over-subscribed request | HTTP 500 | best rota + per-night reasons |
| 60 doctors × 180 nights | not attempted | optimal in ~7s |

### Learned preferences

The solver handles the rules; a small model handles taste. Every manual edit is recorded,
and `POST /api/departments/{id}/preferences/train` fits weights from that history: moving
someone off Fridays repeatedly becomes "avoids Fridays", and the next rota accounts for it.

The weights are deliberately small, decay when the habit stops, need repetition before
they count, and are **soft** — they only break ties between rotas that are already legal,
so a learned preference can never cost coverage or breach leave. `GET .../preferences`
returns each weight with a plain-English explanation, and `DELETE` forgets everything.

## API

Everything under `/api` needs a session cookie, obtained from signup or login.

| Area | Endpoints |
| --- | --- |
| Auth | `POST /api/auth/{signup,login,logout,logout-everywhere}`, `GET /api/auth/session`, `POST /api/auth/password`, `POST /api/auth/password/{reset-request,reset}` |
| Departments | `GET POST /api/departments`, `PATCH /api/departments/{id}`, members, `POST .../invites`, `POST /api/invites/{token}/accept` |
| Roster | `GET POST /api/departments/{id}/doctors`, `PATCH DELETE .../doctors/{id}`, `PUT .../doctors/{id}/leave` |
| Schedules | `POST GET /api/departments/{id}/schedules`, `GET DELETE .../{sid}`, `POST .../publish` |
| Editing | `POST .../{sid}/{assign,unassign,swap,lock,retune}`, `GET .../{sid}/validate` |
| Preferences | `GET DELETE /api/departments/{id}/preferences`, `POST .../preferences/train` |
| Export | `GET .../{sid}/pdf?layout=vertical\|horizontal\|calendar`, `GET .../{sid}/csv` |
| Sharing | `POST GET /api/departments/{id}/schedules/{sid}/shares`, `DELETE .../shares/{id}` |
| Public | `GET /api/shared/{token}`, `.../ics`, `.../pdf`, and the page at `/s/{token}` |
| Legacy | `POST /schedule` — the original API, now answered by the solver |

Interactive docs at `/docs`.

### Editing and fine-tuning

`assign`, `unassign` and `swap` change a rota by hand and mark what they touch as locked.
`validate` re-checks the result against the same rules the solver enforces, and publishing
is refused while errors remain.

`retune` is the interesting one: it re-solves *around* the parts you have settled. Locked
nights are held fixed, and with `stay_close` the solver also pays a penalty for moving
anything else — so the rota people have already seen changes as little as possible.

### Accounts and access

Argon2 password hashing, signed HttpOnly session cookies, throttled logins, single-use
reset tokens, and a session epoch so changing a password signs out every other device.
Three roles: **member** reads, **coordinator** builds and edits, **owner** also manages
people. A department you are not in returns 404 rather than 403, so the API never confirms
which departments exist.

Share links carry a random token; only its hash is stored, so a database leak cannot be
replayed into live links. They can be scoped to one doctor, given an expiry, or revoked.

## PDF layouts

| Layout | Shape | Use |
| --- | --- | --- |
| `vertical` | one row per night, A4 portrait | the diary |
| `horizontal` | doctors as columns, A4 landscape | the wall chart |
| `calendar` | month grid, A4 landscape | the noticeboard |

All three carry the department header, weekend and holiday shading, point weights, a
workload summary and any shortfalls, with page numbers in the footer.

## Tests

```bash
createdb nightshift_test
DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/nightshift_test" \
SECRET_KEY=test pytest -q
```

31 tests covering auth flows, authorisation boundaries, solver constraints against
known-feasible and known-impossible cases, editing and validation, preference learning,
every PDF layout, share-link access and revocation, shift-spacing limits, and legacy API
compatibility.

## Layout

```
app/
  main.py            application assembly
  config.py          settings from the environment
  models.py          database schema
  security.py        hashing, sessions, tokens
  deps.py            current user and department authorisation
  scheduling/
    domain.py        solver-facing types, free of the database
    solver.py        the CP-SAT model
    service.py       database ↔ solver bridge
    preferences.py   learning weights from edit history
  routers/           auth, departments, schedules, exports, share, legacy
  templates/pdf/     the three print layouts
static/              the Rota Studio frontend
migrations/          Alembic
tests/               end-to-end suite
```

`main.py` at the root re-exports the app so `uvicorn main:app` keeps working.
