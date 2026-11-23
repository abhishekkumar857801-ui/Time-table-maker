"""
Integer Programming model for student timetable optimisation (built with PuLP).

Decision variables (all binary)
-------------------------------
x[c,d,p,r] = 1  if lecture course c is held on day d, period p, in room r
y[c,d,p,r] = 1  if a 2-period LAB block of course c STARTS on day d, period p, in room r
                (so it occupies periods p and p+1)
h[g,d,p]   = 1  if student group g has an idle "hole" at (d,p)  (soft constraint)
L[g]       >= 0 integer: maximum number of periods group g has on any day (for balancing)

See README.md for the full mathematical formulation.
"""
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pulp

from .data_loader import LAB_BLOCK, Course, ProblemData


@dataclass
class Session:
    """One scheduled period in the final timetable."""
    course: Course
    day: int
    period: int
    room: str
    is_lab: bool


@dataclass
class SolveResult:
    status: str
    objective: Optional[float]
    solve_seconds: float
    num_variables: int
    num_constraints: int
    sessions: List[Session]
    penalty_breakdown: Dict[str, float]


class TimetableModel:
    def __init__(self, data: ProblemData):
        self.data = data
        self.prob = pulp.LpProblem("Student_Timetable", pulp.LpMinimize)
        self.x: Dict[Tuple, pulp.LpVariable] = {}
        self.y: Dict[Tuple, pulp.LpVariable] = {}
        self.h: Dict[Tuple, pulp.LpVariable] = {}
        self.L: Dict[str, pulp.LpVariable] = {}
        self.penalty_terms: Dict[str, pulp.LpAffineExpression] = {}
        self._build()

    # ------------------------------------------------------------------ helpers
    def _valid_rooms(self, c: Course) -> List[str]:
        """Rooms of the right type and with enough seats (capacity constraint handled by pre-filtering)."""
        size = self.data.groups[c.group].size
        return [r.id for r in self.data.rooms.values() if r.type == c.type and r.capacity >= size]

    def _lab_start_periods(self) -> List[int]:
        """A lab block may start at p only if p+1 exists and the block does not straddle lunch."""
        P, lunch = self.data.P, self.data.lunch_after_period
        starts = []
        for p in range(P - LAB_BLOCK + 1):
            spans_lunch = lunch and (p + 1) <= lunch < (p + LAB_BLOCK)  # 1-based check
            if not spans_lunch:
                starts.append(p)
        return starts

    def occupies(self, c: Course, d: int, p: int, r: Optional[str] = None) -> pulp.LpAffineExpression:
        """Linear expression = 1 if course c occupies slot (d,p) (optionally in room r)."""
        rooms = [r] if r else self._valid_rooms(c)
        if c.type == "lecture":
            return pulp.lpSum(self.x[c.id, d, p, rr] for rr in rooms if (c.id, d, p, rr) in self.x)
        terms = []
        for k in range(LAB_BLOCK):  # a lab started at p-k still occupies p
            for rr in rooms:
                key = (c.id, d, p - k, rr)
                if key in self.y:
                    terms.append(self.y[key])
        return pulp.lpSum(terms)

    # ------------------------------------------------------------------ build
    def _build(self):
        data = self.data
        D, P = data.D, data.P
        S = data.settings
        W = S["weights"]
        lab_starts = self._lab_start_periods()

        # ---------- decision variables
        for c in data.courses:
            rooms = self._valid_rooms(c)
            if not rooms:
                raise ValueError(f"No {c.type} room can seat group {c.group} for {c.subject}")
            for d in range(D):
                for r in rooms:
                    if c.type == "lecture":
                        for p in range(P):
                            self.x[c.id, d, p, r] = pulp.LpVariable(f"x_{c.id}_{d}_{p}_{r}", cat="Binary")
                    else:
                        for p in lab_starts:
                            self.y[c.id, d, p, r] = pulp.LpVariable(f"y_{c.id}_{d}_{p}_{r}", cat="Binary")

        by_group = defaultdict(list)
        by_teacher = defaultdict(list)
        for c in data.courses:
            by_group[c.group].append(c)
            by_teacher[c.teacher].append(c)

        prob = self.prob

        # ---------- HARD CONSTRAINTS
        for c in data.courses:
            # (1) every course gets exactly its required weekly hours
            if c.type == "lecture":
                prob += pulp.lpSum(v for k, v in self.x.items() if k[0] == c.id) == c.hours, f"hours_{c.id}"
            else:
                prob += pulp.lpSum(v for k, v in self.y.items() if k[0] == c.id) == c.hours // LAB_BLOCK, f"hours_{c.id}"

            # (2) spread a subject across the week: limit sessions of same course per day
            for d in range(D):
                if c.type == "lecture":
                    prob += (pulp.lpSum(self.occupies(c, d, p) for p in range(P))
                             <= S["max_same_subject_per_day"]), f"spread_{c.id}_{d}"
                else:
                    prob += (pulp.lpSum(v for k, v in self.y.items() if k[0] == c.id and k[1] == d)
                             <= 1), f"spread_{c.id}_{d}"

        for d in range(D):
            for p in range(P):
                # (3) a student group attends at most one class at a time
                for g, cs in by_group.items():
                    prob += pulp.lpSum(self.occupies(c, d, p) for c in cs) <= 1, f"group_{g}_{d}_{p}"

                # (4) a teacher teaches at most one class at a time
                # (5) a teacher is never scheduled when unavailable
                for t, cs in by_teacher.items():
                    rhs = 0 if (d, p) in data.teachers[t].unavailable else 1
                    prob += pulp.lpSum(self.occupies(c, d, p) for c in cs) <= rhs, f"teacher_{t}_{d}_{p}"

                # (6) a room hosts at most one class at a time
                for r in data.rooms:
                    prob += (pulp.lpSum(self.occupies(c, d, p, r) for c in data.courses
                                        if r in self._valid_rooms(c)) <= 1), f"room_{r}_{d}_{p}"

        for d in range(D):
            # (7) daily load limits for groups and teachers
            for g, cs in by_group.items():
                prob += (pulp.lpSum(self.occupies(c, d, p) for c in cs for p in range(P))
                         <= S["max_periods_per_day_group"]), f"groupday_{g}_{d}"
            for t, cs in by_teacher.items():
                prob += (pulp.lpSum(self.occupies(c, d, p) for c in cs for p in range(P))
                         <= data.teachers[t].max_per_day), f"teacherday_{t}_{d}"

        # ---------- SOFT CONSTRAINTS (objective penalties)
        # (a) student idle gaps (any length) inside a half-day session (morning / afternoon).
        #     a[p] = 1 if the group had some class at or before p   (a[p] >= occ[p], a[p] >= a[p-1])
        #     b[p] = 1 if the group has some class at or after p    (b[p] >= occ[p], b[p] >= b[p+1])
        #     free period p is a gap if a[p-1] = b[p+1] = 1:  h[p] >= a[p-1] + b[p+1] - occ[p] - 1
        #     a, b, h are only bounded from below and are penalised, so the solver drives them to their true value.
        lunch = data.lunch_after_period
        halves = [list(range(0, lunch)), list(range(lunch, P))] if lunch else [list(range(P))]
        for g, cs in by_group.items():
            for d in range(D):
                occ = {p: pulp.lpSum(self.occupies(c, d, p) for c in cs) for p in range(P)}
                for half in halves:
                    a, b = {}, {}
                    for p in half:
                        a[p] = pulp.LpVariable(f"a_{g}_{d}_{p}", 0, 1)
                        b[p] = pulp.LpVariable(f"b_{g}_{d}_{p}", 0, 1)
                        prob += a[p] >= occ[p], f"a1_{g}_{d}_{p}"
                        prob += b[p] >= occ[p], f"b1_{g}_{d}_{p}"
                    for p_prev, p in zip(half, half[1:]):
                        prob += a[p] >= a[p_prev], f"a2_{g}_{d}_{p}"
                        prob += b[p_prev] >= b[p], f"b2_{g}_{d}_{p}"
                    for p in half[1:-1]:
                        self.h[g, d, p] = pulp.LpVariable(f"h_{g}_{d}_{p}", cat="Binary")
                        prob += self.h[g, d, p] >= a[p - 1] + b[p + 1] - occ[p] - 1, f"gap_{g}_{d}_{p}"

        # (b) balance: L[g] >= load of group g on every day  ->  minimise the heaviest day
        for g, cs in by_group.items():
            self.L[g] = pulp.LpVariable(f"L_{g}", lowBound=0, cat="Integer")
            for d in range(D):
                prob += self.L[g] >= pulp.lpSum(self.occupies(c, d, p) for c in cs for p in range(P)), f"bal_{g}_{d}"

        self.penalty_terms = {
            "student_gap": pulp.lpSum(self.h.values()),
            # (c) avoid the last period of the day
            "last_period": pulp.lpSum(self.occupies(c, d, P - 1) for c in data.courses for d in range(D)),
            # (d) respect teacher "prefer not" slots
            "teacher_avoid": pulp.lpSum(self.occupies(c, d, p) for c in data.courses
                                        for (d, p) in data.teachers[c.teacher].avoid),
            "daily_balance": pulp.lpSum(self.L.values()),
        }
        prob += pulp.lpSum(W[k] * expr for k, expr in self.penalty_terms.items()), "total_penalty"

    # ------------------------------------------------------------------ solve
    def solve(self, time_limit: Optional[int] = None, msg: bool = False) -> SolveResult:
        limit = time_limit or self.data.settings["time_limit_seconds"]
        solver = pulp.PULP_CBC_CMD(msg=msg, timeLimit=limit)
        t0 = time.time()
        self.prob.solve(solver)
        elapsed = time.time() - t0

        status = pulp.LpStatus[self.prob.status]
        sessions: List[Session] = []
        breakdown: Dict[str, float] = {}
        objective = None
        has_solution = self.prob.sol_status in (pulp.LpSolutionOptimal, pulp.LpSolutionIntegerFeasible)
        if has_solution:
            # CBC reports "Optimal" status even when stopped by time limit with a feasible solution;
            # sol_status distinguishes proven-optimal from just-feasible.
            if self.prob.sol_status == pulp.LpSolutionIntegerFeasible:
                status = "Feasible (time limit reached)"
            objective = pulp.value(self.prob.objective)
            courses = {c.id: c for c in self.data.courses}
            for (cid, d, p, r), v in self.x.items():
                if v.value() > 0.5:
                    sessions.append(Session(courses[cid], d, p, r, False))
            for (cid, d, p, r), v in self.y.items():
                if v.value() > 0.5:
                    for k in range(LAB_BLOCK):
                        sessions.append(Session(courses[cid], d, p + k, r, True))
            breakdown = {k: float(pulp.value(e) or 0) for k, e in self.penalty_terms.items()}

        return SolveResult(
            status=status,
            objective=objective,
            solve_seconds=elapsed,
            num_variables=len(self.prob.variables()),
            num_constraints=len(self.prob.constraints),
            sessions=sessions,
            penalty_breakdown=breakdown,
        )


def verify(data: ProblemData, sessions: List[Session]) -> List[str]:
    """Independent check of every hard constraint on the produced timetable. Returns list of violations."""
    errors = []
    group_slot, teacher_slot, room_slot = defaultdict(list), defaultdict(list), defaultdict(list)
    hours = defaultdict(int)
    for s in sessions:
        c = s.course
        hours[c.id] += 1
        group_slot[c.group, s.day, s.period].append(c.subject)
        teacher_slot[c.teacher, s.day, s.period].append(c.subject)
        room_slot[s.room, s.day, s.period].append(c.subject)
        if (s.day, s.period) in data.teachers[c.teacher].unavailable:
            errors.append(f"{c.teacher} scheduled while unavailable at {data.days[s.day]} P{s.period + 1}")
        if data.rooms[s.room].capacity < data.groups[c.group].size:
            errors.append(f"Room {s.room} too small for {c.group}")
    for c in data.courses:
        if hours[c.id] != c.hours:
            errors.append(f"{c.group} {c.subject}: {hours[c.id]} of {c.hours} hours scheduled")
    for name, table in (("Group", group_slot), ("Teacher", teacher_slot), ("Room", room_slot)):
        for (who, d, p), subs in table.items():
            if len(subs) > 1:
                errors.append(f"{name} clash: {who} at {data.days[d]} P{p + 1}: {subs}")
    return errors
