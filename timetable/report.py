"""Turn solver output into readable timetables (console, Excel, HTML)."""
from typing import Dict, List

import pandas as pd

from .data_loader import ProblemData
from .model import Session


def _grid(data: ProblemData, sessions: List[Session], key: str, value: str, fmt) -> Dict[str, pd.DataFrame]:
    """Build one Day x Period table per entity (group / teacher / room)."""
    tables: Dict[str, pd.DataFrame] = {}
    for s in sessions:
        owner = {"group": s.course.group, "teacher": s.course.teacher, "room": s.room}[key]
        if owner not in tables:
            tables[owner] = pd.DataFrame("", index=data.days, columns=data.periods)
        tables[owner].iat[s.day, s.period] = fmt(s)
    # insert lunch column for readability
    if data.lunch_after_period:
        for name, df in tables.items():
            df.insert(data.lunch_after_period, "LUNCH", "—")
    return dict(sorted(tables.items()))


def group_tables(data: ProblemData, sessions: List[Session]) -> Dict[str, pd.DataFrame]:
    return _grid(data, sessions, "group", "",
                 lambda s: f"{s.course.subject}\n{data.teachers[s.course.teacher].name} | {s.room}")


def teacher_tables(data: ProblemData, sessions: List[Session]) -> Dict[str, pd.DataFrame]:
    t = _grid(data, sessions, "teacher", "", lambda s: f"{s.course.subject}\n{s.course.group} | {s.room}")
    return {f"{k} - {data.teachers[k].name}": v for k, v in t.items()}


def room_tables(data: ProblemData, sessions: List[Session]) -> Dict[str, pd.DataFrame]:
    return _grid(data, sessions, "room", "", lambda s: f"{s.course.subject}\n{s.course.group}")


def print_tables(title: str, tables: Dict[str, pd.DataFrame]):
    with pd.option_context("display.max_columns", None, "display.width", 250, "display.max_colwidth", 28):
        for name, df in tables.items():
            print(f"\n=== {title}: {name} ===")
            print(df.replace(r"\n", " / ", regex=True).to_string())


def export_excel(path: str, data: ProblemData, sessions: List[Session]):
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for prefix, tables in (("G", group_tables(data, sessions)),
                               ("T", teacher_tables(data, sessions)),
                               ("R", room_tables(data, sessions))):
            for name, df in tables.items():
                df.to_excel(xw, sheet_name=f"{prefix} {name}"[:31])
        for ws in xw.book.worksheets:
            ws.column_dimensions["A"].width = 8
            for col in "BCDEFGHIJKL":
                ws.column_dimensions[col].width = 26
            for row in ws.iter_rows():
                for cell in row:
                    cell.alignment = cell.alignment.copy(wrap_text=True, vertical="center")


_HTML_CSS = """
body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222}
h1{margin-bottom:4px} h2{margin-top:32px;color:#1f4e79}
table{border-collapse:collapse;width:100%;margin-top:8px}
th,td{border:1px solid #bbb;padding:6px;text-align:center;font-size:13px;white-space:pre-line}
th{background:#1f4e79;color:#fff} td.lab{background:#fde9d9} td.lec{background:#e2efda} td.lunch{background:#eee}
"""


def export_html(path: str, data: ProblemData, sessions: List[Session], summary: str = ""):
    labs = {(s.course.group, s.day, s.period) for s in sessions if s.is_lab}
    parts = [f"<html><head><meta charset='utf-8'><title>Timetable</title><style>{_HTML_CSS}</style></head><body>",
             "<h1>Student Timetable (Integer Programming)</h1>", f"<p>{summary}</p>"]
    for g, df in group_tables(data, sessions).items():
        parts.append(f"<h2>{g}</h2><table><tr><th>Day</th>" + "".join(f"<th>{c}</th>" for c in df.columns) + "</tr>")
        for d, (day, row) in enumerate(df.iterrows()):
            parts.append(f"<tr><th>{day}</th>")
            p = 0
            for col, val in row.items():
                if col == "LUNCH":
                    parts.append("<td class='lunch'>LUNCH</td>")
                    continue
                cls = "lab" if (g, d, p) in labs else ("lec" if val else "")
                parts.append(f"<td class='{cls}'>{val}</td>")
                p += 1
            parts.append("</tr>")
        parts.append("</table>")
    parts.append("</body></html>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(parts))
