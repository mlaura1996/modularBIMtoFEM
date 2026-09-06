# Architecture and repository map

This is the map produced at the start of Chapter 7's work, per
PROJECT_BRIEF.md §3.1's own instruction ("read this repository and produce
a short map of it... nothing below should be implemented before that map
exists"). Kept here rather than only in a commit message so it doesn't get
lost.

## Pipeline stages and where they live

```{list-table}
:header-rows: 1

* - Stage
  - Module
  - Chapter
* - IFC parsing, geometry -> STEP, material extraction
  - `core/ifc_processing/` (`data_extractor.py`, `geometry_extractor.py`)
  - 4 (existing, reused as-is)
* - Masonry material characterisation from survey data (no IFC psets)
  - `core/ifc_processing/hmo_mqi.py`
  - 7 (new — see {doc}`materials_hmo_mqi`)
* - Meshing, wall-to-wall interface detection/selection/node-split
  - `core/mesh_generation/` (`mesh.py` existing; `wall_interfaces.py`, `connections.py` new)
  - 7 (new — see {doc}`task_a_interfaces`)
* - OpenSees element/model creation
  - `core/opensees_generation/model_builder.py`
  - 4 (existing, extended for Task B — see below)
* - TCL export for OpenSeesMP
  - `core/opensees_generation/tcl_export.py`
  - 7 (new — see {doc}`task_b_parallel`)
* - STKO-era gmsh -> OpenSees bridge
  - `external/gmsh2opensees/`
  - 4/6 (kept for reference, not used by the Task A/B/C path)
* - Constitutive-law helper formulas
  - `models/damage_law.py`, `models/masonry_cube_compression.py`
  - 5/6 (existing)
* - Shared helpers
  - `utils/` (`dict_helper.py`, `gmsh_helpers.py`, `math_helpers.py`, `string_helpers.py`, `tag_manager.py`)
  - mixed
* - Docker image (OpenSeesMP + MPI + MUMPS)
  - `docker/opensees/`
  - 7 (new — see {doc}`task_c_docker`)
```

`core/config.py` sits underneath all of these: import-time IfcOpenShell/
OpenCASCADE settings, the `G` gravity constant, `STEP_UNIT`, `EXPORT_DIR`.

## Entry points

- **`main.py`**, **`in_plane_wall.py`**, **`out_of_plane_test.py`** — Chapter
  4/6-era scripts, correspond to published results. Per the brief's working
  conventions (§9), these must keep working; they were not rewritten, only
  (in `in_plane_wall.py`/`out_of_plane_test.py`'s case) unblocked where they
  called a function — `utils.dict_helper.load_material_objects` — that was
  imported but never implemented. See {doc}`known_issues` for what in those
  two scripts is still broken independently of that fix.
- **`docker/opensees/*.py`** — the Task A/B/C entry points and their
  standing regression tests (see below).
- **`docker/opensees/castelnuovo_hmo_graph.py`** — the material
  characterisation entry point (§7 in the case study).

## The `Material` database shape

`core/ifc_processing/data_extractor.py`'s `Material` class is the schema
every downstream stage consumes, regardless of whether it was populated
from IFC psets (`Material.create_material_database`) or from a JSON file
(`utils.dict_helper.load_material_objects`, Task 7 addition — both produce
`{name: Material}`):

```python
Material(name, density, young_modulus, poisson_ratio, is_structural, material_model_type,
         compressive_strength=0, tensile_strength=0,
         compression_fracture_energy=0, tensile_fracture_energy=0,
         compressive_elastic_behaviour=0, ...)
```

`material_model_type` selects which `Element.create_*_elements` staticmethod
in `model_builder.py` builds the actual OpenSees element:
`"PlasticDamage"` → `create_plastic_damage_elements` (`nDMaterial
ASDConcrete3D` + `FourNodeTetrahedron`); anything else falls back to
`create_linear_elastic_element`.

## What's still wired to the Chapter 4 serial workflow

- `external/gmsh2opensees/` — the STKO-era bridge, untouched, not on the
  Task A/B/C path.
- `main.py`/`in_plane_wall.py`/`out_of_plane_test.py` — still call
  `Element.add_elements_to_opensees` with `node_substitution=None`
  (backward-compatible default), i.e. no wall-to-wall interface splitting;
  they were never meant to exercise Task A.
- `models/damage_law.py` / `masonry_cube_compression.py` — calibration
  helpers used to derive `ASDConcrete3D` parameters for a single specimen
  (Chapter 5/6 workflow), independent of the survey-data route in
  {doc}`materials_hmo_mqi`.

## Units — the one rule that matters most

The whole pipeline, after the fix described in {doc}`known_issues`, works
in **consistent SI units**: metres, Pascals, kilograms, Newtons,
seconds. This matches `core/config.py`'s `STEP_UNIT = 'M'` and the node
coordinates Gmsh/apeGmsh produce from the STEP geometry. It does **not**
match PROJECT_BRIEF.md §4.1's own reference table, which documents the
Chapter 6 STKO model in N-mm-t (because that model's mesh was built at
millimetre scale) — when comparing a Castelnuovo material value against
that table, convert first; do not copy a number across without checking
its unit.
