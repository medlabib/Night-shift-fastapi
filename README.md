# Night Shift

Fair night-shift rotas for hospital departments — a FastAPI scheduling engine with a
built-in web frontend, **Rota Studio**.

The engine samples thousands of candidate rotas and keeps the one that spreads the
workload most evenly, weighting unsociable nights more heavily. The frontend lets a rota
coordinator build the roster, predict whether a rota is even possible before asking for
one, and audit whatever comes back.

## Running it

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Then open <http://127.0.0.1:8000/>. The frontend is plain HTML, CSS and JavaScript served
by the same app — no build step, no package manager, no external requests at runtime.

| Route | Purpose |
| --- | --- |
| `GET /` | Rota Studio (the frontend) |
| `GET /health` | Readiness probe |
| `POST /schedule` | The scheduling engine |
| `GET /docs` | Interactive OpenAPI docs |

To host the frontend somewhere other than the API, serve `static/` as a static site and
set the API base URL in the studio's settings dialog (the gear icon).

## Rota Studio

**Build the roster.** Add doctors one at a time or paste a comma-separated list. Mark
seniority grades, click nights on a calendar to flag public holidays, and click nights per
doctor to book leave.

**Pre-flight before you generate.** The studio models the engine's own rules and tells you
what will happen before a request is sent — nights that cannot be covered, grades with too
few doctors, projected points and shifts per doctor, and an estimate of how long the search
will take (calibrated against your own past runs). Impossible setups block the button
rather than returning a server error.

**Audit what comes back.** Every rota is re-checked against your constraints: leave
conflicts, understaffed or unfilled nights, back-to-back shifts, doctors who were never
rostered, grade coverage gaps, and how evenly points and weekends landed. The Insights tab
reports what passed as well as what failed.

**Take it away.** Export the rota as CSV, per-doctor workload as CSV, or an `.ics` calendar
you can import into Outlook, Google or Apple Calendar. There is a print stylesheet for the
ward noticeboard. Generated rotas are kept in a local history so you can compare runs and
restore an earlier one.

Roster and rules are saved in the browser's local storage, so a reload does not lose your
work. Dark and light themes both ship; `Ctrl`/`Cmd` + `Enter` generates.

## How the engine scores a rota

Each night carries a point weight:

| Night | Weight |
| --- | --- |
| Weekday | 1.0 |
| Saturday | 1.5 |
| Sunday | 2.0 |
| Public holiday | 2.0 |

`find` random rotas are generated. Those with the flattest points split survive, then ties
are broken on shift count, weekend count, and how evenly spaced each doctor's nights are.
The returned `score` is the sum of those differences — **lower is fairer**.

A rest rule runs throughout: whoever filled the most recent `roster − ceil(roster / 3)`
shift slots is benched, which leaves roughly a third of the roster selectable on any given
night. This is the single most common reason a rota comes back with gaps — a night the
engine cannot fill without breaking the rest rule is left unfilled rather than failing.
Rota Studio models this rule directly, which is how it predicts shortfalls in advance.

## POST /schedule

### Request

| Field | Type | Notes |
| --- | --- | --- |
| `doctor_names` | string | Comma-separated, e.g. `"Dr. Aya,Dr. Bilal"` |
| `start_date` | string | `YYYY-MM-DD` |
| `end_date` | string | `YYYY-MM-DD` |
| `same_num_doctors` | string | `"Y"` for one headcount all period, `"N"` for per-night |
| `num_doctors` | int / null | Doctors per night when `same_num_doctors` is `"Y"` |
| `num_doctors_per_night` | object / null | `{"2026-09-01": 2, …}` when `"N"` — **must be in date order** |
| `holiday_days` | string | Comma-separated dates, or `""` |
| `find` | int | Candidate rotas to sample. More is fairer and slower |
| `department_is_graded` | string | `"Y"` or `"N"` |
| `doctors_grades` | object / null | `{"Dr. Aya": "Senior", …}` when graded |
| `grades` | array / null | `["Senior", "Junior"]` when graded |
| `shift_requirements` | object / null | Per-date grade requirements. **Send `{}`, not `null`, when graded** |
| `doctor_not_present` | object | `{"Dr. Aya": "2026-09-03,2026-09-04"}` |

All fields must be present in the request body; use `null` for the ones that do not apply.

Two things to know when calling the API directly:

- **In a graded department the nightly count is per grade.** `num_doctors: 2` with three
  grades puts six doctors on call each night.
- **`shift_requirements` must be an object when `department_is_graded` is `"Y"`.** Passing
  `null` makes the engine assign nobody at all.

### Response

`schedule` has two shapes depending on the department:

```jsonc
// department_is_graded: "N"
{
  "schedule": { "2026-09-01": [["Dr. Aya", 1], ["Dr. Bilal", 1]] },
  "points": { "Dr. Aya": 7.5 },
  "num_shifts": { "Dr. Aya": 6 },
  "num_weekend_shifts": { "Dr. Aya": 2 },
  "schedule_name": "Schedule 4773690d-…",
  "score": 3.39
}

// department_is_graded: "Y" — dates are timestamps, stats nest under each grade
{
  "schedule": { "2026-09-01T00:00:00": { "Dr. Aya": 1, "Dr. Dara": 1 } },
  "points": { "Senior": { "Dr. Aya": 7.5 } },
  "num_shifts": { "Senior": { "Dr. Aya": 6 } },
  "num_weekend_shifts": { "Senior": { "Dr. Aya": 2 } },
  "schedule_name": "Schedule 3dbaf242-…",
  "score": 1.0
}
```

Doctors with no shifts are omitted from the stats objects rather than reported as zero.

A request the engine cannot satisfy returns **422** with a `detail` string explaining the
likely cause, rather than a bare 500.

### Example

```python
import requests

payload = {
    "doctor_names": "Dr. Aya,Dr. Bilal,Dr. Chen,Dr. Dara,Dr. Elias,Dr. Farah",
    "start_date": "2026-09-01",
    "end_date": "2026-09-30",
    "same_num_doctors": "Y",
    "num_doctors": 2,
    "num_doctors_per_night": None,
    "holiday_days": "2026-09-15",
    "find": 400,
    "department_is_graded": "N",
    "doctors_grades": None,
    "shift_requirements": None,
    "grades": None,
    "doctor_not_present": {"Dr. Aya": "2026-09-03,2026-09-04"},
}

print(requests.post("http://127.0.0.1:8000/schedule", json=payload).json())
```

## Layout

```
main.py            FastAPI app: the scheduling engine, /health, and the static mount
static/index.html  Rota Studio markup
static/styles.css  Design system — midnight and light themes, print stylesheet
static/app.js      State, pre-flight model, API client, rota audit, exports
```
