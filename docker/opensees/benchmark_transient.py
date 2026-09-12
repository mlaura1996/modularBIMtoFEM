"""Measures what a time-history on the Castelnuovo model actually costs.

The question this answers is "can the nonlinear dynamic analysis run on
this laptop", and the only honest way to answer it is to time the
operations it is made of on the real model rather than to guess from the
element count.

It measures, on the tied 34,821-node / 119,953-element model:

  1. model build time (nodes, elements, constraints)
  2. ONE stiffness factorisation + solve (the static self-weight step)
  3. per-step cost of a LINEAR transient, where the effective stiffness is
     constant so it is factored once and every later step is only a
     back-substitution
  4. per-step cost of a transient forced to REFACTOR every step, which is
     what a nonlinear material or a contact interface actually does

(3) and (4) differ by one to two orders of magnitude, and conflating them
is how a dynamic analysis gets estimated at two hours and then runs for a
week. The nonlinear cost is roughly steps x iterations x (4).

The mesh is read from the .msh the eigen run exported and the constraints
from its junction_ties.txt, so this does not re-mesh or re-derive the
junctions. Base fixity is recomputed geometrically (lowest nodes of each
volume) rather than through InterfaceDetection: this is a TIMING
benchmark, and the exact fixity set shifts the free-DOF count by a
fraction of a percent while leaving the sparsity - which is what governs
the factorisation cost - unchanged. Do not read physics off this script's
displacements.

    python docker/opensees/benchmark_transient.py [run_dir] [n_steps]
"""
import os
import sys
import time

sys.path.insert(0, "/app")

import numpy as np
import gmsh
import openseespy.opensees as ops

from external.gmsh2opensees.g2o_nodes_functions import (
    get_all_nodes, add_nodes_to_ops, fix_nodes,
)
from core.opensees_generation.model_builder import ModelBuilder, Element
from core.ifc_processing.data_extractor import Material

RUN_DIR = (sys.argv[1] if len(sys.argv) > 1
           else "output/castelnuovo/recorders_castelnuovo_tied_80modes")
N_STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 10
MSH_PATH = f"{RUN_DIR}/castelnuovo_tied.msh"
TIES_PATH = f"{RUN_DIR}/junction_ties.txt"

E_MPA, NU, RHO = 1227.95, 0.2, 1450.0
DT = 0.005          # s - a typical step for a masonry time-history
BASE_TOL = 0.05     # m


def stamp(label, t0):
    dt_ = time.perf_counter() - t0
    print(f"[{dt_:9.3f} s] {label}", flush=True)
    return dt_


for p in (MSH_PATH, TIES_PATH):
    if not os.path.isfile(p):
        sys.exit(f"Missing {p} - run docker/opensees/eigen_castelnuovo_tied.py "
                 f"--n-modes 80 first.")

t_all = time.perf_counter()
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
t0 = time.perf_counter()
gmsh.open(MSH_PATH)
vol_tags = [t for _d, t in gmsh.model.getEntities(3)]
stamp(f"mesh loaded ({len(vol_tags)} volumes)", t0)

ops.wipe()
model = ModelBuilder(ndm=3, ndf=3)
model.initialize_model()

t0 = time.perf_counter()
node_tags_all, node_coords_all = get_all_nodes(gmsh.model)
add_nodes_to_ops(node_tags_all, gmsh.model)
n_nodes = len(node_tags_all)
stamp(f"{n_nodes} nodes added", t0)

material = Material(
    name="Masonry", density=RHO, young_modulus=E_MPA, poisson_ratio=NU,
    is_structural=True, material_model_type="LinearElastic",
    compressive_strength=0, tensile_strength=0,
    compression_fracture_energy=0, tensile_fracture_energy=0,
    compressive_elastic_behaviour=0,
)
t0 = time.perf_counter()
element_tags = Element.add_elements_to_opensees(gmsh.model, {"Masonry": material})
t_elements = stamp(f"{len(element_tags)} elements added", t0)

# --- base fixity (geometric; see module docstring) ------------------------
t0 = time.perf_counter()
node_z = {int(t): float(c[2]) for t, c in zip(node_tags_all, node_coords_all)}
z_global_min = min(node_z.values())
base_ids = set()
for vol in vol_tags:
    _et, _etg, en = gmsh.model.mesh.getElements(dim=3, tag=vol)
    if not en or len(en[0]) == 0:
        continue
    vnodes = set(int(x) for x in en[0])
    zs = [node_z[n] for n in vnodes if n in node_z]
    if not zs:
        continue
    # Only volumes actually sitting on the ground, not every volume's own
    # underside - fixing the latter would brace the whole aggregate at every
    # storey and make the model artificially stiff (and fast).
    if min(zs) > z_global_min + 0.5:
        continue
    for n in vnodes:
        if node_z[n] <= min(zs) + BASE_TOL:
            base_ids.add(n)
base_arr = np.asarray(sorted(base_ids), dtype=np.int64)
fix_nodes(base_arr, "XYZ")
stamp(f"{len(base_arr)} base nodes fixed", t0)

t0 = time.perf_counter()
n_ties = 0
with open(TIES_PATH) as fh:
    for line in fh:
        if line.startswith("#"):
            continue
        parts = line.strip().split(",")
        if len(parts) != 3:
            continue
        ops.equalDOF(int(parts[0]), int(parts[1]), 1, 2, 3)
        n_ties += 1
stamp(f"{n_ties} equalDOF constraints applied", t0)

free_dof = 3 * n_nodes - 3 * len(base_arr) - 3 * n_ties
print(f"\napprox. free DOFs: {free_dof:,}\n")

# --- 1. one factorisation + solve (the static step) -----------------------
ops.system("UmfPack")
ops.numberer("RCM")
ops.constraints("Transformation")
ops.test("NormDispIncr", 1e-6, 30, 0)
ops.algorithm("Newton")
ops.integrator("LoadControl", 1.0)
ops.analysis("Static")
t0 = time.perf_counter()
ok = ops.analyze(1)
t_static = stamp(f"static self-weight solve (returned {ok})", t0)
assert ok == 0, f"static analysis did not converge (ok={ok})"

# --- 2. linear transient: factor once, then back-substitute --------------
# Newmark with constant dt and a linear material gives a constant effective
# stiffness, so Linear algorithm reuses the factorisation.
ops.wipeAnalysis()
ops.system("UmfPack")
ops.numberer("RCM")
ops.constraints("Transformation")
ops.test("NormDispIncr", 1e-6, 10, 0)
ops.algorithm("Linear")
ops.integrator("Newmark", 0.5, 0.25)
ops.analysis("Transient")
lin = []
for i in range(N_STEPS):
    t0 = time.perf_counter()
    ok = ops.analyze(1, DT)
    lin.append(time.perf_counter() - t0)
    if ok != 0:
        print(f"  linear step {i+1} returned {ok}")
        break
print(f"\nLINEAR transient, {len(lin)} steps of {DT} s:")
print(f"  first step (includes the factorisation): {lin[0]:.3f} s")
if len(lin) > 1:
    rest = lin[1:]
    print(f"  later steps: mean {np.mean(rest):.3f} s, "
          f"min {min(rest):.3f} s, max {max(rest):.3f} s")

# --- 3. transient refactoring every step (what nonlinearity costs) -------
# Newmark's effective stiffness changes whenever dt changes, which forces a
# refactorisation - the same work a nonlinear material or a contact
# interface imposes on every iteration, without needing either to be set
# up. This isolates the cost of ONE factorisation inside a transient.
ops.wipeAnalysis()
ops.system("UmfPack")
ops.numberer("RCM")
ops.constraints("Transformation")
ops.test("NormDispIncr", 1e-6, 10, 0)
ops.algorithm("Linear")
ops.integrator("Newmark", 0.5, 0.25)
ops.analysis("Transient")
refac = []
for i in range(max(3, N_STEPS // 2)):
    dt_i = DT * (1.0 + 0.001 * (i + 1))    # perturb dt -> new K_eff -> refactor
    t0 = time.perf_counter()
    ok = ops.analyze(1, dt_i)
    refac.append(time.perf_counter() - t0)
    if ok != 0:
        print(f"  refactor step {i+1} returned {ok}")
        break
print(f"\nREFACTORING transient, {len(refac)} steps:")
print(f"  mean {np.mean(refac):.3f} s, min {min(refac):.3f} s, "
      f"max {max(refac):.3f} s")

# --- extrapolation --------------------------------------------------------
t_fact = float(np.mean(refac))
t_back = float(np.mean(lin[1:])) if len(lin) > 1 else float(lin[0])
print(f"\n{'='*68}")
print(f"measured: back-substitution {t_back:.3f} s/step, "
      f"factorisation {t_fact:.3f} s/step")
print(f"{'='*68}")
for label, seconds, n_iter in (("linear, 20 s record", 20.0, 0),
                               ("nonlinear, 20 s record, 4 iter/step", 20.0, 4),
                               ("nonlinear, 20 s record, 8 iter/step", 20.0, 8)):
    steps = int(seconds / DT)
    cost = steps * (t_back if n_iter == 0 else n_iter * t_fact)
    print(f"  {label:42s} {steps:6d} steps -> {cost/3600:8.2f} h")
print(f"\ntotal benchmark wall time: {time.perf_counter() - t_all:.1f} s")
gmsh.finalize()
