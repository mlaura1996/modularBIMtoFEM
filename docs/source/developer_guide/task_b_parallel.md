# Task B — parallel execution

Modules: `core/opensees_generation/tcl_export.py` (new), extensions to
`core/opensees_generation/model_builder.py`. Implements PROJECT_BRIEF.md
§6: `IFC → apeGmsh (mesh, partition) → Task A (interfaces) → TCL export →
OpenSeesMP -np N`.

## Why TCL, not OpenSeesPy

The brief records, and this project's own experience confirmed, that
OpenSeesPy in parallel does not work reliably — not something to spend
project time fighting. The route taken instead: `apeGmsh`'s
`g.opensees.export`-adjacent `FEMData` snapshot feeds a hand-written TCL
writer, and the resulting model file runs on `OpenSeesMP` directly (a
binary, not a Python binding). The brief also asks (§6) that the TCL stay
"legible to a reader, not machine-vomit," since it's a thesis artefact —
`TclWriter` is a plain sequence of `self.raw(...)` line-emitters per
concern (nodes, one material call, one partition's elements, duplicate
nodes, contact elements, boundary conditions, analysis commands), not a
templating engine, specifically so the emitted file reads like a model a
person would have written by hand.

## `TclWriter`

| Method | Emits |
|---|---|
| `header()` | `model BasicBuilder -ndm -ndf` |
| `nodes(fem)` | one `node` command per `FEMData` node |
| `material_linear_elastic(tag, E, nu, rho)` | `nDMaterial ElasticIsotropic` |
| `material_asdconcrete3d(tag, E, nu, Te, Ts, Td, Ce, Cs, Cd, lch, implex=True)` | `nDMaterial ASDConcrete3D` with the full Bézier/exponential curve data |
| `solid_elements(fem, pg_name, material_tag, rank, ...)` | `element FourNodeTetrahedron` for one partition, guarded by `if {$pid==rank+1}` |
| `duplicate_nodes(gmshmodel, selected)` | the split-side `node` commands (delegates the mapping to `NodeSplitter.compute_node_map`) |
| `contact_elements(fem, selected, Kn_nominal, Kt_nominal, mu, int_type)` | `element zeroLengthContactASDimplex` per split pair |
| `fix(fem, pg_name, dofs)` | `fix` commands for a physical group |
| `analysis_static_gravity(n_steps, tol, max_iter)` | `constraints`/`numberer ParallelRCM`/`system Mumps`/`test`/`algorithm`/`integrator`/`analysis`/`analyze` |
| `write(path)` | flushes the accumulated lines to a `.tcl` file |

`_node_partition_map(fem)` is a static helper used internally by
`solid_elements` and `contact_elements` to look up which partition owns a
given node.

## The rank / partition off-by-one

`apeGmsh`'s partition IDs are 1-based; OpenSeesMP's own `getPID()` is
0-based. `solid_elements`'s per-rank guard uses `partition=rank+1` to
translate between the two — easy to get backwards silently (every rank
would then own the *wrong* elements and the model would "run" while being
physically nonsensical), caught by checking partition membership against
`FEMData` directly rather than assuming the convention.

## Meshing note: `make_conformal()` vs. raw `fragment()`

`apeGmsh`'s `make_conformal()` broke meshing on the Castelnuovo geometry
(a Tetgen PLC error) and its default fragment tolerance (1.0) is calibrated
for millimetre-scale models — this pipeline works in metres, so that
tolerance is roughly 1000× too coarse for this geometry. Switched to raw
`gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])` instead, which
does the same conformal-interface job without either problem.

## Reconciling Task A and Task B

Task A's `InterfaceDetection`/`NodeSplitter` operate directly on
`gmsh.model` (the raw Gmsh Python API); Task B's `TclWriter` consumes
`FEMData` (apeGmsh's own snapshot). These are two different ID spaces in
principle. Confirmed directly (`probe_femdata_ids.py`, not a standing test
— a one-off check) that `FEMData` node/element IDs are identical to the
underlying Gmsh tags for this apeGmsh version, so no translation layer was
needed between the two Task's outputs. If apeGmsh's ID scheme ever changes,
this is the assumption to re-verify first — `TclWriter.duplicate_nodes`
and `.contact_elements` both call `NodeSplitter.compute_node_map` directly
with `gmsh.model`, relying on it matching `fem`'s own node numbering.

## Verified

`docker/opensees/test_task_ab_reconciled.py` and
`test_task_ab_scaled.py` are standing regression checks (kept in the
repository, not deleted after passing) proving, via a real `mpirun -np N
OpenSeesMP` run (not a mock):

- the same node-split mechanism proven for the direct-`openseespy` path
  (`test_node_split.py`) also decouples the two sides of a joint across
  the apeGmsh/TCL/partition path;
- every original/duplicate node pair shows independent, nonzero relative
  displacement after a converged self-weight analysis, checked
  independently on every MPI rank;
- scaled to a real 18-volume Castelnuovo cluster, multiple interfaces, and
  6 partitions (`test_task_ab_scaled.py`) — not just the 2-volume minimal
  case;
- the full 316-solid aggregate, bonded, with proper per-volume base
  fixity (`self_weight_check_full_aggregate.py`) — total volume matches
  PROJECT_BRIEF.md exactly, and an independent mass/weight balance check
  (`rho * g * V` vs. summed base reactions) agrees to within 0.027%.

## Visualising results headlessly (apeGmsh)

`apeGmsh`'s own `results.plot` (matplotlib-backed, no Qt/X11 needed) can
render a run's output directly inside the Docker container — the
interactive `results.viewer()` needs a display this container doesn't
have, but `results.plot.deformed(...)`/`.contour(...)` save static PNGs.
Two things to get right, both found by hitting them:

- **Recorders must be written per-rank, one file per rank, not one shared
  file requested unconditionally from every rank.** Multiple MPI
  processes racing to write the same file corrupts it — see
  {doc}`known_issues` for the exact failure mode and the fix
  (`self_weight_check_full_aggregate.py`'s recorder section).
- `Results.from_recorders(spec, output_dir, fem=fem)` expects recorder
  commands built from apeGmsh's own `Recorders`/`emit_spec_tcl` (or
  `ResolvedRecorderSpec.to_tcl_commands`) — not arbitrary hand-written
  `recorder` lines — so the transcoder can match files to components.
