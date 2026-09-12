"""Dumps the modal results as CSV, one row per mode.

modal_properties.txt is laid out for reading, not for reuse - the numbers
that belong together (eigenvalue, frequency, period, participation, and its
running total) are spread across four separate sections of it. This pulls
them into one table.

Columns: mode, lambda, f_Hz, T_s, PRMx/y/z, PRMx/y/z_cum (all ratios in %).

    python scripts/export_modal_data.py <recorders_dir> [out.csv]

With no out.csv it writes modal_data.csv inside the recorders directory.
"""
import math
import os
import sys

DATA_DIR = (sys.argv[1] if len(sys.argv) > 1
            else "output/castelnuovo/recorders_castelnuovo_tied")
OUT_CSV = (sys.argv[2] if len(sys.argv) > 2
           else os.path.join(DATA_DIR, "modal_data.csv"))

PER_MODE = "* 9. MODAL PARTICIPATION MASS RATIOS (%):"
CUMULATIVE = "* 10. MODAL PARTICIPATION MASS RATIOS (%) (cumulative):"


def section(text, heading):
    """Rows of one '* N. ...' section as (mode, mx, my, mz, ...)."""
    body = text.split(heading)[1].split("\n*")[0]
    rows = []
    for line in body.splitlines():
        p = line.split()
        if len(p) == 7 and p[0].isdigit():
            rows.append((int(p[0]), float(p[1]), float(p[2]), float(p[3])))
    return rows


with open(os.path.join(DATA_DIR, "modal_properties.txt")) as f:
    props = f.read()
per_mode = section(props, PER_MODE)
cumulative = section(props, CUMULATIVE)

with open(os.path.join(DATA_DIR, "eigenvalues.txt")) as f:
    eigenvalues = [float(x) for x in f.read().split()]

assert len(per_mode) == len(cumulative) == len(eigenvalues), (
    f"{len(per_mode)} PRM rows, {len(cumulative)} cumulative rows, "
    f"{len(eigenvalues)} eigenvalues - modal_properties.txt and "
    f"eigenvalues.txt disagree about how many modes this run has"
)

with open(OUT_CSV, "w") as out:
    out.write("mode,lambda,f_Hz,T_s,PRMx,PRMy,PRMz,"
              "PRMx_cum,PRMy_cum,PRMz_cum\n")
    for (m, mx, my, mz), (_m2, cx, cy, cz), lam in zip(
            per_mode, cumulative, eigenvalues):
        f_hz = math.sqrt(lam) / (2 * math.pi)
        out.write(f"{m},{lam:.4f},{f_hz:.4f},{1 / f_hz:.4f},"
                  f"{mx:.4f},{my:.4f},{mz:.4f},{cx:.4f},{cy:.4f},{cz:.4f}\n")

print(f"Wrote {OUT_CSV} ({len(per_mode)} modes)")
print(f"cumulative after {len(per_mode)} modes: "
      f"MX = {cumulative[-1][1]:.2f}%, MY = {cumulative[-1][2]:.2f}%, "
      f"MZ = {cumulative[-1][3]:.2f}%")
