"""
Student Timetable Optimization using Integer Programming
Command-line entry point.

Usage:
    python main.py                               # uses data/sample_input.json
    python main.py --input my_data.json --time-limit 120 --verbose
"""
import argparse
import os

from timetable import TimetableModel, load_data, verify
from timetable.report import export_excel, export_html, group_tables, print_tables, teacher_tables


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Student timetable optimisation with Integer Programming (PuLP + CBC)")
    ap.add_argument("--input", default=os.path.join(here, "data", "sample_input.json"))
    ap.add_argument("--outdir", default=os.path.join(here, "output"))
    ap.add_argument("--time-limit", type=int, default=None, help="solver time limit in seconds")
    ap.add_argument("--verbose", action="store_true", help="show CBC solver log")
    args = ap.parse_args()

    data = load_data(args.input)
    print(f"Loaded: {len(data.groups)} groups, {len(data.teachers)} teachers, {len(data.rooms)} rooms, "
          f"{len(data.courses)} courses, {data.D} days x {data.P} periods")

    model = TimetableModel(data)
    print(f"IP model: {len(model.prob.variables())} variables, {len(model.prob.constraints)} constraints")
    print("Solving with CBC branch-and-bound ...")
    res = model.solve(time_limit=args.time_limit, msg=args.verbose)

    print(f"\nStatus      : {res.status}")
    print(f"Solve time  : {res.solve_seconds:.2f} s")
    if res.objective is None:
        print("No feasible timetable exists for these constraints. Try relaxing teacher availability, "
              "daily limits, or adding rooms.")
        return
    print(f"Objective   : {res.objective:.1f}  (weighted penalty, lower is better)")
    for k, v in res.penalty_breakdown.items():
        print(f"   {k:<14}: {v:g}  x weight {data.settings['weights'][k]}")

    errors = verify(data, res.sessions)
    print("Verification: " + ("all hard constraints satisfied ✔" if not errors else f"{len(errors)} violations"))
    for e in errors:
        print("   -", e)

    print_tables("Group", group_tables(data, res.sessions))
    print_tables("Teacher", teacher_tables(data, res.sessions))

    os.makedirs(args.outdir, exist_ok=True)
    xlsx = os.path.join(args.outdir, "timetable.xlsx")
    html = os.path.join(args.outdir, "timetable.html")
    export_excel(xlsx, data, res.sessions)
    export_html(html, data, res.sessions,
                summary=f"Status: {res.status} | Objective: {res.objective:.1f} | Solve time: {res.solve_seconds:.2f}s")
    print(f"\nSaved: {xlsx}\nSaved: {html}")


if __name__ == "__main__":
    main()
