#!/usr/bin/env python3
"""Turns the time-history recorders into the quantities Chapter 6 reports.

Produces, from docker/opensees/timehistory_castelnuovo.py's output:

  principal_strains.csv    per element: max tensile and max compressive
                           principal strain over the whole run, and when
                           they occurred
  damage_map.csv           per element: peak damage (whichever ASDConcrete3D
                           response the run actually wrote) - the data
                           behind Chapter 6's damage-pattern figures
  response.csv             per step: roof displacement Rd, base shear BS in
                           both directions, base shear coefficient BS/W,
                           global drift Rd/H, interface opening Id
  energy.csv               per step: cumulative dissipated hysteretic energy
  summary_postprocess.json the peaks and totals

PRINCIPAL STRAINS ARE NOT AN OPENSEES OUTPUT. OpenSees records the six
strain components; the principal strains are the eigenvalues of the strain
TENSOR. Two things have to be right for that and are easy to get wrong:

1. the recorder writes ENGINEERING shear strains (gamma), while the tensor
   needs gamma/2 off the diagonal. Skipping the halving inflates the
   principal values - by up to a factor of 2 in shear-dominated elements,
   which is exactly where masonry cracks.
2. the component ORDER is assumed to be (exx, eyy, ezz, gxy, gyz, gzx),
   which is FourNodeTetrahedron's convention. It is asserted against the
   column count and reported, not silently trusted - if a build orders them
   differently the off-diagonal terms land in the wrong places.

    python scripts/postprocess_timehistory.py [run_dir]
"""
import json
import math
import os
import sys

import numpy as np

RUN_DIR = (sys.argv[1] if len(sys.argv) > 1
           else "output/castelnuovo/recorders_timehistory")

# Element recorders write one row per step: time, then n_components per
# element in the order the -ele list was given.
STRAIN_COMPONENTS = 6
G_ACCEL = 9.81


def load_recorder(name, required=True):
    path = os.path.join(RUN_DIR, f"{name}.txt")
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        if required:
            sys.exit(f"Missing or empty: {path}. If the run reported this "
                     f"recorder as EMPTY, the response name was not valid on "
                     f"that OpenSees build and the quantity was never "
                     f"recorded - rerun with a name that works rather than "
                     f"post-processing nothing.")
        print(f"  (skipped, missing or empty: {name})")
        return None
    data = np.loadtxt(path)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    return data


def principal_strains(row6):
    """Eigenvalues of the strain tensor built from six recorded components.

    row6 = (exx, eyy, ezz, gxy, gyz, gzx) with ENGINEERING shear strains,
    so the tensor's off-diagonal terms are gamma/2.
    """
    exx, eyy, ezz, gxy, gyz, gzx = row6
    t = np.array([[exx, gxy / 2.0, gzx / 2.0],
                  [gxy / 2.0, eyy, gyz / 2.0],
                  [gzx / 2.0, gyz / 2.0, ezz]])
    return np.linalg.eigvalsh(t)          # ascending: e3 <= e2 <= e1


print(f"Post-processing {RUN_DIR}")
with open(os.path.join(RUN_DIR, "summary.json")) as fh:
    summary = json.load(fh)
print(f"  run: {summary.get('run')}, record: {summary.get('record')}, "
      f"{summary.get('steps_requested')} steps")
if summary.get("recorders_empty"):
    print(f"  NOTE: the run reported these recorders as empty: "
          f"{', '.join(summary['recorders_empty'])}")

out = {}

# --- principal strains ---------------------------------------------------
strain = load_recorder("solid_strain")
time_col = strain[:, 0]
n_vals = strain.shape[1] - 1
if n_vals % STRAIN_COMPONENTS != 0:
    sys.exit(f"solid_strain.txt has {n_vals} value columns, not a multiple "
             f"of {STRAIN_COMPONENTS} - the component layout is not what "
             f"this script assumes and the principal strains would be "
             f"nonsense. Inspect the file before going further.")
n_ele = n_vals // STRAIN_COMPONENTS
print(f"  strain: {len(time_col)} steps x {n_ele} elements x "
      f"{STRAIN_COMPONENTS} components")

e1_max = np.full(n_ele, -np.inf)     # most tensile principal strain
e3_min = np.full(n_ele, np.inf)      # most compressive
t_e1 = np.zeros(n_ele)
t_e3 = np.zeros(n_ele)
for i, t in enumerate(time_col):
    block = strain[i, 1:].reshape(n_ele, STRAIN_COMPONENTS)
    for j in range(n_ele):
        e3, _e2, e1 = principal_strains(block[j])
        if e1 > e1_max[j]:
            e1_max[j], t_e1[j] = e1, t
        if e3 < e3_min[j]:
            e3_min[j], t_e3[j] = e3, t

with open(os.path.join(RUN_DIR, "principal_strains.csv"), "w") as fh:
    fh.write("element_index,max_tensile_principal_strain,time_s,"
             "max_compressive_principal_strain,time_s\n")
    for j in range(n_ele):
        fh.write(f"{j},{e1_max[j]:.8e},{t_e1[j]:.4f},"
                 f"{e3_min[j]:.8e},{t_e3[j]:.4f}\n")
print(f"  wrote principal_strains.csv "
      f"(peak tensile {e1_max.max():.3e}, peak compressive {e3_min.min():.3e})")
out["peak_tensile_principal_strain"] = float(e1_max.max())
out["peak_compressive_principal_strain"] = float(e3_min.min())

# --- damage --------------------------------------------------------------
# Whichever of the candidate response names the run actually wrote.
damage = None
for cand in ("damage", "Damage", "damage_tension", "equivalent_plastic_strain",
             "crack_width"):
    damage = load_recorder(f"solid_{cand}", required=False)
    if damage is not None:
        print(f"  damage recorder in use: solid_{cand}")
        out["damage_response_used"] = cand
        break
if damage is not None:
    vals = damage[:, 1:]
    per_ele = vals.shape[1] // n_ele if n_ele and vals.shape[1] % n_ele == 0 else None
    if per_ele is None:
        print(f"  damage file has {vals.shape[1]} columns against {n_ele} "
              f"elements - not divisible, so it is written per element "
              f"differently than the strain file. Peak reported over all "
              f"columns without splitting per element.")
        peak = vals.max(axis=0)
        with open(os.path.join(RUN_DIR, "damage_map.csv"), "w") as fh:
            fh.write("column_index,peak_value\n")
            for j, v in enumerate(peak):
                fh.write(f"{j},{v:.8e}\n")
    else:
        peak = vals.max(axis=0).reshape(n_ele, per_ele)
        with open(os.path.join(RUN_DIR, "damage_map.csv"), "w") as fh:
            fh.write("element_index," +
                     ",".join(f"peak_component_{k}" for k in range(per_ele)) + "\n")
            for j in range(n_ele):
                fh.write(f"{j}," + ",".join(f"{v:.8e}" for v in peak[j]) + "\n")
    out["peak_damage"] = float(vals.max())
    print(f"  wrote damage_map.csv (peak {vals.max():.4f})")
else:
    print("  no damage recorder produced data - see summary.json's "
          "recorders_empty; the damage pattern cannot be plotted from this run")

# --- roof displacement, base shear, drift -------------------------------
roof = load_recorder("roof_disp")
base = load_recorder("base_reaction")
weight = summary["self_weight_N"]

n_roof = (roof.shape[1] - 1) // 3
n_base = (base.shape[1] - 1) // 3
roof_xyz = roof[:, 1:].reshape(len(roof), n_roof, 3)
base_xyz = base[:, 1:].reshape(len(base), n_base, 3)

# Rd: the largest horizontal displacement among the monitored roof nodes at
# each instant, in the excitation direction.
dof = summary.get("excitation_dof", 1) - 1
rd = roof_xyz[:, :, dof]
rd_repr = rd[np.arange(len(rd)), np.argmax(np.abs(rd), axis=1)]
# Base shear: sum of the reactions. A reaction opposes the applied load, so
# the base shear is its negative.
bs_x = -base_xyz[:, :, 0].sum(axis=1)
bs_y = -base_xyz[:, :, 1].sum(axis=1)
bs = bs_x if dof == 0 else bs_y

# Global drift needs a height. Taken from the model's own vertical extent
# rather than typed in.
height = summary.get("model_height_m")
if height is None:
    msh = os.path.join(RUN_DIR, "mesh.msh")
    height = None
    if os.path.exists(msh):
        zs = []
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

with open(os.path.join(RUN_DIR, "response.csv"), "w") as fh:
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

# --- cumulative dissipated hysteretic energy -----------------------------
# The area swept in the base-shear / roof-displacement plane, integrated
# incrementally with the trapezoidal rule. This is the hysteretic energy
# only in the sense Chapter 6 uses it - the work done by the base shear
# through the roof displacement - not a decomposition of the full energy
# balance.
d_rd = np.diff(rd_repr)
bs_mid = 0.5 * (bs[1:] + bs[:-1])
incr = np.abs(bs_mid * d_rd)
cum = np.concatenate(([0.0], np.cumsum(incr)))
with open(os.path.join(RUN_DIR, "energy.csv"), "w") as fh:
    fh.write("time_s,cumulative_dissipated_energy_J\n")
    for t, e in zip(roof[:, 0], cum):
        fh.write(f"{t:.4f},{e:.6e}\n")
print(f"  wrote energy.csv (total {cum[-1]:.1f} J)")
out["cumulative_dissipated_energy_J"] = float(cum[-1])

# --- interface opening (Id) ---------------------------------------------
iface = load_recorder("interface_disp", required=False)
pairs_path = os.path.join(RUN_DIR, "interface_node_pairs.txt")
if iface is not None and os.path.exists(pairs_path):
    node_order = []
    # The recorder wrote the nodes in the sorted order the script used.
    pairs = []
    with open(pairs_path) as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            o, d, _k = line.strip().split(",")
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
        with open(os.path.join(RUN_DIR, "interface_opening.csv"), "w") as fh:
            fh.write("time_s,max_opening_m\n")
            for t, v in zip(iface[:, 0], opening):
                fh.write(f"{t:.4f},{v:.8e}\n")
        print(f"  wrote interface_opening.csv (peak {opening.max():.6f} m)")
        out["peak_interface_opening_m"] = float(opening.max())

with open(os.path.join(RUN_DIR, "summary_postprocess.json"), "w") as fh:
    json.dump(out, fh, indent=2)
print(f"  wrote summary_postprocess.json")
print("Done.")
