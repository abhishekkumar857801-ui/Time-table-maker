# Student Timetable Optimization using Integer Programming

**Subject:** Operations Research (MCA)  **Language:** Python 3  **Solver:** PuLP + CBC (Branch & Bound)

The project builds a clash-free weekly timetable for several student groups. It assigns every lecture and lab to a
**day, period and room** so that all hard rules hold. Among all such timetables it picks the one with the lowest
total penalty for soft preferences: idle gaps, late classes, unwanted teacher slots and unbalanced days.

---

## 1. Project structure

```
timetable_optimization/
├── main.py                 # command-line program (solve + print + export)
├── app.py                  # Streamlit web interface
├── requirements.txt
├── data/sample_input.json  # 3 MCA sections, 6 teachers, 5 rooms, 21 courses
├── timetable/
│   ├── data_loader.py      # reads & validates JSON input
│   ├── model.py            # Integer Programming model + independent verifier
│   └── report.py           # timetables as console tables, Excel, HTML
└── output/                 # timetable.xlsx, timetable.html (generated)
```

## 2. How to run

```bash
cd timetable_optimization
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py                 # CLI: prints timetables, writes output/timetable.xlsx + .html
python main.py --verbose       # also shows the CBC branch-and-bound log
streamlit run app.py           # web UI: change weights/limits, view by group/teacher/room, download Excel
```

## 3. Mathematical formulation

### Sets and indices
| Symbol | Meaning |
|---|---|
| G | student groups (MCA-1A, MCA-1B, …), size n_g |
| T | teachers |
| R | rooms, capacity cap_r, type (lecture / lab) |
| C | courses: a (group, subject, teacher) combination. C^lec = lecture courses, C^lab = lab courses |
| D, P | days (d) and periods (p) |
| R_c | rooms that suit course c: right type **and** cap_r ≥ n_g |
| S | allowed start periods for a 2-period lab (a lab can't run across lunch) |
| H_c | weekly periods needed by course c |
| U_t, A_t | slots where teacher t is unavailable (hard rule) or would rather not teach (soft) |

### Decision variables
* **x(c,d,p,r) ∈ {0,1}**: 1 if lecture course c is held on day d, period p, in room r
* **y(c,d,p,r) ∈ {0,1}**: 1 if a lab block of course c **starts** at (d,p) in room r, so it takes periods p and p+1
* **h(g,d,p) ∈ {0,1}**: 1 if group g has an idle gap at (d,p)
* **a(g,d,p), b(g,d,p) ∈ [0,1]**: helper variables: "group g has had a class by period p" and "group g still has a class at period p or later"
* **L(g) ∈ ℤ⁺**: the most periods group g has on any single day

Occupancy expression (linear):
`occ(c,d,p) = Σ_r x(c,d,p,r)` for lectures, `occ(c,d,p) = Σ_r [ y(c,d,p,r) + y(c,d,p−1,r) ]` for labs.

### Objective (minimise the weighted penalty)

```
min Z = w1·Σ h(g,d,p)                    (student idle gaps)
      + w2·Σ_c Σ_d occ(c,d,last)         (classes in the last period)
      + w3·Σ_c Σ_(d,p)∈A_teacher(c) occ  (teacher "prefer-not" slots)
      + w4·Σ_g L(g)                      (heaviest day per group → balanced week)
```

### Hard constraints
1. **Weekly hours:** Σ x(c,·) = H_c for lectures. Σ y(c,·) = H_c / 2 for labs.
2. **Spread over the week:** Σ_p occ(c,d,p) ≤ k for each course and day (at most one lab block a day).
3. **No group clash:** Σ_{c∈C_g} occ(c,d,p) ≤ 1 for all g, d, p.
4. **No teacher clash:** Σ_{c∈C_t} occ(c,d,p) ≤ 1 for all t, d, p.
5. **Teacher availability:** the right-hand side of (4) is 0 when (d,p) ∈ U_t.
6. **No room clash:** Σ_c occ(c,d,p,r) ≤ 1 for all r, d, p.
7. **Room capacity and type:** handled by creating variables only for rooms in R_c.
8. **Daily limits:** Σ_p occupancy ≤ max/day for every group and every teacher.
9. **Lab contiguity:** the y variables make each lab two back-to-back periods that never run across lunch.

### Soft-constraint linearisation
* **Gap of any length** (computed separately for the morning and afternoon sessions):
  `a(p) ≥ occ(p)`, `a(p) ≥ a(p−1)`, `b(p) ≥ occ(p)`, `b(p) ≥ b(p+1)`,
  `h(p) ≥ a(p−1) + b(p+1) − occ(p) − 1`.
  These variables are penalised and only bounded from below, so at the optimum they take their true 0/1 values.
* **Balance:** `L(g) ≥ Σ_{c,p} occ(c,d,p)` for every day d. This is the min-max trick.

## 4. Solution method
The model is a **0-1 Integer Linear Program**. CBC solves it with **LP relaxation + Branch & Bound + cutting
planes**. If the time limit runs out first, it returns the best feasible timetable found so far. After the solve,
`verify()` checks the timetable on its own, without using the solver: no clashes, all hours scheduled, rooms
large enough, and teacher availability respected.

### Sample result (data/sample_input.json)
| Item | Value |
|---|---|
| Model size | 1423 variables, 936 constraints |
| Status | Optimal (proven) |
| Solve time | ~1 s |
| Objective | 45, all from daily balance: 22 periods over 5 days forces a busiest day of 5, so 3 groups × 5 × weight 3 = 45. Zero gaps, zero last-period classes, zero teacher "avoid" slots used. |

## 5. Using your own data
Edit `data/sample_input.json` or upload a new JSON file in the web UI:
* `days`, `periods`, and `lunch_after_period` (a 1-based period number)
* `rooms`: `id`, `capacity`, `type` (`lecture`/`lab`)
* `teachers`: `id`, `name`, `max_per_day`, `unavailable` / `avoid` as `[["Mon", 1], ...]` (period is 1-based)
* `groups`: `id`, `size`
* `courses`: `group`, `subject`, `teacher`, `hours`, `type` (lab hours must be even)
* `settings`: daily limits, solver time limit, objective weights

## 6. Possible extensions
Elective courses shared by several groups, a teacher's preference for consecutive classes, timetables across
multiple departments, and comparing IP against a heuristic (genetic algorithm or simulated annealing) for solution
quality and running time.



cd ~/Desktop/project/timetable_optimization && source .venv/bin/activate
streamlit run app.py
