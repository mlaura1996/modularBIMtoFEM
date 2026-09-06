# Known issues

Kept as a single, honest list so nothing found during development gets
lost between a chat log and a commit message. Split into fixed (with the
fix verified, not just applied) and still open.

## Fixed

### Units mismatch in `create_plastic_damage_elements` (ASDConcrete3D)

**The bug.** `Element.create_plastic_damage_elements`
(`core/opensees_generation/model_builder.py`) was calibrated for an
N-mm-t unit system (matching PROJECT_BRIEF.md §4.1's own reference table,
which documents the *Chapter 6* STKO model — built at millimetre scale)
while every node coordinate reaching it, from `apeGmsh`/Gmsh via the STEP
geometry, is in **metres** (`core/config.py`'s `STEP_UNIT = 'M'`). `E`,
`fc`, `ft` stayed in MPa and density was converted to t/mm³, but geometry
was metre-scale — a silent unit mismatch, not a crash, so a model would
run and converge to a physically meaningless result without any error.

**The fix.** Rewrote to consistent SI throughout (Pa, m, kg, N). The Gc/Gt
fallback formulas (Bažant/CEB-FIP Model Code 90, used when a material
doesn't supply its own fracture energy) are documented in the literature
in N/mm — verified this by checking their output against
PROJECT_BRIEF.md's own §4.1 reference values (Gt: 0.0060 vs. the brief's
0.006 N/mm, exact match at `fc = 1.30 MPa`), then converted N/mm → N/m
(`× 1000`) once, explicitly, rather than trusting the formula's unit by
assumption.

**Verified**, not just applied: `docker/opensees/test_plastic_damage_units.py`
runs Castelnuovo's actual `Tufelli_masonry_typeA` properties (from
`material_database.json`) through a real self-weight static analysis on a
real touching volume pair, and checks the converged displacement lands in
a physically plausible range (a pre-fix, still-mixed-units version would
be off by many orders of magnitude in one direction or the other).

### Degenerate tension-softening curve when `tensile_strength = 0`

**The bug.** HMO has no SWRL rule for tensile strength at all (a real gap
in the ontology, not a bug in the code reading it — see
{doc}`materials_hmo_mqi`). `tensile_strength` was left `null` in the
material JSON, and `load_material_objects` coerces JSON `null` to `0` for
numeric fields. Traced what `ft = 0` actually does downstream (not just
inspected): `create_plastic_damage_elements` passes it into
`ConstitutiveLaws.ExponentialSoftening_Tension.tension(E, ft, Gt,
side_length)`, whose own convergence check (`if stress > s0*0.05`) is
`0 > 0` — false on the very first iteration — so it silently returns a
degenerate two-point curve (`Te=[0,0.0], Ts=[0,0], Td=[0,0]`) instead of an
actual softening branch, fed straight into `nDMaterial ASDConcrete3D`.
"Not derived by HMO" was silently becoming "asserted zero tensile
strength," and the code had no way to distinguish the two.

**The fix.** `tensile_strength = compressive_strength * (0.17 / 1.30)` —
the ft/fc ratio of PROJECT_BRIEF.md's own Chapter 6 (SERA-AIMS) reference
masonry, the closest documented precedent available, not a masonry-science
formula (recorded as such in the JSON, not hidden).

**Verified**: re-ran the same tension-curve call and confirmed it now
returns a real 21001-point exponential softening curve instead of the
two-point degenerate one.

### `analysis_run.py` wrong import and wrong method name

Imported `models.masonry_law` (module doesn't exist; the real module is
`models.damage_law`) and called `BoundaryConditions.fixNodes(gmshmodel)`
(the actual method, in `model_builder.py`, is `fix_nodes`, snake_case).
Both fixed. **Verified**: `import core.opensees_generation.analysis_run`
now succeeds inside the Docker image (it previously raised
`ModuleNotFoundError` at the first line).

### `cyclic_test.py` importing `pd` from `core.config`

`core/config.py` never actually imported `pandas`, only `numpy` and
`matplotlib.pyplot` — so `from core.config import ... pd ...` raised
`ImportError`. Added `import pandas as pd` (and `import csv`, needed by
the same import line and by `in_plane_wall.py`/`out_of_plane_test.py`) to
`core/config.py`. **Verified**: the script now gets past the import and
fails only on its actual runtime input, a `CT02_estimated_time_series.csv`
file expected in the working directory (a separate, pre-existing
data-availability question, not an import bug).

### `requirements.txt` incomplete

Added `ifcopenshell`, `numpy`, `pandas`, `matplotlib` (all imported by
`core/config.py` at module load time, none previously listed). Left
`pythonocc-core` out deliberately — not reliably pip-installable on
Windows, which is why the Docker image installs it via `conda` instead
(see {doc}`../user_guide/installation`, unchanged advice).

### `mesh.py` hard-coded quadratic mesh order

`GmshModel.createGmshModel` (used by `main.py`) called
`gmsh.model.mesh.setOrder(2)` unconditionally. Every element creator in
`model_builder.py`'s `Element` class (`create_linear_elastic_element` and
`create_plastic_damage_elements`) unpacks `node_tags` directly into an
OpenSees `element('FourNodeTetrahedron', ...)` call, which requires
exactly 4 nodes — order 2 hands it 10-node Tet10 connectivity instead,
which fails at that `element()` call. Changed to `setOrder(1)`, matching
every actual element consumer in the repository (there is no code path
anywhere that handles Tet10 connectivity) and PROJECT_BRIEF.md §4.1's own
choice of Tet4 for this pipeline.

### `EXPORT_DIR_PART_1/2/3`, `OUTPUT_DIR`, `LOG_DIR` — now defined

Added to `core/config.py`. `EXPORT_DIR_PART_1`/`_2` weren't guessed: they
match where `out_of_plane_test.py`'s own real inputs already sat on disk
(`export/ifc_data/CMB_unreinforced_adapted_E.json`,
`export/mesh/out_of_plane.msh` — both predate this fix, evidence of the
intended convention, not an assumption). `OUTPUT_DIR = "output/"` matches
an existing `output/CMB_acceptable/` folder whose contents (`pushover_curve.csv`,
`results_SW.csv`, ...) are exactly what these two scripts produce —
meaning a version of this script *did* run successfully at some point.
`EXPORT_DIR_PART_3` and `LOG_DIR` are imported by both scripts but never
referenced in either script's body, so their values only had to be
plausible, not verified against real data.

This unblocks the import line in both scripts, but does **not** make them
runnable — see the next entry.

## Still open

- **`in_plane_wall.py`/`out_of_plane_test.py` are missing more than config
  constants.** Past the (now fixed) import line, both scripts depend on
  functions that were never implemented anywhere in the repository (not
  just unimported — grepped the full codebase, they don't exist):
  `utils/plot_helper.py`'s `LiveDVPlot` (imported by both, not actually
  called in either script's visible body); `utils/modelbuilder_helper.py`'s
  `get_wall_cp` (in-plane script, actively used to pick the pushover
  control node), `get_group_center_cp` (out-of-plane script, same role),
  `TagManager` (re-import target only — the real class already exists at
  `utils/tag_manager.py`), and `add_base_springs_elastic_tm` (imported,
  not called); `utils/analysis_helper.py`'s `check_sign_flips` (actively
  used) and `PeakViews` (imported, not called); and
  `external/gmsh2opensees/g2o_viz.py`'s
  `compute_and_visualize_principal_strains`/`_stresses` (actively used, in
  the pushover loop of both scripts). `check_sign_flips`/`PeakViews`/the
  two `compute_and_visualize_*` functions weren't on the original version
  of this list — found while trying to actually fix it, not previously
  reported.

  The two genuinely load-bearing gaps are `get_wall_cp`/`get_group_center_cp`
  (control-point selection — an engineering choice, e.g. "highest node,"
  "closest to a target coordinate," that affects what the resulting
  pushover curve means) and `check_sign_flips`/the principal stress/strain
  visualizers, where a plausible-looking but wrong implementation would be
  worse than an ImportError: it would produce a curve or a stress plot that
  runs cleanly and looks reasonable without actually being correct.
  Deliberately not guessed at.

  **Deprioritised, on request**: these are Chapter 6 SERA-AIMS specimen
  scripts, not part of this chapter's Castelnuovo case study. Left
  documented as "not yet runnable" rather than implemented with guessed
  engineering logic. Revisit if/when they're back in scope, ideally with
  either the original working version of these two functions or an
  explicit specification of the control-point selection rule.

## Documented separately

Materials/ontology-specific open items (Type D classification, Poisson
ratio as a literature default, no Mohr-Coulomb rule in HMO, HSTO
unit-adjacency inferred rather than IFC-verified, limited
`HistoricOpening` inventory) live in
{doc}`../case_study/open_questions`, next to the data they qualify.
