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

## Still open

- **`in_plane_wall.py`/`out_of_plane_test.py`** — still missing
  `EXPORT_DIR_PART_1/2/3`, `OUTPUT_DIR`, `LOG_DIR` config constants, and
  `utils/plot_helper.py`/`utils/modelbuilder_helper.py` modules they
  import. `load_material_objects` being implemented (see
  {doc}`materials_hmo_mqi`) unblocks their import error, not these.
- **`core/opensees_generation/analysis_run.py`** — wrong import,
  `models.masonry_law` (the actual module is `models.damage_law`).
- **`core/opensees_generation/cyclic_test.py`** — imports `pd` (pandas)
  from `core.config`, which doesn't define or re-export it.
- **`requirements.txt`** — lists only `gmsh`, `openseespy`, `lark`; missing
  `ifcopenshell`, `pythonocc-core`, `numpy`, `pandas`, `matplotlib`, all of
  which `core/config.py` imports at module load time. See
  {doc}`../user_guide/installation`.
- **`core/mesh_generation/mesh.py`** defaults to `setOrder(2)` (quadratic
  tetrahedra), but the Task A/B/C pipeline uses `FourNodeTetrahedron`
  (linear Tet4, per PROJECT_BRIEF.md §4.1 — Tet10 was explicitly rejected
  on cost grounds). Not reconciled — a caller that doesn't override the
  order explicitly (as the Task A/B/C test scripts do, via
  `gmsh.model.mesh.setOrder(1)`) would mesh quadratically and then feed a
  Tet4 element creator element connectivity it doesn't expect.

## Documented separately

Materials/ontology-specific open items (Type D classification, Poisson
ratio as a literature default, no Mohr-Coulomb rule in HMO, HSTO
unit-adjacency inferred rather than IFC-verified, limited
`HistoricOpening` inventory) live in
{doc}`../case_study/open_questions`, next to the data they qualify.
