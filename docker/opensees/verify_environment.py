"""Acceptance test for a new machine: does it reproduce this model?

Run this BEFORE launching a long analysis on a second computer. It runs the
tied Castelnuovo pipeline end to end at 10 modes - STEP import, fragment,
two-pass junction refinement, tie construction, static self-weight, eigen
solve - and compares every result against the reference committed in
resources/reference/castelnuovo_tied_10modes.json.

Why bother: a multi-day nonlinear run that turns out to have been computed
on a subtly different geometry or a different tie set is a multi-day run
thrown away, and the difference would not announce itself. The quantities
checked here each fail for a different reason, which is the point:

  mesh nodes/elements   the OCC kernel or gmsh version differs, so the
                        geometry was fragmented or meshed differently
  total volume          the STEP file itself differs
  open junctions/ties   the tie search found a different set, so the walls
                        are connected differently
  base reaction         mass or boundary conditions differ
  eigenvalues           everything above, plus the solver itself

Takes roughly 20 minutes (the mesh and the static solve dominate; the ten
modes are about a minute).

    python docker/opensees/verify_environment.py

Exit code 0 = the machine reproduces the reference and is safe to use.
"""
import json
import math
import os
import platform
import subprocess
import sys

sys.path.insert(0, "/app")

REF_PATH = "resources/reference/castelnuovo_tied_10modes.json"
SCRATCH = "output/castelnuovo/recorders_verify_environment"
EIGEN = "docker/opensees/eigen_castelnuovo_tied.py"

# An identical build on a different CPU can differ in the last bits through
# a different BLAS code path, so bitwise equality is the wrong test. These
# are the loosest values at which a difference would still be numerical
# noise rather than a different model: 1e-6 relative on eigenvalues is far
# tighter than any modelling decision, and the integer counts must match
# exactly - there is no "nearly the same" number of nodes.
REL_TOL_EIGEN = 1e-6
REL_TOL_FORCE = 1e-9
REL_TOL_VOLUME = 1e-9

if not os.path.isfile(REF_PATH):
    sys.exit(f"Missing {REF_PATH} - this file is the reference and must be "
             f"committed in the repository.")
with open(REF_PATH) as f:
    ref = json.load(f)

print(f"Machine: {platform.platform()}")
print(f"Python:  {sys.version.split()[0]}")
print(f"Reference produced on: {ref.get('_produced_on', 'unknown')}")
print(f"\nRunning {EIGEN} --n-modes 10 (about 20 minutes)...\n", flush=True)

proc = subprocess.run(
    [sys.executable, EIGEN, "--n-modes", "10", "--out-dir", SCRATCH],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
if proc.returncode != 0:
    print(proc.stdout[-4000:])
    sys.exit(f"FAIL: the analysis itself did not complete "
             f"(exit {proc.returncode}). The environment is not usable; "
             f"fix this before comparing numbers.")

with open(f"{SCRATCH}/summary.json") as f:
    got = json.load(f)
with open(f"{SCRATCH}/eigenvalues.txt") as f:
    got_eig = [float(x) for x in f.read().split()]

failures, warnings = [], []


def check_int(name):
    a, b = ref[name], got[name]
    ok = a == b
    print(f"  {'OK  ' if ok else 'FAIL'}  {name:28s} ref {a!s:>14}  got {b!s:>14}")
    if not ok:
        failures.append(f"{name}: expected {a}, got {b}")


def check_float(name, tol):
    a, b = float(ref[name]), float(got[name])
    rel = abs(b - a) / abs(a) if a else abs(b)
    ok = rel <= tol
    print(f"  {'OK  ' if ok else 'FAIL'}  {name:28s} ref {a:14.6f}  "
          f"got {b:14.6f}  rel {rel:.2e}")
    if not ok:
        failures.append(f"{name}: relative difference {rel:.3e} exceeds {tol:.0e}")


print("Model:")
for n in ("mesh_nodes", "mesh_elements", "open_junctions",
          "equaldof_constraints"):
    check_int(n)
check_float("total_volume_m3", REL_TOL_VOLUME)
check_float("young_modulus_MPa", 0.0)

print("\nStatic:")
check_float("self_weight_calculated_N", REL_TOL_FORCE)
check_float("total_base_reaction_N", REL_TOL_FORCE)

print("\nEigenvalues:")
if len(got_eig) != len(ref["eigenvalues"]):
    failures.append(f"eigenvalue count: expected {len(ref['eigenvalues'])}, "
                    f"got {len(got_eig)}")
    print(f"  FAIL  count: expected {len(ref['eigenvalues'])}, got {len(got_eig)}")
else:
    worst, worst_mode = 0.0, 0
    for i, (a, b) in enumerate(zip(ref["eigenvalues"], got_eig), start=1):
        rel = abs(b - a) / abs(a)
        if rel > worst:
            worst, worst_mode = rel, i
        T_ref, T_got = 2 * math.pi / math.sqrt(a), 2 * math.pi / math.sqrt(b)
        flag = "OK  " if rel <= REL_TOL_EIGEN else "FAIL"
        print(f"  {flag}  mode {i:2d}  ref {a:12.4f} (T={T_ref:.4f}s)  "
              f"got {b:12.4f} (T={T_got:.4f}s)  rel {rel:.2e}")
        if rel > REL_TOL_EIGEN:
            failures.append(f"eigenvalue {i}: relative difference {rel:.3e}")
    if worst > 1e-12:
        warnings.append(
            f"largest eigenvalue difference {worst:.2e} (mode {worst_mode}) is "
            f"above bitwise agreement. Within tolerance, and expected on "
            f"different hardware, but worth noting in the thesis record.")

print(f"\n{'=' * 70}")
if failures:
    print(f"FAIL - {len(failures)} check(s) did not pass:")
    for f_ in failures:
        print(f"  - {f_}")
    print("\nDo NOT start a long run on this machine until these are "
          "explained. The model here is not the model the reference "
          "describes.")
    sys.exit(1)

print("PASS - this machine reproduces the reference model.")
for w in warnings:
    print(f"\nNote: {w}")
print(f"\nScratch results left in {SCRATCH}/ for inspection.")
