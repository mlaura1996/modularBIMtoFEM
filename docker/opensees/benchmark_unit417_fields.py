"""Results of unit 417 on its own (the results run of the scalability
benchmark), in the files the Chapter 8 rendering scripts read.

The results run is partitioned, so every rank wrote the strain of its own
elements and the displacement of the nodes they use. This merges them:

  results_unit417/mesh.msh               the mesh, as written by the build
  results_unit417/sampled_elements.txt   element_index,element_tag (every element)
  results_unit417/principal_strains.csv  per element: peak tensile and peak
                                         compressive principal strain and
                                         when each occurred (same format and
                                         same computation as
                                         scripts/postprocess_timehistory.py)
  results_unit417/damage_map.csv         per element: final d+ and d- (0 for
                                         the elastic stone and brick elements)
  results_unit417/displacement.csv       per node: displacement at the time
                                         of the peak roof displacement and
                                         the peak of its norm over the run,
                                         both net of the self-weight state
  results_unit417/response.csv           time, Rd (mean x displacement of the
                                         roof nodes), base shear / W
  results_unit417/summary.json

so that scripts/render_strain_figure_gmsh.py <out>/results_unit417 renders
the strain envelopes of the unit exactly like Figures 8.36 and 8.37.

    python docker/opensees/benchmark_unit417_fields.py <out_dir>
"""
import glob
import json
import os
import re
import shutil
import sys

import numpy as np

OUT = sys.argv[1]
summ = json.load(open(os.path.join(OUT, "build_summary.json")))
LABEL = summ["results_run"]
NPART = max(int(k) for k in summ["partitions"])
RUN = os.path.join(OUT, "runs", LABEL)
DEST = os.path.join(OUT, "results_unit417")
os.makedirs(DEST, exist_ok=True)
W = summ["self_weight_N"]


def tcl_list(path, name):
    m = re.search(r"set %s \{([^}]*)\}" % name, open(path).read())
    return [int(v) for v in m.group(1).split()] if m else []


lists = [os.path.join(OUT, "model", f"np{NPART}", f"rank{r}_lists.tcl") for r in range(NPART)]
rank_eles = [tcl_list(p, "RANK_ELES") for p in lists]
rank_nodes = [tcl_list(p, "RANK_NODES") for p in lists]
all_eles = sorted(t for es in rank_eles for t in es)
index_of = {t: i for i, t in enumerate(all_eles)}
shutil.copy(os.path.join(OUT, "model", "mesh.msh"), os.path.join(DEST, "mesh.msh"))
with open(os.path.join(DEST, "sampled_elements.txt"), "w") as fh:
    fh.write("# element_index,element_tag - every element of the unit\n")
    for i, t in enumerate(all_eles):
        fh.write(f"{i},{t}\n")


def rows(path):
    with open(path) as fh:
        for line in fh:
            if line.strip():
                yield np.fromstring(line, sep=" ")


def principal(a, b, c, d, e, f):
    """Eigenvalues of symmetric 3x3 [[a d f][d b e][f e c]], largest and
    smallest (same closed form as scripts/postprocess_timehistory.py)."""
    p1 = d * d + e * e + f * f
    q = (a + b + c) / 3.0
    p = np.sqrt(np.maximum((a - q) ** 2 + (b - q) ** 2 + (c - q) ** 2 + 2 * p1, 0.0) / 6.0)
    ps = np.where(p > 0, p, 1.0)
    bxx, byy, bzz, bxy, byz, bxz = (a - q) / ps, (b - q) / ps, (c - q) / ps, d / ps, e / ps, f / ps
    det = bxx * (byy * bzz - byz * byz) - bxy * (bxy * bzz - byz * bxz) + bxz * (bxy * byz - byy * bxz)
    phi = np.arccos(np.clip(det / 2.0, -1.0, 1.0)) / 3.0
    e1 = q + 2 * p * np.cos(phi)
    e3 = q + 2 * p * np.cos(phi + 2 * np.pi / 3)
    diag = p1 <= 1e-30
    if np.any(diag):
        st = np.sort(np.stack([a, b, c], axis=-1), axis=-1)
        e1, e3 = np.where(diag, st[..., 2], e1), np.where(diag, st[..., 0], e3)
    return e1, e3


# --- principal strain envelopes: all ranks read in step -----------------------
n = len(all_eles)
e1_max, e3_min = np.full(n, -np.inf), np.full(n, np.inf)
t1, t3 = np.zeros(n), np.zeros(n)
idx = [np.array([index_of[t] for t in es]) for es in rank_eles]
streams = [rows(os.path.join(RUN, f"strain_r{r}.txt")) for r in range(NPART)]
n_rows = 0
for parts in zip(*streams):
    t = parts[0][0]
    for r, row in enumerate(parts):
        blk = row[1:].reshape(-1, 6)
        assert len(blk) == len(idx[r]), f"rank {r}: {len(blk)} strain blocks for {len(idx[r])} elements"
        exx, eyy, ezz, gxy, gyz, gzx = blk.T
        e1, e3 = principal(exx, eyy, ezz, gxy / 2, gyz / 2, gzx / 2)
        ii = idx[r]
        up = e1 > e1_max[ii]
        e1_max[ii[up]], t1[ii[up]] = e1[up], t
        dn = e3 < e3_min[ii]
        e3_min[ii[dn]], t3[ii[dn]] = e3[dn], t
    n_rows += 1
with open(os.path.join(DEST, "principal_strains.csv"), "w") as fh:
    fh.write("element_index,max_tensile_principal_strain,time_s,max_compressive_principal_strain,time_s\n")
    for i in range(n):
        fh.write(f"{i},{e1_max[i]:.8e},{t1[i]:.4f},{e3_min[i]:.8e},{t3[i]:.4f}\n")
print(f"strains: {n} elements, {n_rows} recorded steps; tension 99th percentile "
      f"{np.percentile(e1_max, 99):.3e}, compression 99th percentile {np.percentile(-e3_min, 99):.3e}")

# --- damage at the end ----------------------------------------------------------
dmg = np.zeros((n, 2))
for f in glob.glob(os.path.join(RUN, "damage_final_r*.txt")):
    for line in open(f):
        v = line.split()
        if len(v) >= 3:
            dmg[index_of[int(v[0])]] = float(v[1]), float(v[2])
with open(os.path.join(DEST, "damage_map.csv"), "w") as fh:
    fh.write("element_index,damage_tension,damage_compression\n")
    for i in range(n):
        fh.write(f"{i},{dmg[i, 0]:.6e},{dmg[i, 1]:.6e}\n")
n_plastic = sum(1 for f in glob.glob(os.path.join(RUN, "damage_final_r*.txt")) for _ in open(f))
print(f"damage: d+ > 0.5 in {(dmg[:, 0] > 0.5).sum()} and d- > 0.5 in {(dmg[:, 1] > 0.5).sum()} "
      f"of {n_plastic} masonry elements")

# --- roof displacement and base shear ---------------------------------------------
roof = np.loadtxt(os.path.join(RUN, "roof_disp.txt"), ndmin=2)
t_roof = roof[:, 0]
rd = roof[:, 1::3].mean(axis=1)
vb = None
for f in sorted(glob.glob(os.path.join(RUN, "base_reaction_r*.txt"))):
    r_ = np.loadtxt(f, ndmin=2)
    m = min(len(r_), len(t_roof))
    part = -r_[:m, 1::3].sum(axis=1)
    vb = part if vb is None else vb[:m] + part
k_pk = int(np.argmax(np.abs(rd)))
t_pk = float(t_roof[k_pk])
np.savetxt(os.path.join(DEST, "response.csv"),
           np.column_stack([t_roof[:len(vb)], rd[:len(vb)] * 1000, vb / W]),
           delimiter=",", header="time_s,Rd_mm,Vb_over_W", comments="", fmt="%.6f")
print(f"Rd max {abs(rd[k_pk]) * 1000:.2f} mm at {t_pk:.2f} s, base shear max {np.abs(vb).max() / W:.3f} W")

# --- displacements: at the peak and the envelope, net of the self-weight state ---
node_cols = {}
for r in range(NPART):
    for j, nd in enumerate(rank_nodes[r]):
        node_cols.setdefault(nd, (r, j))
nodes = sorted(node_cols)
streams = [rows(os.path.join(RUN, f"disp_r{r}.txt")) for r in range(NPART)]
u0 = u_pk = None
env = np.zeros(len(nodes))
best_dt = np.inf
sel_r = np.array([node_cols[nd][0] for nd in nodes])
sel_j = np.array([node_cols[nd][1] for nd in nodes])
for parts in zip(*streams):
    t = parts[0][0]
    u = np.empty((len(nodes), 3))
    for r, row in enumerate(parts):
        mask = sel_r == r
        u[mask] = row[1:].reshape(-1, 3)[sel_j[mask]]
    if u0 is None:
        u0 = u.copy()          # first recorded step: the self-weight state
    du = u - u0
    env = np.maximum(env, np.linalg.norm(du, axis=1))
    if abs(t - t_pk) < best_dt:
        best_dt, u_pk, t_snap = abs(t - t_pk), du, t
with open(os.path.join(DEST, "displacement.csv"), "w") as fh:
    fh.write(f"node,ux_at_peak_m,uy_at_peak_m,uz_at_peak_m,u_norm_envelope_m  # snapshot at t = {t_snap:.4f} s\n")
    for nd, d, e in zip(nodes, u_pk, env):
        fh.write(f"{nd},{d[0]:.6e},{d[1]:.6e},{d[2]:.6e},{e:.6e}\n")
print(f"displacements: {len(nodes)} nodes, snapshot at {t_snap:.3f} s, max norm at the peak "
      f"{np.linalg.norm(u_pk, axis=1).max() * 1000:.2f} mm, envelope max {env.max() * 1000:.2f} mm")

out = {"run": LABEL, "processes": NPART, "elements": n, "nodes": len(nodes), "recorded_steps": n_rows,
       "Rd_max_mm": abs(rd[k_pk]) * 1000, "t_Rd_max_s": t_pk, "Vb_max_over_W": float(np.abs(vb).max() / W),
       "snapshot_time_s": float(t_snap),
       "tension_strain_p99": float(np.percentile(e1_max, 99)),
       "compression_strain_p99": float(np.percentile(-e3_min, 99)),
       "masonry_elements": n_plastic,
       "dplus_over_05": int((dmg[:, 0] > 0.5).sum()), "dminus_over_05": int((dmg[:, 1] > 0.5).sum())}
json.dump(out, open(os.path.join(DEST, "summary.json"), "w"), indent=2)
print(f"wrote {DEST}")
