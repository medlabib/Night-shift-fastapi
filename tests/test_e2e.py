"""End-to-end coverage: auth, authorisation, solving, editing, PDF and sharing."""

from __future__ import annotations

import datetime as dt
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://nightshift:nightshift@127.0.0.1:5433/nightshift_test"
)
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

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

    # A coordinator moves the same doctor off Fridays, rota after rota —
    # which is how a real preference actually shows up in the record.
    target = ids[0]
    fridays = {d.isoformat() for d in _days() if d.weekday() == 4}
    moved = 0
    for _ in range(4):
        schedule_id = generate(client, department_id).json()["id"]
        state = client.get(f"{base}/{schedule_id}").json()
        for row in state["assignments"]:
            if row["date"] not in fridays or row["doctor_id"] != target:
                continue
            on_call = {a["doctor_id"] for a in state["assignments"] if a["date"] == row["date"]}
            stand_in = next((i for i in ids if i not in on_call), None)
            if stand_in and client.post(f"{base}/{schedule_id}/swap", json={
                "date": row["date"], "doctor_out": target, "doctor_in": stand_in,
            }).status_code == 200:
                moved += 1
    assert moved >= 2, f"expected repeated Friday edits, got {moved}"

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
