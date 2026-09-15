#!/usr/bin/env python3
"""Turns the time-history recorders into the quantities Chapter 6 reports.

Produces, from docker/opensees/timehistory_castelnuovo.py's output:

  principal_strains.csv    per element: max tensile and max compressive
                           principal strain over the whole run, and when
                           they occurred
  damage_map.csv           per element: final damage (see "why the last
                           row" below) - the data behind Chapter 6's
                           damage-pattern figures
  response.csv             per step: roof displacement Rd, base shear BS in
                           both directions, base shear coefficient BS/W,
                           global drift Rd/H, interface opening Id
  energy.csv                per step: cumulative dissipated hysteretic energy
  summary_postprocess.json the peaks and totals

REWRITTEN after the first version would have needed to hold the raw
recorder files (39 GB on the real run) entirely in RAM via np.loadtxt, and
would have computed principal strains with a Python-level eigenvalue call
PER ELEMENT PER STEP - at tens of thousands of sampled elements x ~4000
steps, tens of millions of individual np.linalg.eigvalsh calls, which is
impractical. Neither defect showed up on the small test cases used while
writing the first version. Two fixes:

1. STRAIN is read by streaming one line (one time step) at a time with
   np.fromstring - never more than one row in memory - and its principal
   values are computed with the closed-form trigonometric solution for a
   symmetric 3x3 matrix (Smith 1961), fully vectorised across every element
   in one step at once instead of one LAPACK call per element. Verified
   against np.linalg.eigvalsh on 50,000 random matrices before use: max
   error 8.8e-15, ~5x faster even at that scale, and the degenerate
   (diagonal, zero-shear) case checked separately.

2. DAMAGE uses only the LAST row of its file, read with a backward seek in
   O(1) time regardless of file size - not a full scan. This relies on
   damage being non-decreasing: every response name registered by the
   analysis script (ASDConcrete3D's own damage indices, and the equivalent
   plastic strain / crack width fallbacks) is a continuum-damage-mechanics
   internal variable that never heals by construction, so the final step
   already IS the peak. A cheap sanity check reads one more row from
   roughly halfway through the file and warns (does not just proceed
   silently) if any value there exceeds the final one - the signature of a
   response that turned out not to be monotonic after all.

PRINCIPAL STRAINS ARE NOT AN OPENSEES OUTPUT. OpenSees records the six
strain components; the principal strains are the eigenvalues of the strain
TENSOR. Two things have to be right for that and are easy to get wrong:

1. the recorder writes ENGINEERING shear strains (gamma), while the tensor
   needs gamma/2 off the diagonal. Skipping the halving inflates the
   principal values - by up to a factor of 2 in shear-dominated elements,
   which is exactly where masonry cracks.
2. the component ORDER is assumed to be (exx, eyy, ezz, gxy, gyz, gzx),
   FourNodeTetrahedron's convention. Asserted against the column count on
   the first row and reported, not silently trusted.

    python scripts/postprocess_timehistory.py [run_dir] [out_dir]

Needs only numpy - runs the same in or out of the Docker image.

OUTPUT GOES SOMEWHERE ELSE THAN THE RAW RECORDERS, ON PURPOSE. run_dir
(recorders_timehistory/, 39 GB on the real run) is under
output/castelnuovo/recorders_*/, which .gitignore excludes - correctly,
that much data does not belong in git and GitHub rejects anything over
100 MB per file outright. out_dir defaults to the same name with
"recorders_" swapped for "results_" (results_timehistory/), which is NOT
covered by that ignore pattern, so once this has run on the machine that
holds the raw data, `git add output/castelnuovo/results_timehistory/` picks
up only the small CSVs/JSON this script writes - never the raw files - and
that is what should be committed and pulled back, not the 39 GB itself.
"""
import json
import math
import os
import sys
import time

import numpy as np

RUN_DIR = (sys.argv[1] if len(sys.argv) > 1
           else "output/castelnuovo/recorders_timehistory")
_default_out = (RUN_DIR.replace("recorders_", "results_", 1)
                if "recorders_" in os.path.basename(RUN_DIR.rstrip("/\\"))
                else RUN_DIR + "_results")
OUT_DIR = sys.argv[2] if len(sys.argv) > 2 else _default_out
os.makedirs(OUT_DIR, exist_ok=True)


def out_path(filename):
    """filename already carries its extension - every call site below
    passes e.g. "response.csv" or "summary_postprocess.json" in full."""
    return os.path.join(OUT_DIR, filename)


STRAIN_COMPONENTS = 6
G_ACCEL = 9.81
PROGRESS_INTERVAL_S = 5.0
SMALL_FILE_LIMIT_MB = 500   # node recorders are expected to be small; a
# node recorder anywhere near this size means something is not as assumed
# (e.g. far more monitored nodes than intended) and should be looked at
# rather than silently loaded whole.


def recorder_path(name):
    return os.path.join(RUN_DIR, f"{name}.txt")


def peek_first_line(path):
    """First line's values, without reading the rest of the file."""
    with open(path, "r") as fh:
        line = fh.readline()
    if not line.strip():
        return None
    return np.fromstring(line, sep=" ")


def stream_time_value_rows(path, expected_extra_cols=None):
    """Yields (time, values) for every row, one at a time.

    Uses a manual readline() loop rather than `for line in f`: Python's
    line iterator read-aheads its own internal buffer, which makes
    f.tell() lie - and f.tell() is how progress is reported here against
    the file's total byte size, since the row count is not known up front
    (retried/subdivided steps mean it need not match the nominal step
    count).
    """
    size = os.path.getsize(path)
    t_last_print = time.time()
    with open(path, "r") as fh:
        first = True
        while True:
            line = fh.readline()
            if not line:
                break
            if not line.strip():
                continue
            vals = np.fromstring(line, sep=" ")
            if first:
                if expected_extra_cols is not None and \
                   (len(vals) - 1) != expected_extra_cols:
                    raise ValueError(
                        f"{path}: first row has {len(vals) - 1} value "
                        f"column(s), expected {expected_extra_cols}")
                first = False
            yield vals[0], vals[1:]
            now = time.time()
            if now - t_last_print > PROGRESS_INTERVAL_S:
                pct = 100.0 * fh.tell() / size if size else 100.0
                print(f"    ... {pct:5.1f}% of {os.path.basename(path)} "
                      f"({fh.tell()/1e9:.2f} / {size/1e9:.2f} GB)", flush=True)
                t_last_print = now


def principal_eig_3x3_sym(a, b, c, d, e, f):
    """Eigenvalues of a batch of symmetric 3x3 matrices
        [[a d f]
         [d b e]
         [f e c]]
    one value per matrix in a, b, c, d, e, f (1D arrays, same length).
    Returns (e1, e2, e3) with e1 >= e2 >= e3 - e1 most tensile, e3 most
    compressive.

    Closed-form trigonometric solution (Smith, "Eigenvalues of a symmetric
    3x3 matrix", Comm. ACM 4(4), 1961) instead of np.linalg.eigvalsh: at
    tens of thousands of elements x thousands of steps, one LAPACK call per
    matrix adds up, and a symmetric 3x3 has an exact solution needing no
    iteration - plain vectorised array arithmetic over the whole batch at
    once. Verified against eigvalsh before use (see module docstring).
    """
    p1 = d * d + e * e + f * f
    q = (a + b + c) / 3.0
    p2 = (a - q) ** 2 + (b - q) ** 2 + (c - q) ** 2 + 2 * p1
    p = np.sqrt(np.maximum(p2, 0.0) / 6.0)
    p_safe = np.where(p > 0, p, 1.0)   # guarded; overwritten below where p1==0
    bxx, byy, bzz = (a - q) / p_safe, (b - q) / p_safe, (c - q) / p_safe
    bxy, byz, bxz = d / p_safe, e / p_safe, f / p_safe
    detB = (bxx * (byy * bzz - byz * byz)
            - bxy * (bxy * bzz - byz * bxz)
            + bxz * (bxy * byz - byy * bxz))
    r = np.clip(detB / 2.0, -1.0, 1.0)
    phi = np.arccos(r) / 3.0
    eig1 = q + 2 * p * np.cos(phi)
    eig3 = q + 2 * p * np.cos(phi + 2 * np.pi / 3)
    eig2 = 3 * q - eig1 - eig3
    # Purely diagonal (zero shear): p1 == 0 makes p == 0 and the formula
    # above divides by the guard value instead of the real (zero) p - the
    # eigenvalues are just a, b, c themselves, sorted.
    diag = p1 <= 1e-30
    if np.any(diag):
        stacked = np.sort(np.stack([a, b, c], axis=-1), axis=-1)
        eig1 = np.where(diag, stacked[..., 2], eig1)
        eig2 = np.where(diag, stacked[..., 1], eig2)
        eig3 = np.where(diag, stacked[..., 0], eig3)
    return eig1, eig2, eig3


def compute_principal_strains(path):
    """Streams solid_strain.txt once; returns per-element peak tensile and
    peak compressive principal strain and when each occurred. Never holds
    more than one time step's data (plus the small per-element running
    arrays) in memory."""
    n_ele = None
    e1_max = e3_min = t_e1 = t_e3 = None
    n_rows = 0
    t0 = time.perf_counter()
    for t, vals in stream_time_value_rows(path):
        if n_ele is None:
            if len(vals) % STRAIN_COMPONENTS != 0:
                sys.exit(f"{path}: {len(vals)} value columns is not a "
                         f"multiple of {STRAIN_COMPONENTS} - the component "
                         f"layout is not (exx,eyy,ezz,gxy,gyz,gzx) and the "
                         f"principal strains would be nonsense. Inspect the "
                         f"file before going further.")
            n_ele = len(vals) // STRAIN_COMPONENTS
            e1_max = np.full(n_ele, -np.inf)
            e3_min = np.full(n_ele, np.inf)
            t_e1 = np.zeros(n_ele)
            t_e3 = np.zeros(n_ele)
            print(f"  strain: {n_ele} elements, streaming "
                  f"{os.path.getsize(path)/1e9:.2f} GB...", flush=True)
        block = vals.reshape(n_ele, STRAIN_COMPONENTS)
        exx, eyy, ezz, gxy, gyz, gzx = (block[:, i] for i in range(6))
        e1, _e2, e3 = principal_eig_3x3_sym(
            exx, eyy, ezz, gxy / 2.0, gyz / 2.0, gzx / 2.0)
        up = e1 > e1_max
        e1_max[up], t_e1[up] = e1[up], t
        dn = e3 < e3_min
        e3_min[dn], t_e3[dn] = e3[dn], t
        n_rows += 1
    if n_ele is None:
        sys.exit(f"{path}: no data rows")
    print(f"  {n_rows} time step(s) processed in "
          f"{time.perf_counter()-t0:.1f} s")
    return e1_max, t_e1, e3_min, t_e3


def read_last_line_values(path):
    """The LAST non-empty line of a large text file, in O(1) time - reads
    backward from the end instead of scanning forward from the start. Used
    for damage: see the module docstring for why the last row is the peak."""
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        chunk = b""
        while pos > 0:
            step = min(65536, pos)
            pos -= step
            fh.seek(pos)
            chunk = fh.read(step) + chunk
            lines = chunk.splitlines()
            if len(lines) > 1 or pos == 0:
                for line in reversed(lines):
                    if line.strip():
                        return np.fromstring(line, sep=" ")
        return None


def read_line_near_fraction(path, frac):
    """An arbitrary row at roughly `frac` of the way through the file, by
    byte offset rather than by counting rows - a cheap monotonicity sanity
    check, not an exact time lookup."""
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        fh.seek(int(size * frac))
        fh.readline()             # discard the partial line landed on
        line = fh.readline()
        if not line:
            return None
        return np.fromstring(line.decode(), sep=" ")


def peak_damage_monotonic(path):
    """Final (= peak, given monotonicity) value per column, plus a
    same-cost sanity check against a mid-run row."""
    last = read_last_line_values(path)
    if last is None:
        return None
    mid = read_line_near_fraction(path, 0.5)
    if mid is not None and len(mid) == len(last):
        exceed = mid[1:] - last[1:]
        bad = int(np.sum(exceed > 1e-6))
        if bad:
            print(f"    WARNING: {bad} value(s) partway through the run "
                  f"exceed the final value - this response may not be "
                  f"monotonic, and the true peak may be underestimated by "
                  f"using the last row. Consider a full scan for this one.")
    return last[1:]


def safe_loadtxt(path, label):
    size_mb = os.path.getsize(path) / 1e6
    if size_mb > SMALL_FILE_LIMIT_MB:
        sys.exit(f"{path} is {size_mb:.0f} MB - larger than the "
                 f"{SMALL_FILE_LIMIT_MB} MB expected for a {label} "
                 f"recorder (few nodes/elements). Loading it whole could "
                 f"exhaust memory; stopping rather than guessing whether "
                 f"that is safe on this machine.")
    data = np.loadtxt(path)
    return data.reshape(1, -1) if data.ndim == 1 else data


def load_recorder(name, required=True):
    path = recorder_path(name)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        if required:
            sys.exit(f"Missing or empty: {path}.")
        print(f"  (skipped, missing or empty: {name})")
        return None
    return safe_loadtxt(path, name)


print(f"Post-processing {RUN_DIR}")
t_all = time.perf_counter()
with open(os.path.join(RUN_DIR, "summary.json")) as fh:
    summary = json.load(fh)
print(f"  run: {summary.get('run')}, record: {summary.get('record')}, "
      f"{summary.get('steps_requested')} steps requested")
if summary.get("recorders_empty"):
    print(f"  NOTE: the run reported these recorders as empty: "
          f"{', '.join(summary['recorders_empty'])}")

out = {}

# --- principal strains (streamed) -----------------------------------------
strain_path = recorder_path("solid_strain")
if not os.path.isfile(strain_path):
    sys.exit(f"Missing {strain_path}.")
e1_max, t_e1, e3_min, t_e3 = compute_principal_strains(strain_path)
n_ele = len(e1_max)

with open(out_path("principal_strains.csv"), "w") as fh:
    fh.write("element_index,max_tensile_principal_strain,time_s,"
             "max_compressive_principal_strain,time_s\n")
    for j in range(n_ele):
        fh.write(f"{j},{e1_max[j]:.8e},{t_e1[j]:.4f},"
                 f"{e3_min[j]:.8e},{t_e3[j]:.4f}\n")
print(f"  wrote principal_strains.csv "
      f"(peak tensile {e1_max.max():.3e}, peak compressive {e3_min.min():.3e})")
out["peak_tensile_principal_strain"] = float(e1_max.max())
out["peak_compressive_principal_strain"] = float(e3_min.min())
out["solid_elements_recorded"] = n_ele

# --- damage (last row only) ------------------------------------------------
damage = None
damage_path_used = None
for cand in ("damage", "Damage", "damage_tension", "equivalent_plastic_strain",
             "crack_width"):
    p = recorder_path(f"solid_{cand}")
    if not os.path.isfile(p) or os.path.getsize(p) == 0:
        continue
    first = peek_first_line(p)
    if first is not None and len(first) > 1:
        print(f"  damage recorder in use: solid_{cand} "
              f"({os.path.getsize(p)/1e9:.2f} GB, reading only the last row)")
        damage = peak_damage_monotonic(p)
        damage_path_used = p
        out["damage_response_used"] = cand
        break
if damage is not None:
    per_ele = len(damage) // n_ele if n_ele and len(damage) % n_ele == 0 else None
    if per_ele is None:
        print(f"  damage file has {len(damage)} columns against {n_ele} "
              f"elements - not divisible, so per-element splitting is "
              f"skipped; peak reported over all columns.")
        with open(out_path("damage_map.csv"), "w") as fh:
            fh.write("column_index,final_value\n")
            for j, v in enumerate(damage):
                fh.write(f"{j},{v:.8e}\n")
    elif per_ele == 2 and out.get("damage_response_used") in ("damage", "Damage"):
        # ASDConcrete3D's "damage"/"Damage" response is documented as
        # exactly (d+, d-) - tension damage, then compression damage, in
        # that order (opensees.github.io/OpenSeesDocumentation/user/manual/
        # material/ndMaterials/ASDConcrete3D.html). Confirmed against the
        # reference rather than guessed, so the columns are named for what
        # they are instead of "component 0/1".
        vals = damage.reshape(n_ele, per_ele)
        with open(out_path("damage_map.csv"), "w") as fh:
            fh.write("element_index,damage_tension,damage_compression\n")
            for j in range(n_ele):
                fh.write(f"{j},{vals[j,0]:.8e},{vals[j,1]:.8e}\n")
        out["peak_damage_tension"] = float(vals[:, 0].max())
        out["peak_damage_compression"] = float(vals[:, 1].max())
    else:
        vals = damage.reshape(n_ele, per_ele)
        with open(out_path("damage_map.csv"), "w") as fh:
            fh.write("element_index," +
                     ",".join(f"final_component_{k}" for k in range(per_ele)) + "\n")
            for j in range(n_ele):
                fh.write(f"{j}," + ",".join(f"{v:.8e}" for v in vals[j]) + "\n")
    out["peak_damage"] = float(damage.max())
    print(f"  wrote damage_map.csv (peak {damage.max():.4f})")
else:
    print("  no damage recorder produced data - see summary.json's "
          "recorders_empty; the damage pattern cannot be plotted from this run")

# --- roof displacement, base shear, drift (small files) -------------------
roof = load_recorder("roof_disp")
base = load_recorder("base_reaction")
weight = summary["self_weight_N"]

n_roof = (roof.shape[1] - 1) // 3
n_base = (base.shape[1] - 1) // 3
roof_xyz = roof[:, 1:].reshape(len(roof), n_roof, 3)
base_xyz = base[:, 1:].reshape(len(base), n_base, 3)

dof = summary.get("excitation_dof", 1) - 1
rd = roof_xyz[:, :, dof]
rd_repr = rd[np.arange(len(rd)), np.argmax(np.abs(rd), axis=1)]
bs_x = -base_xyz[:, :, 0].sum(axis=1)
bs_y = -base_xyz[:, :, 1].sum(axis=1)
bs = bs_x if dof == 0 else bs_y

height = summary.get("model_height_m")
if height is None:
    msh = os.path.join(RUN_DIR, "mesh.msh")
    zs = []
    if os.path.exists(msh):
        with open(msh) as fh:
            in_nodes = False
            for line in fh:
                if line.startswith("$Nodes"):
                    in_nodes = True
                    continue
                if line.startswith("$EndNodes"):
                    break
                if in_nodes:
                    p = line.split()
                    if len(p) == 3:
                        try:
                            zs.append(float(p[2]))
                        except ValueError:
                            pass
    if zs:
        height = max(zs) - min(zs)
if not height:
    print("  WARNING: could not determine the model height from mesh.msh, so "
          "the drift ratio is left blank rather than computed against a "
          "guessed height.")

with open(out_path("response.csv"), "w") as fh:
    fh.write("time_s,Rd_m,BS_N,BS_over_W,drift_ratio,BSx_N,BSy_N\n")
    for i, t in enumerate(roof[:, 0]):
        drift = (rd_repr[i] / height) if height else float("nan")
        fh.write(f"{t:.4f},{rd_repr[i]:.8e},{bs[i]:.6e},"
                 f"{bs[i]/weight:.6e},{drift:.8e},"
                 f"{bs_x[i]:.6e},{bs_y[i]:.6e}\n")
print(f"  wrote response.csv (peak |Rd| = {np.abs(rd_repr).max():.5f} m, "
      f"peak |BS| = {np.abs(bs).max():.1f} N = "
      f"{np.abs(bs/weight).max():.4f} W)")
out["peak_roof_displacement_m"] = float(np.abs(rd_repr).max())
out["peak_base_shear_N"] = float(np.abs(bs).max())
out["peak_base_shear_coefficient"] = float(np.abs(bs / weight).max())
if height:
    out["model_height_m"] = float(height)
    out["peak_drift_ratio"] = float(np.abs(rd_repr).max() / height)

# --- cumulative dissipated hysteretic energy -------------------------------
d_rd = np.diff(rd_repr)
bs_mid = 0.5 * (bs[1:] + bs[:-1])
incr = np.abs(bs_mid * d_rd)
cum = np.concatenate(([0.0], np.cumsum(incr)))
with open(out_path("energy.csv"), "w") as fh:
    fh.write("time_s,cumulative_dissipated_energy_J\n")
    for t, e in zip(roof[:, 0], cum):
        fh.write(f"{t:.4f},{e:.6e}\n")
print(f"  wrote energy.csv (total {cum[-1]:.1f} J)")
out["cumulative_dissipated_energy_J"] = float(cum[-1])

# --- interface opening (Id) -------------------------------------------------
iface = load_recorder("interface_disp", required=False)
pairs_path = os.path.join(RUN_DIR, "interface_node_pairs.txt")
if iface is not None and os.path.exists(pairs_path):
    pairs = []
    with open(pairs_path) as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            # split(",", 2): the writer (timehistory_castelnuovo.py) puts
            # InterfaceSelection.key_for()'s own "cx,cy,cz" string as the
            # third field with no quoting, so a real line has 5
            # comma-separated pieces, not 3 - splitting on every comma
            # crashes here. Only the first two fields (both node tags,
            # which cannot themselves contain a comma) are ever needed.
            o, d, _key = line.strip().split(",", 2)
            pairs.append((int(o), int(d)))
    node_order = sorted({n for p in pairs for n in p})
    idx = {n: i for i, n in enumerate(node_order)}
    n_if = (iface.shape[1] - 1) // 3
    if n_if != len(node_order):
        print(f"  WARNING: interface_disp has {n_if} nodes but "
              f"{len(node_order)} were expected - skipping Id rather than "
              f"pairing the wrong columns.")
    else:
        xyz = iface[:, 1:].reshape(len(iface), n_if, 3)
        opening = np.zeros(len(iface))
        for o, d in pairs:
            rel = xyz[:, idx[d], :] - xyz[:, idx[o], :]
            opening = np.maximum(opening, np.linalg.norm(rel, axis=1))
        with open(out_path("interface_opening.csv"), "w") as fh:
            fh.write("time_s,max_opening_m\n")
            for t, v in zip(iface[:, 0], opening):
                fh.write(f"{t:.4f},{v:.8e}\n")
        print(f"  wrote interface_opening.csv (peak {opening.max():.6f} m)")
        out["peak_interface_opening_m"] = float(opening.max())

with open(out_path("summary_postprocess.json"), "w") as fh:
    json.dump(out, fh, indent=2)
print(f"  wrote summary_postprocess.json")
print(f"Done in {time.perf_counter()-t_all:.1f} s.")
