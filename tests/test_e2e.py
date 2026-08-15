"""End-to-end coverage: auth, authorisation, solving, editing, PDF and sharing."""

from __future__ import annotations

import datetime as dt
import io
import os
from collections import Counter

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://nightshift:nightshift@127.0.0.1:5433/nightshift_test"
)
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
# CP-SAT reaches the same optimal *score* every run, but with several workers
# racing it returns a different one of the equally-optimal rotas each time.
# One worker makes a solve reproducible, which is what lets these tests assert
# on the rota itself rather than only on its score.
os.environ.setdefault("SOLVER_WORKERS", "1")

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

START = dt.date(2026, 9, 1)
END = dt.date(2026, 9, 21)
NAMES = ["Amara Osei", "Bilal Haddad", "Chen Wei", "Dara Nolan",
         "Elias Fournier", "Farah Rahimi", "Gio Ferrari", "Hana Kim"]


@pytest.fixture(scope="module", autouse=True)
def schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def signup(client, email="lead@hospital.org", password="correct-horse-staple", name="Dr Lead"):
    res = client.post("/api/auth/signup", json={
        "email": email, "password": password, "name": name,
        "department_name": "Emergency",
    })
    assert res.status_code == 201, res.text
    return res.json()


def roster(client, department_id, names=NAMES, grade=None):
    ids = []
    for name in names:
        res = client.post(f"/api/departments/{department_id}/doctors",
                          json={"name": name, "grade": grade})
        assert res.status_code == 201, res.text
        ids.append(res.json()["id"])
    return ids


def generate(client, department_id, **overrides):
    body = {
        "start_date": START.isoformat(), "end_date": END.isoformat(),
        "coverage": 2, "min_rest_nights": 1,
        "holidays": [dt.date(2026, 9, 15).isoformat()],
    }
    body.update(overrides)
    return client.post(f"/api/departments/{department_id}/schedules", json=body)


# ───────────────────────────── auth ─────────────────────────────


def test_signup_creates_department_and_session(client):
    data = signup(client, email="first@hospital.org")
    assert data["user"]["email"] == "first@hospital.org"
    assert data["departments"][0]["name"] == "Emergency"
    assert data["departments"][0]["role"] == "owner"
    assert client.cookies.get("nightshift_session")


def test_password_is_never_returned_and_is_hashed(client):
    data = signup(client, email="hash@hospital.org")
    assert "password" not in str(data).lower() or "password_hash" not in str(data)
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "hash@hospital.org"))
        assert user.password_hash.startswith("$argon2")
        assert "correct-horse-staple" not in user.password_hash


def test_weak_password_rejected(client):
    res = client.post("/api/auth/signup", json={
        "email": "weak@hospital.org", "password": "short", "name": "Weak"})
    assert res.status_code == 422
    assert "10 characters" in res.json()["detail"]


def test_duplicate_signup_does_not_confirm_the_address(client):
    signup(client, email="dupe@hospital.org")
    res = client.post("/api/auth/signup", json={
        "email": "dupe@hospital.org", "password": "another-good-password", "name": "Other"})
    assert res.status_code == 409
    assert "dupe@hospital.org" not in res.json()["detail"]


def test_login_logout_roundtrip(client):
    signup(client, email="round@hospital.org", password="a-perfectly-fine-password")
    client.post("/api/auth/logout")
    client.cookies.clear()
    assert client.get("/api/auth/session").status_code == 401

    res = client.post("/api/auth/login", json={
        "email": "round@hospital.org", "password": "a-perfectly-fine-password"})
    assert res.status_code == 200
    assert client.get("/api/auth/session").status_code == 200


def test_wrong_password_rejected(client):
    signup(client, email="wrong@hospital.org", password="the-real-password-x")
    client.cookies.clear()
    res = client.post("/api/auth/login", json={
        "email": "wrong@hospital.org", "password": "not-the-password"})
    assert res.status_code == 401


def test_password_reset_flow(client):
    signup(client, email="reset@hospital.org", password="original-password-1")
    token = client.post("/api/auth/password/reset-request",
                        json={"email": "reset@hospital.org"}).json()["token"]

    assert client.post("/api/auth/password/reset", json={
        "token": token, "new_password": "brand-new-password-2"}).status_code == 204
    # The token is single use.
    assert client.post("/api/auth/password/reset", json={
        "token": token, "new_password": "third-password-3"}).status_code == 400

    client.cookies.clear()
    assert client.post("/api/auth/login", json={
        "email": "reset@hospital.org", "password": "brand-new-password-2"}).status_code == 200


def test_reset_for_unknown_email_reveals_nothing(client):
    res = client.post("/api/auth/password/reset-request", json={"email": "ghost@hospital.org"})
    assert res.status_code == 200 and res.json()["sent"] is True


# ─────────────────────── authorisation boundaries ───────────────────────


def test_other_users_department_is_not_reachable(client):
    owner = signup(client, email="owner@hospital.org")
    department_id = owner["departments"][0]["id"]
    client.cookies.clear()

    signup(client, email="stranger@hospital.org")
    for path in (f"/api/departments/{department_id}/doctors",
                 f"/api/departments/{department_id}/schedules"):
        res = client.get(path)
        # 404 rather than 403: the API does not confirm the department exists.
        assert res.status_code == 404, path


def test_member_cannot_edit_roster(client):
    owner = signup(client, email="boss@hospital.org")
    department_id = owner["departments"][0]["id"]
    invite = client.post(f"/api/departments/{department_id}/invites",
                         json={"email": "junior@hospital.org", "role": "member"}).json()
    token = invite["invite_url"].rsplit("/", 1)[1]

    client.cookies.clear()
    signup(client, email="junior@hospital.org")
    assert client.post(f"/api/invites/{token}/accept").status_code == 200

    assert client.get(f"/api/departments/{department_id}/doctors").status_code == 200
    res = client.post(f"/api/departments/{department_id}/doctors", json={"name": "Sneaky"})
    assert res.status_code == 403
    assert "coordinator" in res.json()["detail"]


def test_invite_bound_to_the_invited_address(client):
    owner = signup(client, email="inviter@hospital.org")
    department_id = owner["departments"][0]["id"]
    invite = client.post(f"/api/departments/{department_id}/invites",
                         json={"email": "intended@hospital.org"}).json()
    token = invite["invite_url"].rsplit("/", 1)[1]

    client.cookies.clear()
    signup(client, email="interloper@hospital.org")
    assert client.post(f"/api/invites/{token}/accept").status_code == 403


def test_anonymous_is_refused(client):
    client.cookies.clear()
    assert client.get("/api/departments").status_code == 401


# ───────────────────────── solving & editing ─────────────────────────


def test_generate_respects_every_hard_constraint(client):
    account = signup(client, email="solver@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id)

    # Book leave for one doctor across the first week.
    leave = [(START + dt.timedelta(days=i)).isoformat() for i in range(7)]
    client.put(f"/api/departments/{department_id}/doctors/{ids[0]}/leave",
               json={"dates": leave})

    res = generate(client, department_id)
    assert res.status_code == 201, res.text
    body = res.json()

    assert body["solver_status"] in {"OPTIMAL", "FEASIBLE"}
    assert body["metrics"]["coverage"] == 100.0
    assert not body["shortfalls"]

    by_date: dict[str, list] = {}
    for row in body["assignments"]:
        by_date.setdefault(row["date"], []).append(row)

    nights = (END - START).days + 1
    assert len(by_date) == nights
    assert all(len(v) == 2 for v in by_date.values()), "every night needs exactly 2 on call"

    # Leave is honoured.
    on_leave = {r["date"] for r in body["assignments"] if r["doctor_id"] == ids[0]}
    assert not (on_leave & set(leave))

    # Rest rule: nobody works two nights running.
    per_doctor: dict[str, list[dt.date]] = {}
    for row in body["assignments"]:
        per_doctor.setdefault(row["doctor_id"], []).append(dt.date.fromisoformat(row["date"]))
    for days in per_doctor.values():
        ordered = sorted(days)
        assert all((b - a).days > 1 for a, b in zip(ordered, ordered[1:]))


def test_fairness_beats_the_old_random_search(client):
    account = signup(client, email="fair@hospital.org")
    department_id = account["departments"][0]["id"]
    roster(client, department_id)

    metrics = generate(client, department_id).json()["metrics"]
    # The random sampler managed a spread of 2.0 and ~91% balance here.
    assert metrics["points_spread"] <= 1.0
    assert metrics["balance"] >= 95.0


def test_impossible_request_explains_itself(client):
    account = signup(client, email="hard@hospital.org")
    department_id = account["departments"][0]["id"]
    roster(client, department_id, names=NAMES[:3])

    res = generate(client, department_id, coverage=9)
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert "reasons" in detail and detail["reasons"]
    assert any("only 3" in r or "at most" in r for r in detail["reasons"])


def test_graded_department_staffs_each_grade(client):
    account = signup(client, email="graded@hospital.org")
    department_id = account["departments"][0]["id"]
    for name, grade in zip(NAMES, ["Senior", "Junior"] * 4):
        client.post(f"/api/departments/{department_id}/doctors",
                    json={"name": name, "grade": grade})

    res = generate(client, department_id, coverage=1, graded=True,
                   grades=["Senior", "Junior"])
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["metrics"]["coverage"] == 100.0

    by_date: dict[str, set] = {}
    for row in body["assignments"]:
        by_date.setdefault(row["date"], set()).add(row["grade"])
    assert all(v == {"Senior", "Junior"} for v in by_date.values())


def test_edit_swap_and_validate(client):
    account = signup(client, email="edit@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id)
    schedule = generate(client, department_id).json()
    schedule_id = schedule["id"]

    first = schedule["assignments"][0]
    on_that_night = {a["doctor_id"] for a in schedule["assignments"] if a["date"] == first["date"]}
    replacement = next(i for i in ids if i not in on_that_night)

    res = client.post(f"/api/departments/{department_id}/schedules/{schedule_id}/swap", json={
        "date": first["date"], "doctor_out": first["doctor_id"], "doctor_in": replacement})
    assert res.status_code == 200, res.text
    after = res.json()

    swapped = [a for a in after["assignments"] if a["date"] == first["date"]]
    assert replacement in {a["doctor_id"] for a in swapped}
    assert first["doctor_id"] not in {a["doctor_id"] for a in swapped}
    assert next(a for a in swapped if a["doctor_id"] == replacement)["locked"] is True

    # Removing someone leaves the night short, and validation says so.
    client.post(f"/api/departments/{department_id}/schedules/{schedule_id}/unassign",
                json={"doctor_id": replacement, "date": first["date"]})
    check = client.get(
        f"/api/departments/{department_id}/schedules/{schedule_id}/validate").json()
    assert check["ok"] is False
    assert any("1 of 2 on call" in e for e in check["errors"])

    # And publishing is refused while it is broken.
    assert client.post(
        f"/api/departments/{department_id}/schedules/{schedule_id}/publish").status_code == 422


def test_retune_keeps_locked_nights(client):
    account = signup(client, email="retune@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id)
    schedule = generate(client, department_id).json()
    schedule_id = schedule["id"]

    # Pin the first four assignments.
    pinned = []
    for row in schedule["assignments"][:4]:
        client.post(f"/api/departments/{department_id}/schedules/{schedule_id}/lock", json={
            "doctor_id": row["doctor_id"], "date": row["date"], "locked": True})
        pinned.append((row["doctor_id"], row["date"]))

    res = client.post(f"/api/departments/{department_id}/schedules/{schedule_id}/retune",
                      json={"keep_locked": True, "stay_close": True})
    assert res.status_code == 200, res.text
    after = {(a["doctor_id"], a["date"]) for a in res.json()["assignments"]}
    for pin in pinned:
        assert pin in after, f"pinned assignment {pin} was moved"


def test_assignment_outside_the_period_is_refused(client):
    account = signup(client, email="range@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id)
    schedule_id = generate(client, department_id).json()["id"]

    res = client.post(f"/api/departments/{department_id}/schedules/{schedule_id}/assign", json={
        "doctor_id": ids[0], "date": (END + dt.timedelta(days=5)).isoformat()})
    assert res.status_code == 422
    assert "outside this schedule" in res.json()["detail"]


# ───────────────────────── exports & sharing ─────────────────────────


@pytest.mark.parametrize("layout", ["vertical", "horizontal", "calendar"])
def test_pdf_layouts_render(client, layout):
    account = signup(client, email=f"pdf-{layout}@hospital.org")
    department_id = account["departments"][0]["id"]
    roster(client, department_id)
    schedule_id = generate(client, department_id).json()["id"]

    res = client.get(
        f"/api/departments/{department_id}/schedules/{schedule_id}/pdf?layout={layout}")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF-")
    assert len(res.content) > 2000


def test_share_link_reads_without_an_account(client):
    account = signup(client, email="share@hospital.org")
    department_id = account["departments"][0]["id"]
    roster(client, department_id)
    schedule_id = generate(client, department_id).json()["id"]

    share = client.post(
        f"/api/departments/{department_id}/schedules/{schedule_id}/shares",
        json={"label": "Ward noticeboard"}).json()
    token = share["url"].rsplit("/", 1)[1]

    client.cookies.clear()
    res = client.get(f"/api/shared/{token}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["read_only"] is True
    assert body["schedule"]["assignments"]
    assert body["department"]["name"] == "Emergency"

    assert client.get(f"/api/shared/{token}/ics").status_code == 200
    assert client.get(f"/api/shared/{token}/pdf?layout=calendar").content.startswith(b"%PDF-")


def test_share_link_can_be_scoped_to_one_doctor(client):
    account = signup(client, email="scoped@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id)
    schedule_id = generate(client, department_id).json()["id"]

    share = client.post(
        f"/api/departments/{department_id}/schedules/{schedule_id}/shares",
        json={"doctor_id": ids[0]}).json()
    token = share["url"].rsplit("/", 1)[1]

    client.cookies.clear()
    body = client.get(f"/api/shared/{token}").json()
    assert {a["doctor_id"] for a in body["schedule"]["assignments"]} == {ids[0]}


def test_revoked_share_link_stops_working(client):
    account = signup(client, email="revoke@hospital.org")
    department_id = account["departments"][0]["id"]
    roster(client, department_id)
    schedule_id = generate(client, department_id).json()["id"]

    share = client.post(
        f"/api/departments/{department_id}/schedules/{schedule_id}/shares", json={}).json()
    token = share["url"].rsplit("/", 1)[1]
    assert client.get(f"/api/shared/{token}").status_code == 200

    client.delete(
        f"/api/departments/{department_id}/schedules/{schedule_id}/shares/{share['id']}")
    client.cookies.clear()
    assert client.get(f"/api/shared/{token}").status_code == 404


def test_share_token_is_not_stored_in_clear(client):
    account = signup(client, email="tokens@hospital.org")
    department_id = account["departments"][0]["id"]
    roster(client, department_id)
    schedule_id = generate(client, department_id).json()["id"]
    share = client.post(
        f"/api/departments/{department_id}/schedules/{schedule_id}/shares", json={}).json()
    token = share["url"].rsplit("/", 1)[1]

    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import ShareLink
    with SessionLocal() as db:
        rows = db.scalars(select(ShareLink)).all()
        assert all(token not in row.token_hash for row in rows)

    # Listing shares never hands the token back.
    listed = client.get(
        f"/api/departments/{department_id}/schedules/{schedule_id}/shares").json()
    assert all(item.get("url") is None for item in listed)


# ───────────────────────── legacy compatibility ─────────────────────────


def test_legacy_endpoint_still_answers(client):
    res = client.post("/schedule", json={
        "doctor_names": ",".join(NAMES),
        "start_date": START.isoformat(), "end_date": END.isoformat(),
        "same_num_doctors": "Y", "num_doctors": 2,
        "num_doctors_per_night": None, "holiday_days": "2026-09-15",
        "find": 400, "department_is_graded": "N",
        "doctors_grades": None, "shift_requirements": None, "grades": None,
        "doctor_not_present": {NAMES[0]: "2026-09-03,2026-09-04"},
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["schedule"] and body["points"] and body["schedule_name"]
    assert body["solver"]["coverage"] == 100.0
    # The old shape: date -> [[name, points], ...]
    first = body["schedule"]["2026-09-01"]
    assert isinstance(first, list) and isinstance(first[0], list)
    # Leave is respected even through the legacy route.
    assert NAMES[0] not in [n for n, _ in body["schedule"].get("2026-09-03", [])]


# ───────────────────────── learned preferences ─────────────────────────


def test_preferences_are_learned_from_edits_and_change_the_rota(client):
    account = signup(client, email="learn@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id)
    base = f"/api/departments/{department_id}/schedules"
    prefs = f"/api/departments/{department_id}/preferences"

    assert client.get(prefs).json() == [], "nothing should be learned yet"

    # A coordinator moves the same doctor off Fridays, rota after rota — which
    # is how a real preference shows up in the record. Which doctor the solver
    # puts on a Friday is its own business, so rather than naming one up front
    # the test moves off whoever it has moved off before, and asks afterwards
    # who the habit landed on.
    fridays = sorted(d.isoformat() for d in _days() if d.weekday() == 4)
    moved_off, moved_on = Counter(), Counter()

    for _ in range(4):
        schedule_id = generate(client, department_id).json()["id"]
        state = client.get(f"{base}/{schedule_id}").json()
        for friday in fridays:
            on_call = [a["doctor_id"] for a in state["assignments"] if a["date"] == friday]
            stand_in = next((i for i in reversed(ids) if i not in on_call), None)
            if not on_call or stand_in is None:
                continue
            # Whoever has been moved off most already, so the habit concentrates
            # on one person instead of smearing across the roster.
            out = max(on_call, key=lambda d: (moved_off[d], -ids.index(d)))
            if client.post(f"{base}/{schedule_id}/swap", json={
                "date": friday, "doctor_out": out, "doctor_in": stand_in,
            }).status_code == 200:
                moved_off[out] += 1
                moved_on[stand_in] += 1

    target = max(ids, key=lambda d: moved_off[d] - moved_on[d])
    moved = moved_off[target] - moved_on[target]
    assert moved >= 2, f"expected a repeated Friday habit, off={moved_off} on={moved_on}"

    learned = client.post(prefs + "/train").json()
    friday_rule = [w for w in learned if w["feature"] == "dow:4" and w["doctor_id"] == target]
    assert friday_rule, f"no Friday preference learned from {moved} edits"
    assert friday_rule[0]["weight"] < 0, "moving someone off Fridays should read as avoidance"
    assert "avoids Fridays" in friday_rule[0]["explanation"]

    # The learned weight should steer the next rota without breaking it.
    with_prefs = generate(client, department_id, name="with").json()
    without = generate(client, department_id, name="without", use_preferences=False).json()

    def friday_count(schedule):
        return sum(
            1 for a in schedule["assignments"]
            if a["doctor_id"] == target and dt.date.fromisoformat(a["date"]).weekday() == 4
        )

    assert friday_count(with_prefs) <= friday_count(without)
    assert with_prefs["metrics"]["coverage"] == 100.0, "preferences must not break coverage"


def test_preferences_can_be_audited_and_cleared(client):
    account = signup(client, email="audit@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id)
    base = f"/api/departments/{department_id}/schedules"
    prefs = f"/api/departments/{department_id}/preferences"
    schedule_id = generate(client, department_id).json()["id"]

    state = client.get(f"{base}/{schedule_id}").json()
    for row in state["assignments"][:4]:
        client.post(f"{base}/{schedule_id}/unassign", json={
            "doctor_id": row["doctor_id"], "date": row["date"]})

    client.post(prefs + "/train")
    described = client.get(prefs).json()
    for row in described:
        # Every weight explains itself in words a coordinator can check.
        assert row["explanation"] and ("prefers" in row["explanation"] or "avoids" in row["explanation"])
        assert row["doctor"] != "the department" or row["doctor_id"] is None

    assert client.delete(prefs).status_code == 204
    assert client.get(prefs).json() == []


def _days():
    return [START + dt.timedelta(days=i) for i in range((END - START).days + 1)]


def test_no_doctor_gets_an_every_other_night_run(client):
    """A minimum rest gap alone permits shift/rest/shift/rest for a fortnight.

    That pattern obeys the rule at every individual step and is still
    punishing, so density is capped over a rolling window as well.
    """
    account = signup(client, email="spacing@hospital.org")
    department_id = account["departments"][0]["id"]
    roster(client, department_id, names=NAMES + ["Kwame Mensah", "Lena Vogt"])

    body = client.post(f"/api/departments/{department_id}/schedules", json={
        "start_date": START.isoformat(), "end_date": dt.date(2026, 9, 30).isoformat(),
        "coverage": 2, "min_rest_nights": 1,
        "max_shifts_per_window": 2, "spread_window_nights": 7,
    }).json()

    per_doctor: dict[str, list[dt.date]] = {}
    for row in body["assignments"]:
        per_doctor.setdefault(row["doctor_id"], []).append(dt.date.fromisoformat(row["date"]))

    for doctor_id, days in per_doctor.items():
        ordered = sorted(days)
        # No more than 2 shifts inside any 7-night window.
        for i in range(len(ordered) - 2):
            window = ordered[i:i + 3]
            assert (window[-1] - window[0]).days >= 7, (
                f"{doctor_id} works {[d.isoformat() for d in window]} "
                "— three shifts inside a week"
            )
        # An isolated two-day gap is fine; a *run* of them is the pattern
        # people object to, so no two tight gaps may sit back to back.
        gaps = [(b - a).days for a, b in zip(ordered, ordered[1:])]
        runs = [(a, b) for a, b in zip(gaps, gaps[1:]) if a <= 2 and b <= 2]
        assert not runs, f"{doctor_id} has consecutive tight gaps: {gaps}"

    assert body["metrics"]["coverage"] == 100.0, "spacing must not cost coverage"


def test_spacing_cap_is_explained_when_it_cannot_be_met(client):
    account = signup(client, email="dense@hospital.org")
    department_id = account["departments"][0]["id"]
    roster(client, department_id, names=NAMES[:4])

    # 4 doctors, 2 a night, capped at 1 shift per 7 nights is impossible.
    res = client.post(f"/api/departments/{department_id}/schedules", json={
        "start_date": START.isoformat(), "end_date": END.isoformat(),
        "coverage": 2, "max_shifts_per_window": 1, "spread_window_nights": 7,
    })
    assert res.status_code == 422
    reasons = " ".join(res.json()["detail"]["reasons"])
    assert "in any 7 nights" in reasons
    assert "raise the shifts-per-window cap" in reasons


# ────────────────── carrying fairness across periods ──────────────────


def test_a_heavy_month_is_paid_back_in_the_next_one(client):
    """The point of carry-forward: last month's load shapes this month's."""
    account = signup(client, email="carry@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id)
    base = f"/api/departments/{department_id}/schedules"

    august = client.post(base, json={
        "start_date": "2026-08-01", "end_date": "2026-08-21", "coverage": 2,
    })
    assert august.status_code == 201, august.text
    august_id = august.json()["id"]

    # Load one doctor up by hand, then publish: only published rotas count as
    # history, so a draft cannot distort the next period.
    heavy = ids[0]
    worked = {
        a["date"] for a in august.json()["assignments"] if a["doctor_id"] == heavy
    }
    added = 0
    for day in _august_days():
        if added >= 4:
            break
        iso = day.isoformat()
        if iso in worked:
            continue
        on_call = [a["doctor_id"] for a in august.json()["assignments"] if a["date"] == iso]
        if heavy in on_call or not on_call:
            continue
        if client.post(f"{base}/{august_id}/swap", json={
            "date": iso, "doctor_out": on_call[0], "doctor_in": heavy,
        }).status_code == 200:
            added += 1
    assert added >= 3, "could not load the doctor up for the first period"

    client.post(f"{base}/{august_id}/publish")
    august_state = client.get(f"{base}/{august_id}").json()
    august_points = august_state["metrics"]["per_doctor"][heavy]["points"]

    september = client.post(base, json={
        "start_date": "2026-09-01", "end_date": "2026-09-21", "coverage": 2,
    })
    assert september.status_code == 201, september.text
    metrics = september.json()["metrics"]

    assert metrics["carry_forward"] is True
    carried = metrics["per_doctor"][heavy]
    assert carried["prior_points"] == pytest.approx(august_points, abs=0.01), (
        "September should know what August cost them"
    )

    # Having done more in August, they do less in September than the busiest.
    this_period = {d: metrics["per_doctor"][d]["points"] for d in ids}
    assert this_period[heavy] < max(this_period.values()), (
        f"a heavy August should buy a lighter September: {this_period}"
    )
    # And the running total across both months is tighter than the raw
    # month-on-month totals would have been.
    cumulative = [metrics["per_doctor"][d]["cumulative_points"] for d in ids]
    assert max(cumulative) - min(cumulative) < (august_points - min(
        august_state["metrics"]["per_doctor"][d]["points"] for d in ids
    )), "carrying forward should close the gap, not widen it"


def test_carry_forward_can_be_switched_off(client):
    account = signup(client, email="nocarry@hospital.org")
    department_id = account["departments"][0]["id"]
    roster(client, department_id)
    base = f"/api/departments/{department_id}/schedules"

    first = client.post(base, json={
        "start_date": "2026-08-01", "end_date": "2026-08-21", "coverage": 2,
    })
    client.post(f"{base}/{first.json()['id']}/publish")

    off = client.post(base, json={
        "start_date": "2026-09-01", "end_date": "2026-09-21", "coverage": 2,
        "carry_forward_days": 0,
    })
    assert off.status_code == 201
    assert off.json()["metrics"]["carry_forward"] is False


def test_drafts_are_not_counted_as_history(client):
    account = signup(client, email="drafts@hospital.org")
    department_id = account["departments"][0]["id"]
    roster(client, department_id)
    base = f"/api/departments/{department_id}/schedules"

    # Three attempts at the same month, none published.
    for _ in range(3):
        assert client.post(base, json={
            "start_date": "2026-08-01", "end_date": "2026-08-21", "coverage": 2,
        }).status_code == 201

    later = client.post(base, json={
        "start_date": "2026-09-01", "end_date": "2026-09-21", "coverage": 2,
    })
    assert later.json()["metrics"]["carry_forward"] is False, (
        "unpublished attempts must not be charged to anyone"
    )


def _august_days():
    start = dt.date(2026, 8, 1)
    return [start + dt.timedelta(days=i) for i in range(21)]


# ─────────────────────── doctors with accounts ───────────────────────


def _member(client, department_id, email, *, role="member", doctor_id=None):
    """Invite someone, sign them up, accept — returns their session payload."""
    body = {"email": email, "role": role}
    if doctor_id:
        body["doctor_id"] = doctor_id
    invite = client.post(f"/api/departments/{department_id}/invites", json=body)
    assert invite.status_code == 201, invite.text
    token = invite.json()["invite_url"].rsplit("/", 1)[1]

    owner_cookies = dict(client.cookies)
    client.cookies.clear()
    signup(client, email=email, name=email.split("@")[0].title())
    assert client.post(f"/api/invites/{token}/accept").status_code == 200
    member_cookies = dict(client.cookies)

    client.cookies.clear()
    client.cookies.update(owner_cookies)
    return member_cookies


def test_an_invite_can_hand_over_a_roster_entry(client):
    account = signup(client, email="handover@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id, names=NAMES[:4])

    member = _member(client, department_id, "amara@hospital.org", doctor_id=ids[0])

    # The coordinator sees the link.
    doctors = client.get(f"/api/departments/{department_id}/doctors").json()
    linked = next(d for d in doctors if d["id"] == ids[0])
    assert linked["user_id"] is not None
    assert linked["user_name"] == "Amara"

    # And the doctor arrives on their own roster entry.
    client.cookies.clear()
    client.cookies.update(member)
    mine = client.get("/api/me").json()
    assert [d["id"] for d in mine["doctors"]] == [ids[0]]


def test_a_doctor_sees_only_their_own_shifts(client):
    account = signup(client, email="ownshifts@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id)
    base = f"/api/departments/{department_id}/schedules"

    # A period that is definitely in the future, so it lands in the horizon.
    start = dt.date.today() + dt.timedelta(days=3)
    end = start + dt.timedelta(days=20)
    created = client.post(base, json={
        "start_date": start.isoformat(), "end_date": end.isoformat(), "coverage": 2,
    })
    assert created.status_code == 201, created.text
    mine_expected = {
        a["date"] for a in created.json()["assignments"] if a["doctor_id"] == ids[1]
    }

    member = _member(client, department_id, "bilal@hospital.org", doctor_id=ids[1])
    client.cookies.clear()
    client.cookies.update(member)

    shifts = client.get("/api/me/shifts").json()
    assert {s["date"] for s in shifts} == mine_expected
    assert all(s["doctor_id"] == ids[1] for s in shifts)
    # Each night says who else is on, so a swap can be aimed at someone.
    assert any(s["alongside"] for s in shifts)


def test_leave_request_is_approved_and_reaches_the_solver(client):
    account = signup(client, email="leavereq@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id)

    member = _member(client, department_id, "chen@hospital.org", doctor_id=ids[2])
    away_from = dt.date.today() + dt.timedelta(days=40)
    away_to = away_from + dt.timedelta(days=4)

    client.cookies.clear()
    client.cookies.update(member)
    asked = client.post("/api/me/time-off", json={
        "start_date": away_from.isoformat(), "end_date": away_to.isoformat(),
        "reason": "Family",
    })
    assert asked.status_code == 201, asked.text
    assert asked.json()["status"] == "pending"
    assert asked.json()["nights"] == 5
    request_id = asked.json()["id"]

    # Asking twice for the same dates is refused.
    assert client.post("/api/me/time-off", json={
        "start_date": away_from.isoformat(), "end_date": away_to.isoformat(),
    }).status_code == 409

    client.cookies.clear()
    signup(client, email="leaveboss@hospital.org")   # a stranger cannot decide
    assert client.post(
        f"/api/departments/{department_id}/time-off/{request_id}/decide",
        json={"approve": True},
    ).status_code == 404

    client.cookies.clear()
    client.post("/api/auth/login", json={
        "email": "leavereq@hospital.org", "password": "correct-horse-staple"})

    inbox = client.get(f"/api/departments/{department_id}/requests").json()
    assert [r["id"] for r in inbox["time_off"]] == [request_id]
    assert inbox["time_off"][0]["doctor_name"] == NAMES[2]

    decided = client.post(
        f"/api/departments/{department_id}/time-off/{request_id}/decide",
        json={"approve": True, "note": "Enjoy it"},
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"

    # Approval writes real leave, which the solver treats as unavailable.
    doctors = client.get(f"/api/departments/{department_id}/doctors").json()
    booked = next(d for d in doctors if d["id"] == ids[2])["leave"]
    assert booked == [(away_from + dt.timedelta(days=i)).isoformat() for i in range(5)]

    rota = client.post(f"/api/departments/{department_id}/schedules", json={
        "start_date": away_from.isoformat(),
        "end_date": (away_to + dt.timedelta(days=16)).isoformat(),
        "coverage": 2,
    })
    assert rota.status_code == 201, rota.text
    worked = {a["date"] for a in rota.json()["assignments"] if a["doctor_id"] == ids[2]}
    assert not worked & set(booked), "approved leave must never be worked"

    # Deciding twice is refused.
    assert client.post(
        f"/api/departments/{department_id}/time-off/{request_id}/decide",
        json={"approve": False},
    ).status_code == 409


def test_a_declined_leave_request_books_nothing(client):
    account = signup(client, email="declined@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id, names=NAMES[:4])
    member = _member(client, department_id, "dara@hospital.org", doctor_id=ids[3])

    away = dt.date.today() + dt.timedelta(days=30)
    client.cookies.clear()
    client.cookies.update(member)
    request_id = client.post("/api/me/time-off", json={
        "start_date": away.isoformat(), "end_date": away.isoformat()}).json()["id"]

    client.cookies.clear()
    client.post("/api/auth/login", json={
        "email": "declined@hospital.org", "password": "correct-horse-staple"})
    res = client.post(
        f"/api/departments/{department_id}/time-off/{request_id}/decide",
        json={"approve": False, "note": "We are too thin that week"},
    )
    assert res.json()["status"] == "declined"

    doctors = client.get(f"/api/departments/{department_id}/doctors").json()
    assert next(d for d in doctors if d["id"] == ids[3])["leave"] == []


def test_a_doctor_proposes_a_swap_and_the_coordinator_approves_it(client):
    account = signup(client, email="swapreq@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id)
    base = f"/api/departments/{department_id}/schedules"

    start = dt.date.today() + dt.timedelta(days=5)
    created = client.post(base, json={
        "start_date": start.isoformat(),
        "end_date": (start + dt.timedelta(days=20)).isoformat(),
        "coverage": 2,
    })
    schedule_id = created.json()["id"]
    assignments = created.json()["assignments"]

    mine = next(a for a in assignments if a["doctor_id"] == ids[4])
    night = mine["date"]
    on_call = {a["doctor_id"] for a in assignments if a["date"] == night}
    colleague = next(i for i in ids if i not in on_call)

    member = _member(client, department_id, "elias@hospital.org", doctor_id=ids[4])
    client.cookies.clear()
    client.cookies.update(member)

    proposed = client.post("/api/me/swaps", json={
        "schedule_id": schedule_id, "date": night,
        "to_doctor_id": colleague, "message": "Wedding",
    })
    assert proposed.status_code == 201, proposed.text
    swap_id = proposed.json()["id"]
    assert proposed.json()["from_doctor_name"] == NAMES[4]

    # A night they do not work cannot be offered.
    not_mine = next(
        a for a in assignments if a["doctor_id"] != ids[4] and a["date"] != night
    )
    assert client.post("/api/me/swaps", json={
        "schedule_id": schedule_id, "date": not_mine["date"], "to_doctor_id": colleague,
    }).status_code == 404

    client.cookies.clear()
    client.post("/api/auth/login", json={
        "email": "swapreq@hospital.org", "password": "correct-horse-staple"})

    approved = client.post(
        f"/api/departments/{department_id}/swaps/{swap_id}/decide", json={"approve": True})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    after = client.get(f"{base}/{schedule_id}").json()["assignments"]
    that_night = {a["doctor_id"] for a in after if a["date"] == night}
    assert colleague in that_night and ids[4] not in that_night

    # An approved swap is a rota edit like any other, so it is in the history.
    history = client.get(f"{base}/{schedule_id}/history").json()
    assert any(h["kind"] == "swap" and night[-2:] in h["summary"] for h in history)


def test_a_swap_that_the_rota_has_outgrown_is_refused(client):
    account = signup(client, email="stale@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id)
    base = f"/api/departments/{department_id}/schedules"

    start = dt.date.today() + dt.timedelta(days=5)
    created = client.post(base, json={
        "start_date": start.isoformat(),
        "end_date": (start + dt.timedelta(days=20)).isoformat(), "coverage": 2,
    })
    schedule_id = created.json()["id"]
    assignments = created.json()["assignments"]
    mine = next(a for a in assignments if a["doctor_id"] == ids[5])
    night = mine["date"]
    on_call = {a["doctor_id"] for a in assignments if a["date"] == night}
    colleague = next(i for i in ids if i not in on_call)

    member = _member(client, department_id, "farah@hospital.org", doctor_id=ids[5])
    client.cookies.clear()
    client.cookies.update(member)
    swap_id = client.post("/api/me/swaps", json={
        "schedule_id": schedule_id, "date": night, "to_doctor_id": colleague,
    }).json()["id"]

    client.cookies.clear()
    client.post("/api/auth/login", json={
        "email": "stale@hospital.org", "password": "correct-horse-staple"})

    # The coordinator puts the colleague on that night by hand first.
    client.post(f"{base}/{schedule_id}/swap", json={
        "date": night, "doctor_out": ids[5], "doctor_in": colleague})

    res = client.post(
        f"/api/departments/{department_id}/swaps/{swap_id}/decide", json={"approve": True})
    assert res.status_code == 409
    assert "not on call" in res.json()["detail"] or "already" in res.json()["detail"]


def test_an_unlinked_account_has_no_shifts_to_show(client):
    account = signup(client, email="unlinked@hospital.org")
    department_id = account["departments"][0]["id"]
    roster(client, department_id, names=NAMES[:4])
    member = _member(client, department_id, "nobody@hospital.org")

    client.cookies.clear()
    client.cookies.update(member)
    assert client.get("/api/me").json()["doctors"] == []
    assert client.get("/api/me/shifts").json() == []
    res = client.post("/api/me/time-off", json={
        "start_date": (dt.date.today() + dt.timedelta(days=5)).isoformat(),
        "end_date": (dt.date.today() + dt.timedelta(days=6)).isoformat()})
    assert res.status_code == 403
    assert "not linked" in res.json()["detail"]


# ───────────────────────── the audit trail ─────────────────────────


def test_history_says_who_changed_what(client):
    account = signup(client, email="history@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id)
    base = f"/api/departments/{department_id}/schedules"
    schedule_id = generate(client, department_id).json()["id"]

    state = client.get(f"{base}/{schedule_id}").json()
    row = state["assignments"][0]
    on_call = {a["doctor_id"] for a in state["assignments"] if a["date"] == row["date"]}
    stand_in = next(i for i in ids if i not in on_call)

    client.post(f"{base}/{schedule_id}/swap", json={
        "date": row["date"], "doctor_out": row["doctor_id"], "doctor_in": stand_in})
    client.post(f"{base}/{schedule_id}/unassign", json={
        "doctor_id": stand_in, "date": row["date"]})

    history = client.get(f"{base}/{schedule_id}/history").json()
    assert len(history) >= 2
    assert history[0]["created_at"] >= history[-1]["created_at"], "newest first"

    kinds = [h["kind"] for h in history]
    assert "swap" in kinds and "unassign" in kinds
    for entry in history:
        assert entry["actor"] == "Dr Lead"
        assert entry["summary"].startswith("Dr Lead ")
        assert entry["schedule_name"]

    swap = next(h for h in history if h["kind"] == "swap")
    assert row["doctor_name"] in swap["summary"]

    # The department-wide view sees the same events.
    everything = client.get(f"/api/departments/{department_id}/history").json()
    assert {h["id"] for h in history} <= {h["id"] for h in everything}


def test_history_is_not_readable_from_outside_the_department(client):
    account = signup(client, email="private@hospital.org")
    department_id = account["departments"][0]["id"]
    roster(client, department_id, names=NAMES[:4])

    client.cookies.clear()
    signup(client, email="nosy@hospital.org")
    assert client.get(f"/api/departments/{department_id}/history").status_code == 404


# ───────────────────────── calendar feeds ─────────────────────────


def test_a_doctor_feed_follows_publication(client):
    account = signup(client, email="feed@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id)
    base = f"/api/departments/{department_id}/schedules"

    created = generate(client, department_id)
    schedule_id = created.json()["id"]
    nights = sorted(
        a["date"] for a in created.json()["assignments"] if a["doctor_id"] == ids[0]
    )
    assert nights

    feed = client.post(f"/api/departments/{department_id}/doctors/{ids[0]}/feed")
    assert feed.status_code == 201, feed.text
    url = feed.json()["url"]
    assert url.endswith(".ics")
    path = "/api" + url.split("/api", 1)[1]

    # A draft is a proposal: it must not turn up in anyone's calendar.
    client.cookies.clear()
    empty = client.get(path)
    assert empty.status_code == 200
    assert empty.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VEVENT" not in empty.text

    client.cookies.clear()
    client.post("/api/auth/login", json={
        "email": "feed@hospital.org", "password": "correct-horse-staple"})
    client.post(f"{base}/{schedule_id}/publish")

    client.cookies.clear()
    live = client.get(path).text
    assert live.count("BEGIN:VEVENT") == len(nights)
    for night in nights:
        assert f"DTSTART;VALUE=DATE:{night.replace('-', '')}" in live
    assert NAMES[0] in live

    # Only that doctor's nights, nobody else's.
    assert NAMES[1] not in live


def test_a_feed_can_be_rotated_and_revoked(client):
    account = signup(client, email="rotate@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id, names=NAMES[:4])

    first = client.post(
        f"/api/departments/{department_id}/doctors/{ids[0]}/feed").json()["url"]
    second = client.post(
        f"/api/departments/{department_id}/doctors/{ids[0]}/feed").json()["url"]
    assert first != second

    def fetch(url):
        client_cookies = dict(client.cookies)
        client.cookies.clear()
        res = client.get("/api" + url.split("/api", 1)[1])
        client.cookies.update(client_cookies)
        return res

    # Rotating retires the old link.
    assert fetch(first).status_code == 404
    assert fetch(second).status_code == 200

    assert client.delete(
        f"/api/departments/{department_id}/doctors/{ids[0]}/feed").status_code == 204
    assert fetch(second).status_code == 404


def test_feed_tokens_are_not_stored_in_clear(client):
    account = signup(client, email="feedhash@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id, names=NAMES[:4])
    url = client.post(
        f"/api/departments/{department_id}/doctors/{ids[0]}/feed").json()["url"]
    token = url.rsplit("/", 1)[1].removesuffix(".ics")

    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import CalendarFeed
    with SessionLocal() as db:
        stored = [f.token_hash for f in db.scalars(select(CalendarFeed)).all()]
    assert token not in stored
    assert all(len(h) == 64 for h in stored)


# ───────────────────────── importing a roster ─────────────────────────


def _upload(client, department_id, text, filename="roster.csv"):
    return client.post(
        f"/api/departments/{department_id}/doctors/import",
        files={"file": (filename, io.BytesIO(text.encode("utf-8")), "text/csv")},
    )


def test_a_roster_arrives_from_a_spreadsheet(client):
    account = signup(client, email="import@hospital.org")
    department_id = account["departments"][0]["id"]

    res = _upload(client, department_id, (
        "Name,Grade,Email,Active\n"
        "Amara Osei,consultant,,yes\n"
        "Bilal Haddad,registrar,,yes\n"
        "Chen Wei,registrar,,no\n"
    ))
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["created"], body["updated"], body["failed"]) == (3, 0, 0)

    doctors = {d["name"]: d for d in client.get(
        f"/api/departments/{department_id}/doctors").json()}
    assert set(doctors) == {"Amara Osei", "Bilal Haddad", "Chen Wei"}
    assert doctors["Amara Osei"]["grade"] == "consultant"
    assert doctors["Chen Wei"]["is_active"] is False

    # Re-importing updates rather than duplicating.
    again = _upload(client, department_id, "Name,Grade\nAmara Osei,professor\n").json()
    assert (again["created"], again["updated"]) == (0, 1)
    doctors = {d["name"]: d for d in client.get(
        f"/api/departments/{department_id}/doctors").json()}
    assert len(doctors) == 3
    assert doctors["Amara Osei"]["grade"] == "professor"


def test_import_reports_bad_rows_without_losing_good_ones(client):
    account = signup(client, email="badrows@hospital.org")
    department_id = account["departments"][0]["id"]

    body = _upload(client, department_id, (
        "name,grade\n"
        "Amara Osei,consultant\n"
        ",registrar\n"
        "Amara Osei,duplicate\n"
        "Bilal Haddad,registrar\n"
    )).json()

    assert body["created"] == 2
    assert body["failed"] == 1 and body["skipped"] == 1
    problem = next(r for r in body["rows"] if r["status"] == "error")
    assert problem["line"] == 3 and "No name" in problem["detail"]
    repeat = next(r for r in body["rows"] if r["status"] == "skipped")
    assert repeat["line"] == 4 and "Repeated" in repeat["detail"]

    names = {d["name"] for d in client.get(
        f"/api/departments/{department_id}/doctors").json()}
    assert names == {"Amara Osei", "Bilal Haddad"}


def test_import_links_accounts_and_accepts_a_headerless_file(client):
    account = signup(client, email="linkimport@hospital.org")
    department_id = account["departments"][0]["id"]
    _member(client, department_id, "gio@hospital.org")

    body = _upload(client, department_id, (
        "name,email\n"
        "Gio Ferrari,gio@hospital.org\n"
        "Hana Kim,stranger@hospital.org\n"
    )).json()

    doctors = {d["name"]: d for d in client.get(
        f"/api/departments/{department_id}/doctors").json()}
    assert doctors["Gio Ferrari"]["user_name"] == "Gio"
    assert doctors["Hana Kim"]["user_id"] is None
    unmatched = next(r for r in body["rows"] if r["name"] == "Hana Kim")
    assert "No member" in unmatched["detail"]

    # A bare list of names, no header row at all.
    plain = _upload(client, department_id, "Ines Duarte\nJonah Blake\n").json()
    assert plain["created"] == 2
    assert {r["line"] for r in plain["rows"]} == {1, 2}


def test_import_needs_a_coordinator(client):
    account = signup(client, email="importauth@hospital.org")
    department_id = account["departments"][0]["id"]
    member = _member(client, department_id, "reader@hospital.org")

    client.cookies.clear()
    client.cookies.update(member)
    assert _upload(client, department_id, "name\nSneaky\n").status_code == 403


# ───────────────────────────── email ─────────────────────────────


def test_a_reset_email_carries_a_working_link(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.mail.send",
        lambda to, subject, text, html=None: sent.append(
            {"to": to, "subject": subject, "text": text, "html": html}) or True,
    )

    signup(client, email="mailme@hospital.org", password="original-password-1")
    res = client.post("/api/auth/password/reset-request", json={"email": "mailme@hospital.org"})
    assert res.status_code == 200

    assert len(sent) == 1, "one reset, one email"
    message = sent[0]
    assert message["to"] == "mailme@hospital.org"
    assert "Night Shift" in message["subject"]
    assert "/reset/" in message["text"] and "/reset/" in message["html"]

    # The link in the email is the one that actually resets the password.
    token = message["text"].split("/reset/")[1].split()[0]
    assert client.post("/api/auth/password/reset", json={
        "token": token, "new_password": "brand-new-password-9"}).status_code == 204
    assert client.get(f"/reset/{token}").status_code == 200, "the link has a page to land on"


def test_no_email_goes_to_an_address_that_is_not_registered(client, monkeypatch):
    sent = []
    monkeypatch.setattr("app.mail.send", lambda *a, **k: sent.append(a) or True)
    client.post("/api/auth/password/reset-request",
                json={"email": "never-registered@hospital.org"})
    assert sent == []


def test_an_invitation_is_emailed_in_the_inviters_language(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.mail.send",
        lambda to, subject, text, html=None: sent.append(
            {"to": to, "subject": subject, "text": text}) or True,
    )

    account = signup(client, email="french@hospital.org")
    department_id = account["departments"][0]["id"]
    assert client.post("/api/auth/locale", json={"locale": "fr"}).status_code == 204

    res = client.post(f"/api/departments/{department_id}/invites",
                      json={"email": "nouveau@hospital.org"})
    assert res.status_code == 201

    assert len(sent) == 1
    assert sent[0]["to"] == "nouveau@hospital.org"
    assert "invite" in sent[0]["subject"]          # "vous invite à rejoindre"
    assert "Emergency" in sent[0]["subject"]
    assert "/join/" in sent[0]["text"]

    # And the link resolves to a page rather than a 404.
    token = sent[0]["text"].split("/join/")[1].split()[0]
    assert client.get(f"/join/{token}").status_code == 200


def test_the_signup_language_is_remembered(client):
    res = client.post(
        "/api/auth/signup",
        json={"email": "arabic@hospital.org", "password": "correct-horse-staple",
              "name": "Dr Arabic"},
        headers={"accept-language": "ar-TN,ar;q=0.9,en;q=0.5"},
    )
    assert res.status_code == 201
    assert res.json()["user"]["locale"] == "ar"


def test_a_doctor_can_mint_their_own_feed(client):
    """Asking a coordinator for a calendar link would defeat the point."""
    account = signup(client, email="ownfeed@hospital.org")
    department_id = account["departments"][0]["id"]
    ids = roster(client, department_id)
    base = f"/api/departments/{department_id}/schedules"

    start = dt.date.today() + dt.timedelta(days=3)
    created = client.post(base, json={
        "start_date": start.isoformat(),
        "end_date": (start + dt.timedelta(days=20)).isoformat(), "coverage": 2,
    })
    schedule_id = created.json()["id"]
    client.post(f"{base}/{schedule_id}/publish")
    nights = sorted(
        a["date"] for a in created.json()["assignments"] if a["doctor_id"] == ids[6])

    member = _member(client, department_id, "ferrari@hospital.org", doctor_id=ids[6])
    client.cookies.clear()
    client.cookies.update(member)

    feed = client.post("/api/me/feed")
    assert feed.status_code == 201, feed.text
    assert feed.json()["doctor_id"] == ids[6]
    path = "/api" + feed.json()["url"].split("/api", 1)[1]

    client.cookies.clear()
    body = client.get(path).text
    assert body.count("BEGIN:VEVENT") == len(nights)
    assert NAMES[6] in body

    # Revoking is the same person's call.
    client.cookies.update(member)
    assert client.delete("/api/me/feed").status_code == 204
    client.cookies.clear()
    assert client.get(path).status_code == 404


def test_someone_with_no_roster_entry_cannot_mint_a_feed(client):
    account = signup(client, email="nofeed@hospital.org")
    department_id = account["departments"][0]["id"]
    roster(client, department_id, names=NAMES[:4])
    member = _member(client, department_id, "outsider@hospital.org")

    client.cookies.clear()
    client.cookies.update(member)
    assert client.post("/api/me/feed").status_code == 403
