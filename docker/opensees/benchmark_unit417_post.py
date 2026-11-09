"""Collects the unit 417 scalability benchmark (run_benchmark_unit417.sh).

For every run: wall time of the model build, of gravity and of the
transient, Newton iterations, speed-up and parallel efficiency, and the
check that matters before any timing is read: the response must be the
same whatever the number of processes. Rd (mean x displacement of the roof
nodes) and the base shear of every run are compared with the sequential
UmfPack run.

    python docker/opensees/benchmark_unit417_post.py <out_dir>

Writes <out_dir>/benchmark_results.csv and <out_dir>/benchmark_timehistories.csv.
"""
import csv
import glob
import json
import os
import sys

import numpy as np

OUT = sys.argv[1]
summ = json.load(open(os.path.join(OUT, "build_summary.json")))
W = summ["self_weight_N"]
runs = [line.split() for line in open(os.path.join(OUT, "runs.txt")) if line.strip()]


def read_timing(path):
    out = {}
    for line in open(path):
        k, *v = line.split()
        out[k] = " ".join(v)
    return out


def peak_rss_kb(path):
    if not os.path.isfile(path):
        return None
    for line in open(path, errors="replace"):
        if "Maximum resident set size" in line:
            return int(line.split()[-1])
    return None


res, hist = {}, {}
for label, npart in runs:
    d = os.path.join(OUT, "runs", label)
    tp = os.path.join(d, "timing.txt")
    if not os.path.isfile(tp):
        print(f"{label}: no timing.txt, run missing or failed")
        continue
    tm = read_timing(tp)
    roof = np.loadtxt(os.path.join(d, "roof_disp.txt"), ndmin=2)
    t = roof[:, 0]
    rd = roof[:, 1::3].mean(axis=1)
    vb = None
    for f in sorted(glob.glob(os.path.join(d, "base_reaction_r*.txt"))):
        r = np.loadtxt(f, ndmin=2)
        n = min(len(r), len(t))
        part = -r[:n, 1::3].sum(axis=1)
        vb = part if vb is None else vb[:n] + part
    hist[label] = (t, rd, vb)
    res[label] = {"label": label, "np": int(npart), "system": tm["system"],
                  "build_s": float(tm["build_s"]), "gravity_s": float(tm["gravity_s"]),
                  "transient_s": float(tm["transient_s"]), "iterations": int(tm["iterations"]),
                  "subdivided_steps": int(tm["subdivided_steps"]), "failed_steps": int(tm["failed_steps"]),
                  "steps_done": int(tm["steps_done"]) - (0 if int(tm["failed_steps"]) else 1),
                  "Rd_max_mm": float(np.abs(rd).max() * 1000), "Vb_max_over_W": float(np.abs(vb).max() / W),
                  "peak_rss_MB": (peak_rss_kb(os.path.join(OUT, f"{label}.out")) or 0) / 1024}

ref = "np1_umfpack" if "np1_umfpack" in hist else next(iter(hist), None)
base = "np1_mumps" if "np1_mumps" in res else ref
for label, r in res.items():
    t, rd, vb = hist[label]
    t0, rd0, vb0 = hist[ref]
    n = min(len(rd), len(rd0))
    r["Rd_diff_rel"] = float(np.abs(rd[:n] - rd0[:n]).max() / max(np.abs(rd0[:n]).max(), 1e-30))
    r["Vb_diff_rel"] = float(np.abs(vb[:n] - vb0[:n]).max() / max(np.abs(vb0[:n]).max(), 1e-30))
    r["time_per_step_s"] = r["transient_s"] / max(r["steps_done"], 1)
    r["time_per_iteration_s"] = r["transient_s"] / max(r["iterations"], 1)
    r["speedup_vs_np1_mumps"] = res[base]["transient_s"] / r["transient_s"]
    r["efficiency"] = r["speedup_vs_np1_mumps"] / r["np"]
    r["speedup_vs_umfpack"] = res[ref]["transient_s"] / r["transient_s"]

cols = ["label", "np", "system", "build_s", "gravity_s", "transient_s", "time_per_step_s",
        "iterations", "time_per_iteration_s", "subdivided_steps", "failed_steps", "steps_done",
        "speedup_vs_np1_mumps", "efficiency", "speedup_vs_umfpack", "Rd_max_mm", "Vb_max_over_W",
        "Rd_diff_rel", "Vb_diff_rel", "peak_rss_MB"]
with open(os.path.join(OUT, "benchmark_results.csv"), "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in res.values():
        w.writerow(r)

if hist:
    n = min(len(h[0]) for h in hist.values())
    with open(os.path.join(OUT, "benchmark_timehistories.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time_s"] + [f"{k}_{q}" for k in hist for q in ("Rd_mm", "Vb_over_W")])
        t_ref = hist[ref][0]
        for i in range(n):
            row = [f"{t_ref[i]:.5f}"]
            for k, (t, rd, vb) in hist.items():
                row += [f"{rd[i] * 1000:.6f}", f"{vb[i] / W:.6f}"]
            w.writerow(row)

print(f"model: {summ['nodes']} nodes, {summ['elements']} elements, {summ['dofs_free']} free DOFs, "
      f"{summ['ties']} ties ({summ['tie_model']}), {summ['steps']} steps")
print(f"{'run':14s} {'np':>3s} {'transient':>10s} {'s/step':>7s} {'iter':>6s} {'speed-up':>8s} "
      f"{'eff.':>5s} {'Rd max':>8s} {'dRd':>9s} {'dVb':>9s}")
for r in res.values():
    print(f"{r['label']:14s} {r['np']:3d} {r['transient_s']:9.1f}s {r['time_per_step_s']:7.2f} "
          f"{r['iterations']:6d} {r['speedup_vs_np1_mumps']:8.2f} {r['efficiency']:5.2f} "
          f"{r['Rd_max_mm']:7.3f}mm {r['Rd_diff_rel']:9.2e} {r['Vb_diff_rel']:9.2e}")
print(f"wrote {OUT}/benchmark_results.csv and benchmark_timehistories.csv")
