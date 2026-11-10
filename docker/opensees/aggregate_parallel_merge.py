"""Turns the per-rank recorders of an aggregate_parallel run into a Chapter 8
run directory, so scripts/postprocess_timehistory.py reads it unchanged.

    python docker/opensees/aggregate_parallel_merge.py <out_dir> <np>

Reads <out_dir>/runs/np<N>/ and writes <out_dir>/recorders_np<N>/:

  roof_disp.txt, roof_accel.txt, interface_disp.txt   copied (rank 0 holds
                                     every node and the global solution)
  base_reaction.txt                  the per-rank reactions summed: each
                                     rank only sees the forces of its own
                                     elements on a base node
  contact_force.txt                  the contact elements in the Chapter 8
                                     order
  solid_damage.txt                   one row, the final (= peak, damage
                                     never heals) d+ and d- of every
                                     recorded element in sampled order,
                                     0 0 for the elastic ones; the Chapter 8
                                     post-processing reads only the last
                                     row of this file anyway
  principal_strains.csv              the strain of every recorded element
                                     reduced to its peak principal values
                                     here, streaming the rank files one step
                                     at a time, with the same closed form
                                     and the same gamma/2 as the Chapter 8
                                     post-processing. A merged
                                     solid_strain.txt of the full model
                                     would be tens of GB written only to be
                                     read once.
  summary.json, mesh.msh, sampled_elements.txt, interface_node_pairs.txt

then: python scripts/postprocess_timehistory.py <out_dir>/recorders_np<N> <out_dir>/results_np<N>
"""
import json
import os
import shutil
import sys

import numpy as np

OUT = sys.argv[1]
NP = int(sys.argv[2])
RUN = os.path.join(OUT, "runs", f"np{NP}")
DEST = os.path.join(OUT, f"recorders_np{NP}")
os.makedirs(DEST, exist_ok=True)
summ = json.load(open(os.path.join(OUT, "build_summary.json")))
timing = {}
if os.path.isfile(os.path.join(RUN, "timing.txt")):
    for line in open(os.path.join(RUN, "timing.txt")):
        k, *v = line.split()
        timing[k] = " ".join(v)
else:
    sys.exit(f"{RUN}: no timing.txt, the run is missing or did not finish")


def tcl_list(path, name):
    import re
    m = re.search(r"set %s \{([^}]*)\}" % name, open(path).read())
    return [int(v) for v in m.group(1).split()] if m else []


lists = [os.path.join(OUT, "model", f"np{NP}", f"rank{r}_lists.tcl") for r in range(NP)]
rank_sampled = [tcl_list(p, "RANK_SAMPLED") for p in lists]
rank_contact = [tcl_list(p, "RANK_CONTACT") for p in lists]
sampled = summ["sampled_elements"]
index_of = {t: i for i, t in enumerate(sampled)}
n = len(sampled)
written = []

for f in ("roof_disp", "roof_accel", "interface_disp"):
    src = os.path.join(RUN, f"{f}.txt")
    if os.path.isfile(src):
        shutil.copy(src, os.path.join(DEST, f"{f}.txt"))
        written.append(f)
for f in ("mesh.msh", "sampled_elements.txt", "interface_node_pairs.txt"):
    shutil.copy(os.path.join(OUT, f), os.path.join(DEST, f))


def rows(path):
    with open(path) as fh:
        for line in fh:
            if line.strip():
                yield np.array(line.split(), dtype=float)


# --- base reactions: sum of the ranks --------------------------------------------
with open(os.path.join(DEST, "base_reaction.txt"), "w") as fh:
    for parts in zip(*[rows(os.path.join(RUN, f"base_reaction_r{r}.txt")) for r in range(NP)]):
        tot = parts[0].copy()
        for p in parts[1:]:
            tot[1:] += p[1:]
        fh.write(" ".join(repr(float(v)) for v in tot) + "\n")
written.append("base_reaction")

# --- contact forces in the Chapter 8 order ---------------------------------------
order = summ["contact_element_order"]
if order:
    pos = {t: i for i, t in enumerate(order)}
    files = [(r, os.path.join(RUN, f"contact_force_r{r}.txt")) for r in range(NP) if rank_contact[r]]
    with open(os.path.join(DEST, "contact_force.txt"), "w") as fh:
        width = None
        for parts in zip(*[rows(p) for _r, p in files]):
            blocks = [None] * len(order)
            for (r, _p), row in zip(files, parts):
                w = (len(row) - 1) // len(rank_contact[r])
                assert w * len(rank_contact[r]) == len(row) - 1, f"rank {r}: contact columns"
                width = w
                for k, t in enumerate(rank_contact[r]):
                    blocks[pos[t]] = row[1 + k * w:1 + (k + 1) * w]
            fh.write(repr(float(parts[0][0])) + " " +
                     " ".join(repr(float(v)) for b in blocks for v in b) + "\n")
    written.append("contact_force")
    print(f"contact forces: {len(order)} elements, {width} values each")

# --- final damage ---------------------------------------------------------------
dmg = np.zeros((n, 2))
n_plastic = 0
for r in range(NP):
    for line in open(os.path.join(RUN, f"damage_final_r{r}.txt")):
        v = line.split()
        if len(v) >= 3:
            dmg[index_of[int(v[0])]] = float(v[1]), float(v[2])
            n_plastic += 1
t_final = float(timing.get("final_time", "nan"))
with open(os.path.join(DEST, "solid_damage.txt"), "w") as fh:
    fh.write(repr(t_final) + " " + " ".join(f"{v:.10g}" for v in dmg.ravel()) + "\n")
written.append("solid_damage")
print(f"damage: {n_plastic} masonry elements of {n} recorded; d+ > 0.5 in {(dmg[:, 0] > 0.5).sum()}, "
      f"d- > 0.5 in {(dmg[:, 1] > 0.5).sum()}")


# --- principal strains, streamed ---------------------------------------------------
def principal(a, b, c, d, e, f):
    """Largest and smallest eigenvalue of [[a d f][d b e][f e c]] (closed form,
    as scripts/postprocess_timehistory.py)."""
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


e1_max, e3_min = np.full(n, -np.inf), np.full(n, np.inf)
t1, t3 = np.zeros(n), np.zeros(n)
active = [r for r in range(NP) if rank_sampled[r]]
idx = {r: np.array([index_of[t] for t in rank_sampled[r]]) for r in active}
n_rows = 0
for parts in zip(*[rows(os.path.join(RUN, f"solid_strain_r{r}.txt")) for r in active]):
    t = parts[0][0]
    for r, row in zip(active, parts):
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
    if n_rows % 500 == 0:
        print(f"  strains: {n_rows} steps read", flush=True)
with open(os.path.join(DEST, "principal_strains.csv"), "w") as fh:
    fh.write("element_index,max_tensile_principal_strain,time_s,max_compressive_principal_strain,time_s\n")
    for i in range(n):
        fh.write(f"{i},{e1_max[i]:.8e},{t1[i]:.4f},{e3_min[i]:.8e},{t3[i]:.4f}\n")
print(f"strains: {n} elements, {n_rows} recorded steps")

# --- summary in the Chapter 8 format ----------------------------------------------
grav = sum(float(open(os.path.join(RUN, f"gravity_reaction_r{r}.txt")).read()) for r in range(NP))
out = {k: v for k, v in summ.items() if k not in ("sampled_elements", "contact_element_order")}
out.update({
    "processes": NP, "solver": timing.get("system"),
    "steps_failed": int(timing.get("failed_steps", -1)),
    "steps_subdivided": int(timing.get("subdivided_steps", -1)),
    "steps_done": int(timing.get("steps_done", -1)),
    "iterations": int(timing.get("iterations", -1)),
    "final_time_s": t_final,
    "base_reaction_N": abs(grav),
    "model_build_s": float(timing.get("build_s", "nan")),
    "gravity_s": float(timing.get("gravity_s", "nan")),
    "wall_time_transient_h": float(timing.get("transient_s", "nan")) / 3600.0,
    "recorders_written": sorted(written), "recorders_empty": [],
    "strain_reduced_to_principal_values_in_merge": True,
})
json.dump(out, open(os.path.join(DEST, "summary.json"), "w"), indent=2)
print(f"self-weight {summ['self_weight_N']:,.1f} N, base reaction after gravity {abs(grav):,.1f} N "
      f"({abs(abs(grav) - summ['self_weight_N']) / summ['self_weight_N'] * 100:.3f} %)")
print(f"transient {out['wall_time_transient_h']:.2f} h, {out['iterations']} iterations, "
      f"{out['steps_subdivided']} subdivided, {out['steps_failed']} failed")
print(f"wrote {DEST}")
