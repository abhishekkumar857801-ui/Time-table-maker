"""Load and validate the timetable input data (JSON)."""
import json
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

Slot = Tuple[int, int]  # (day_index, period_index), both 0-based


@dataclass
class Room:
    id: str
    capacity: int
    type: str  # "lecture" or "lab"


@dataclass
class Teacher:
    id: str
    name: str
    max_per_day: int
    unavailable: Set[Slot] = field(default_factory=set)
    avoid: Set[Slot] = field(default_factory=set)


@dataclass
class Group:
    id: str
    size: int


@dataclass
class Course:
    """One subject taught to one student group by one teacher."""
    id: str
    group: str
    subject: str
    teacher: str
    hours: int  # periods per week
    type: str   # "lecture" (1-period sessions) or "lab" (2-period blocks)


@dataclass
class ProblemData:
    days: List[str]
    periods: List[str]
    lunch_after_period: int  # 1-based period number after which lunch break happens
    rooms: Dict[str, Room]
    teachers: Dict[str, Teacher]
    groups: Dict[str, Group]
    courses: List[Course]
    settings: dict

    @property
    def D(self) -> int:
        return len(self.days)

    @property
    def P(self) -> int:
        return len(self.periods)


LAB_BLOCK = 2  # a lab session occupies 2 consecutive periods


def _parse_slots(raw, days: List[str], n_periods: int, who: str) -> Set[Slot]:
    slots = set()
    for day, period in raw:
        if day not in days:
            raise ValueError(f"{who}: unknown day '{day}'")
        if not 1 <= period <= n_periods:
            raise ValueError(f"{who}: period {period} out of range 1..{n_periods}")
        slots.add((days.index(day), period - 1))
    return slots


def load_data(source) -> ProblemData:
    """`source` may be a file path or an already-parsed dict."""
    if isinstance(source, dict):
        raw = source
    else:
        with open(source, "r", encoding="utf-8") as f:
            raw = json.load(f)

    days, periods = raw["days"], raw["periods"]
    rooms = {r["id"]: Room(r["id"], int(r["capacity"]), r["type"]) for r in raw["rooms"]}
    teachers = {
        t["id"]: Teacher(
            id=t["id"],
            name=t.get("name", t["id"]),
            max_per_day=int(t.get("max_per_day", len(periods))),
            unavailable=_parse_slots(t.get("unavailable", []), days, len(periods), t["id"]),
            avoid=_parse_slots(t.get("avoid", []), days, len(periods), t["id"]),
        )
        for t in raw["teachers"]
    }
    groups = {g["id"]: Group(g["id"], int(g["size"])) for g in raw["groups"]}

    courses = []
    for i, c in enumerate(raw["courses"]):
        course = Course(
            id=f"C{i + 1:02d}",
            group=c["group"],
            subject=c["subject"],
            teacher=c["teacher"],
            hours=int(c["hours"]),
            type=c.get("type", "lecture"),
        )
        if course.group not in groups:
            raise ValueError(f"Course {course.subject}: unknown group '{course.group}'")
        if course.teacher not in teachers:
            raise ValueError(f"Course {course.subject}: unknown teacher '{course.teacher}'")
        if course.type not in ("lecture", "lab"):
            raise ValueError(f"Course {course.subject}: type must be 'lecture' or 'lab'")
        if course.type == "lab" and course.hours % LAB_BLOCK != 0:
            raise ValueError(f"Lab {course.subject} ({course.group}): hours must be a multiple of {LAB_BLOCK}")
        courses.append(course)

    settings = {
        "max_periods_per_day_group": len(periods),
        "max_same_subject_per_day": 1,
        "time_limit_seconds": 60,
        "weights": {"student_gap": 10, "last_period": 2, "teacher_avoid": 5, "daily_balance": 3},
    }
    user_settings = raw.get("settings", {})
    settings.update({k: v for k, v in user_settings.items() if k != "weights"})
    settings["weights"].update(user_settings.get("weights", {}))

    return ProblemData(
        days=days,
        periods=periods,
        lunch_after_period=int(raw.get("lunch_after_period", 0)),
        rooms=rooms,
        teachers=teachers,
        groups=groups,
        courses=courses,
        settings=settings,
    )
