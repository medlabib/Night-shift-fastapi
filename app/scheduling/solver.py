"""Rota construction as constraint optimisation.

The previous engine sampled thousands of random rotas and kept the least-bad
one, which meant unfilled nights appeared silently and fairness was whatever
luck allowed. This states the problem once and lets CP-SAT prove an answer:

  hard   nightly coverage, per-grade coverage, booked leave, rest between
         shifts, pinned assignments
  soft   even points, even weekend load, even shift counts, learned
         preferences, and staying close to a rota being fine-tuned

Coverage is attempted strictly first. If that is genuinely impossible the model
is re-solved with coverage relaxed and *minimised* shortfall, so the caller gets
the best achievable rota plus an explanation of exactly which nights fell short
and why — never a silent gap.
"""

from __future__ import annotations

import datetime as dt
import time

from ortools.sat.python import cp_model

from app.scheduling.domain import SCALE, RotaRequest, RotaResult, Shortfall

# Objective weights. Points fairness dominates; the rest break ties.
W_POINTS_SPREAD = 100
W_WEEKEND_SPREAD = 40
W_SHIFT_SPREAD = 25
W_PREFERENCE = 8
# Crowding costs more than a preference but less than raw fairness: a rota
# should be even *and* readable, with fairness still winning outright.
W_SPREAD = 30
W_SHORTFALL = 10_000  # only used in the relaxed pass


class _Model:
    """One CP-SAT formulation of a rota request."""

    def __init__(self, req: RotaRequest, *, relax_coverage: bool):
        self.req = req
        self.relax = relax_coverage
        self.days = req.days
        self.model = cp_model.CpModel()
        self.x: dict[tuple[str, dt.date], cp_model.IntVar] = {}
        self.slack: dict[tuple[dt.date, str | None], cp_model.IntVar] = {}
        self._build()

    # ── variables ──────────────────────────────────────────────────
    def _build(self) -> None:
        req, model = self.req, self.model

        for doc in req.doctors:
            for day in self.days:
                self.x[doc.id, day] = model.NewBoolVar(f"x_{doc.id}_{day.isoformat()}")

        self._availability()
        self._coverage()
        self._rest()
        self._caps()
        self._objective()

    def _availability(self) -> None:
        """Leave, coordinator-cleared nights and pinned assignments."""
        req, model = self.req, self.model
        for doc in req.doctors:
            blocked = set(req.unavailable.get(doc.id, set())) | set(req.forbidden.get(doc.id, set()))
            pinned = set(req.locked.get(doc.id, set()))
            for day in self.days:
                var = self.x[doc.id, day]
                if day in pinned:
                    model.Add(var == 1)      # a pin beats a block: the coordinator decided
                elif day in blocked:
                    model.Add(var == 0)

    def _coverage(self) -> None:
        req, model = self.req, self.model

        def cover(day: dt.date, pool: list, needed: int, grade: str | None) -> None:
            if not pool:
                if needed and self.relax:
                    # Nobody of this grade exists; record the whole night as short.
                    s = model.NewIntVar(needed, needed, f"s_{day}_{grade}")
                    self.slack[day, grade] = s
                return
            total = sum(self.x[d.id, day] for d in pool)
            if self.relax:
                s = model.NewIntVar(0, needed, f"s_{day}_{grade}")
                self.slack[day, grade] = s
                model.Add(total + s == needed)
            else:
                model.Add(total == needed)

        for day in self.days:
            if req.graded and req.grades:
                for grade in req.grades:
                    cover(day, req.doctors_in(grade), req.required_for(day, grade), grade)
            else:
                cover(day, list(req.doctors), req.required_on(day), None)

    def _rest(self) -> None:
        """Rest between shifts, and a ceiling on how dense a stretch may get.

        The minimum gap on its own is not enough: obeying "one night off" to
        the letter still allows working every other night for a fortnight. The
        rolling cap is what actually rules that out.
        """
        req, model = self.req, self.model

        window = max(0, int(req.min_rest_nights)) + 1
        if window >= 2:
            for doc in req.doctors:
                for i in range(len(self.days)):
                    chunk = self.days[i : i + window]
                    if len(chunk) < 2:
                        break
                    model.AddAtMostOne(self.x[doc.id, day] for day in chunk)

        span = max(0, int(req.spread_window_nights))
        cap = max(1, int(req.max_shifts_per_window))
        if span >= 2:
            for doc in req.doctors:
                for i in range(len(self.days)):
                    chunk = self.days[i : i + span]
                    if len(chunk) <= cap:
                        break
                    model.Add(sum(self.x[doc.id, day] for day in chunk) <= cap)

    def _spread_terms(self) -> list:
        """Reward rotas that space a doctor's nights out evenly.

        Without this the solver has no reason to prefer 2/9/16/23 over
        2/4/6/8: the totals are identical, so it picks arbitrarily and the
        result reads as a punishing run. Each shift beyond the first inside a
        rolling window costs something, which pushes them apart.
        """
        req, model = self.req, self.model
        span = max(0, int(req.spread_window_nights))
        if span < 2:
            return []

        terms = []
        for doc in req.doctors:
            for i in range(len(self.days) - span + 1):
                chunk = self.days[i : i + span]
                excess = model.NewIntVar(0, len(chunk), f"crowd_{doc.id}_{i}")
                model.Add(excess >= sum(self.x[doc.id, day] for day in chunk) - 1)
                terms.append(W_SPREAD * excess)
        return terms

    def _caps(self) -> None:
        req, model = self.req, self.model
        for doc in req.doctors:
            cap = req.max_shifts.get(doc.id)
            if cap is not None:
                model.Add(sum(self.x[doc.id, day] for day in self.days) <= int(cap))

    # ── objective ──────────────────────────────────────────────────
    def _objective(self) -> None:
        req, model = self.req, self.model
        terms = []

        points = {d.id: [] for d in req.doctors}
        weekend = {d.id: [] for d in req.doctors}
        shifts = {d.id: [] for d in req.doctors}

        for doc in req.doctors:
            for day in self.days:
                var = self.x[doc.id, day]
                points[doc.id].append(int(round(req.points_for(day) * SCALE)) * var)
                shifts[doc.id].append(var)
                if day.weekday() >= 5 or day in req.holidays:
                    weekend[doc.id].append(var)

        # Fairness is measured within a grade: comparing a consultant's load to a
        # resident's is meaningless when each tier is staffed separately.
        groups = (
            [[d for d in req.doctors if d.grade == g] for g in req.grades]
            if req.graded and req.grades
            else [list(req.doctors)]
        )

        for gi, group in enumerate(groups):
            if len(group) < 2:
                continue

            # Carried-forward balance shifts each doctor's starting position,
            # so what gets evened out is the running total rather than this
            # period in isolation. Measured per grade, like everything else.
            carried_pts = self._carried(group, req.prior_points, req.carry_cap_points, SCALE)
            carried_wke = self._carried(group, req.prior_weekends, req.carry_cap_weekends, 1)
            head_pts = max(carried_pts.values(), default=0)
            head_wke = max(carried_wke.values(), default=0)

            terms.append(W_POINTS_SPREAD * self._spread(
                [sum(points[d.id]) + carried_pts[d.id] for d in group],
                f"pts{gi}", self._max_points() + head_pts))
            terms.append(W_WEEKEND_SPREAD * self._spread(
                [sum(weekend[d.id]) + carried_wke[d.id] for d in group],
                f"wke{gi}", len(self.days) + head_wke))
            # Shift count is left on this period alone: it tracks points
            # closely, and carrying both would double-weight the same signal.
            terms.append(W_SHIFT_SPREAD * self._spread(
                [sum(shifts[d.id]) for d in group], f"shf{gi}", len(self.days)))

        terms += self._spread_terms()
        terms += self._preference_terms()
        terms += self._change_terms()

        if self.relax:
            for var in self.slack.values():
                terms.append(W_SHORTFALL * var)

        model.Minimize(sum(terms))

    def _max_points(self) -> int:
        return int(round(max(self.req.points_for(d) for d in self.days) * SCALE)) * len(self.days)

    def _carried(self, group: list, history: dict[str, float], cap: float, scale: int) -> dict:
        """Each doctor's head start, as a scaled integer offset.

        Rebased so the least-worked doctor in the grade starts at zero — only
        the differences matter — then capped, so a long absence cannot hand
        one person an entire month to catch up in.
        """
        if not history:
            return {d.id: 0 for d in group}

        # Someone who joined mid-window has no comparable record; the group's
        # average keeps them neutral instead of bottom of the pile.
        known = [float(history.get(d.id, 0.0)) for d in group if d.id not in self.req.prior_partial]
        neutral = sum(known) / len(known) if known else 0.0
        raw = {
            d.id: neutral if d.id in self.req.prior_partial else float(history.get(d.id, 0.0))
            for d in group
        }
        lowest = min(raw.values(), default=0.0)
        return {k: int(round(min(v - lowest, cap) * scale)) for k, v in raw.items()}

    def _spread(self, expressions: list, tag: str, upper: int) -> cp_model.IntVar:
        """max(expressions) - min(expressions), as a variable to minimise."""
        model = self.model
        hi = model.NewIntVar(0, max(1, upper), f"hi_{tag}")
        lo = model.NewIntVar(0, max(1, upper), f"lo_{tag}")
        for expr in expressions:
            model.Add(hi >= expr)
            model.Add(lo <= expr)
        gap = model.NewIntVar(0, max(1, upper), f"gap_{tag}")
        model.Add(gap == hi - lo)
        return gap

    def _preference_terms(self) -> list:
        """Learned soft preferences. Positive weight prefers, negative avoids."""
        req, model = self.req, self.model
        terms = []
        by_doctor = {d.id: d for d in req.doctors}

        for (subject, feature), weight in req.preferences.items():
            if not weight:
                continue
            scaled = int(round(-W_PREFERENCE * weight))  # minimising, so flip the sign
            targets = [by_doctor[subject]] if subject in by_doctor else list(req.doctors)

            if feature.startswith("dow:"):
                dow = int(feature.split(":", 1)[1])
                for doc in targets:
                    for day in self.days:
                        if day.weekday() == dow:
                            terms.append(scaled * self.x[doc.id, day])

            elif feature.startswith("date:"):
                day = dt.date.fromisoformat(feature.split(":", 1)[1])
                if day in set(self.days):
                    for doc in targets:
                        terms.append(scaled * self.x[doc.id, day])

            elif feature.startswith("partner:"):
                other = feature.split(":", 1)[1]
                if subject in by_doctor and other in by_doctor and subject != other:
                    for day in self.days:
                        both = model.NewBoolVar(f"pair_{subject}_{other}_{day}")
                        a, b = self.x[subject, day], self.x[other, day]
                        model.AddBoolAnd([a, b]).OnlyEnforceIf(both)
                        model.AddBoolOr([a.Not(), b.Not()]).OnlyEnforceIf(both.Not())
                        terms.append(scaled * both)

        return terms

    def _change_terms(self) -> list:
        """Keep a fine-tuned rota close to the one the coordinator already has."""
        req = self.req
        if not req.anchor or req.change_penalty <= 0:
            return []
        terms = []
        for doc in req.doctors:
            previous = req.anchor.get(doc.id, set())
            for day in self.days:
                var = self.x[doc.id, day]
                # Cost a flip in either direction.
                terms.append(req.change_penalty * (1 - var) if day in previous
                             else req.change_penalty * var)
        return terms


def solve(req: RotaRequest) -> RotaResult:
    """Build the fairest rota that satisfies every hard constraint.

    Tries strict coverage first, then falls back to minimised shortfall so an
    over-subscribed request still returns a usable rota with an explanation.
    """
    started = time.perf_counter()

    if not req.doctors or not req.days:
        return RotaResult(
            assignments={}, status="INFEASIBLE", solve_seconds=0.0,
            diagnostics=["Add at least one doctor and a valid date range."],
        )

    strict = _run(_Model(req, relax_coverage=False), req)
    if strict is not None:
        assignments, status, objective = strict
        result = RotaResult(
            assignments=assignments,
            status=status,
            solve_seconds=time.perf_counter() - started,
            objective=objective,
        )
        result.metrics = summarise(req, result)
        return result

    relaxed = _run(_Model(req, relax_coverage=True), req)
    if relaxed is None:
        return RotaResult(
            assignments={}, status="INFEASIBLE",
            solve_seconds=time.perf_counter() - started,
            diagnostics=diagnose(req),
        )

    assignments, _, objective = relaxed
    result = RotaResult(
        assignments=assignments,
        status="RELAXED",
        solve_seconds=time.perf_counter() - started,
        objective=objective,
        shortfalls=_shortfalls(req, assignments),
        diagnostics=diagnose(req),
    )
    result.metrics = summarise(req, result)
    return result


def _run(built: _Model, req: RotaRequest):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(req.time_limit)
    solver.parameters.num_search_workers = int(req.workers)
    status = solver.Solve(built.model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    assignments = {
        doc.id: [day for day in built.days if solver.Value(built.x[doc.id, day])]
        for doc in req.doctors
    }
    name = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
    return assignments, name, solver.ObjectiveValue()


def _shortfalls(req: RotaRequest, assignments: dict[str, list[dt.date]]) -> list[Shortfall]:
    grade_of = {d.id: d.grade for d in req.doctors}
    worked: dict[dt.date, list[str]] = {}
    for doctor_id, days in assignments.items():
        for day in days:
            worked.setdefault(day, []).append(doctor_id)

    out: list[Shortfall] = []
    for day in req.days:
        on_call = worked.get(day, [])
        if req.graded and req.grades:
            for grade in req.grades:
                need = req.required_for(day, grade)
                got = sum(1 for doc in on_call if grade_of.get(doc) == grade)
                if got < need:
                    out.append(Shortfall(day, grade, need, got, _why(req, day, grade)))
        else:
            need = req.required_on(day)
            if len(on_call) < need:
                out.append(Shortfall(day, None, need, len(on_call), _why(req, day, None)))
    return out


def _why(req: RotaRequest, day: dt.date, grade: str | None) -> str:
    pool = req.doctors_in(grade) if grade else req.doctors
    need = req.required_for(day, grade) if grade else req.required_on(day)
    free = [d for d in pool if req.is_available(d.id, day)]
    label = f"{grade} " if grade else ""

    if len(pool) < need:
        return f"only {len(pool)} {label}doctors exist, {need} needed each night"
    if len(free) < need:
        away = len(pool) - len(free)
        return f"{away} of {len(pool)} {label}doctors are on leave, leaving {len(free)} for {need} slots"
    return (
        f"enough {label}doctors are free, but {req.min_rest_nights} "
        f"night(s) of rest between shifts leaves too few eligible"
    )


def structural_blockers(req: RotaRequest) -> list[str]:
    """Reasons a request can never be met, however the solver arranges it.

    Cheap arithmetic, checked before solving. A rota that merely runs tight
    still gets built and reports its gaps; one that is arithmetically
    impossible is refused outright rather than returning a third of a rota.
    """
    blockers: list[str] = []
    groups = (
        [(g, req.doctors_in(g)) for g in req.grades]
        if req.graded and req.grades else [(None, list(req.doctors))]
    )

    for grade, pool in groups:
        label = f"{grade}: " if grade else ""
        peak = max(
            (req.required_for(d, grade) if grade else req.required_on(d)) for d in req.days
        )
        if not pool:
            if peak:
                blockers.append(f"{label}no doctors are assigned to this grade.")
            continue
        if peak > len(pool):
            blockers.append(
                f"{label}{peak} doctors are requested per night but only {len(pool)} exist."
            )
            continue

        # Two limits bound how often one doctor can work: the rest gap, and
        # the rolling density cap. Whichever bites harder sets the ceiling.
        rest_rate = 1 / max(1, req.min_rest_nights + 1)
        density_rate = (
            req.max_shifts_per_window / req.spread_window_nights
            if req.spread_window_nights >= 2 else 1.0
        )
        binding = min(rest_rate, density_rate)
        capacity = len(pool) * len(req.days) * binding
        demand = sum(
            (req.required_for(d, grade) if grade else req.required_on(d)) for d in req.days
        )
        if demand > capacity:
            if density_rate < rest_rate:
                cause = (
                    f"at most {req.max_shifts_per_window} shift(s) in any "
                    f"{req.spread_window_nights} nights"
                )
                remedy = "raise the shifts-per-window cap"
            else:
                cause = f"{req.min_rest_nights} night(s) of rest between shifts"
                remedy = "shorten the rest requirement"
            blockers.append(
                f"{label}{demand} shifts are needed but {len(pool)} doctors working "
                f"{cause} can cover at most {capacity:.0f}. Add doctors, {remedy}, "
                f"or lower coverage."
            )

    return blockers


def diagnose(req: RotaRequest) -> list[str]:
    """Plain-language reasons a request cannot be met in full."""
    notes: list[str] = []
    groups = (
        [(g, req.doctors_in(g)) for g in req.grades]
        if req.graded and req.grades else [(None, list(req.doctors))]
    )

    for grade, pool in groups:
        label = f"{grade}: " if grade else ""
        if not pool:
            notes.append(f"{label}no doctors are assigned to this grade.")
            continue

        peak = max((req.required_for(d, grade) if grade else req.required_on(d)) for d in req.days)
        if peak > len(pool):
            notes.append(
                f"{label}{peak} doctors are requested per night but only {len(pool)} exist."
            )
            continue

        # With R nights of rest, a doctor can work at most every (R+1)th night,
        # so the roster's ceiling over the period is len(pool) * nights / (R+1).
        window = max(1, req.min_rest_nights + 1)
        capacity = len(pool) * len(req.days) / window
        demand = sum(
            (req.required_for(d, grade) if grade else req.required_on(d)) for d in req.days
        )
        if demand > capacity:
            notes.append(
                f"{label}{demand} shifts are needed but {len(pool)} doctors resting "
                f"{req.min_rest_nights} night(s) between shifts can cover at most "
                f"{capacity:.0f}. Add doctors, shorten the rest requirement, or lower coverage."
            )

        booked = sum(
            1 for d in req.days for doc in pool if not req.is_available(doc.id, d)
        )
        if booked and demand > capacity - booked / window:
            notes.append(f"{label}booked leave removes {booked} doctor-nights from the pool.")

    if not notes:
        notes.append(
            "The combination of coverage, leave and rest requirements has no solution. "
            "Relax one of them — usually the nightly headcount."
        )
    return notes


def summarise(req: RotaRequest, result: RotaResult) -> dict:
    """Fairness metrics computed from the solved rota."""
    per_doctor = {}
    for doc in req.doctors:
        days = result.assignments.get(doc.id, [])
        earned = round(sum(req.points_for(d) for d in days), 2)
        prior = round(float(req.prior_points.get(doc.id, 0.0)), 2)
        per_doctor[doc.id] = {
            "name": doc.name,
            "grade": doc.grade,
            "shifts": len(days),
            "points": earned,
            "weekend_shifts": sum(1 for d in days if d.weekday() >= 5),
            "holiday_shifts": sum(1 for d in days if d in req.holidays),
            "dates": [d.isoformat() for d in days],
            # What they brought in, and where that leaves them — so a lighter
            # month reads as "they did more last month", not as a mistake.
            "prior_points": prior,
            "cumulative_points": round(prior + earned, 2),
            "new_this_period": doc.id in req.prior_partial,
        }

    points = [v["points"] for v in per_doctor.values()]
    cumulative = [v["cumulative_points"] for v in per_doctor.values()]
    shifts = [v["shifts"] for v in per_doctor.values()]
    weekends = [v["weekend_shifts"] for v in per_doctor.values()]
    mean = sum(points) / len(points) if points else 0.0
    sd = (sum((p - mean) ** 2 for p in points) / len(points)) ** 0.5 if points else 0.0

    assigned = sum(len(v) for v in result.assignments.values())
    required = req.seats()

    return {
        "per_doctor": per_doctor,
        "carry_forward": req.carries_forward,
        "cumulative_spread": (
            round(max(cumulative) - min(cumulative), 2) if cumulative and req.carries_forward else 0
        ),
        "points_spread": round(max(points) - min(points), 2) if points else 0,
        "shift_spread": max(shifts) - min(shifts) if shifts else 0,
        "weekend_spread": max(weekends) - min(weekends) if weekends else 0,
        "mean_points": round(mean, 2),
        "balance": round(max(0.0, min(100.0, 100 * (1 - sd / mean))), 1) if mean else 0.0,
        "assigned": assigned,
        "required": required,
        "coverage": round(100 * assigned / required, 1) if required else 100.0,
    }
