# Architecture and repository map

This is the map produced at the start of this pipeline's interface
detection, parallel export, and Docker image work, following the
usual discipline of reading a codebase and sketching its shape before
adding to it. Kept here rather than only in a commit message so it
doesn't get lost.

## Pipeline stages and where they live

```{list-table}
:header-rows: 1

* - Stage
  - Module
  - Status
* - IFC parsing, geometry -> STEP, material extraction
  - `core/ifc_processing/` (`data_extractor.py`, `geometry_extractor.py`)
  - existing, reused as-is
* - Masonry material characterisation from survey data (no IFC psets)
  - `core/ifc_processing/hmo_mqi.py`
  - new — see {doc}`materials_hmo_mqi`
* - Meshing, wall-to-wall interface detection/selection/node-split
  - `core/mesh_generation/` (`mesh.py` existing; `wall_interfaces.py`, `connections.py` new)
  - new — see {doc}`interface_detection`
* - OpenSees element/model creation
  - `core/opensees_generation/model_builder.py`
  - existing, extended for parallel export — see below
* - TCL export for OpenSeesMP
  - `core/opensees_generation/tcl_export.py`
  - new — see {doc}`parallel_export`
* - Earlier gmsh -> OpenSees bridge
  - `external/gmsh2opensees/`
  - kept for reference, not used by the interface-detection/parallel-export path
* - Constitutive-law helper formulas
  - `models/damage_law.py`, `models/masonry_cube_compression.py`
  - existing
* - Shared helpers
  - `utils/` (`dict_helper.py`, `gmsh_helpers.py`, `math_helpers.py`, `string_helpers.py`, `tag_manager.py`)
  - mixed
* - Docker image (OpenSeesMP + MPI + MUMPS)
  - `docker/opensees/`
  - new — see {doc}`docker_image_build`
```

`core/config.py` sits underneath all of these: import-time IfcOpenShell/
OpenCASCADE settings, the `G` gravity constant, `STEP_UNIT`, `EXPORT_DIR`.

## Entry points

- **`main.py`**, **`in_plane_wall.py`**, **`out_of_plane_test.py`** — earlier,
  single-material serial-workflow scripts, correspond to published
  results. Per the brief's working conventions (§9), these must keep
  working; they were not rewritten, only (in
  `in_plane_wall.py`/`out_of_plane_test.py`'s case) unblocked where they
  called a function — `utils.dict_helper.load_material_objects` — that was
  imported but never implemented. See {doc}`known_issues` for what in those
  two scripts is still broken independently of that fix.
- **`docker/opensees/*.py`** — the interface-detection/parallel-export
  entry points and their standing regression tests (see below).
- **`docker/opensees/castelnuovo_hmo_graph.py`** — the material
  characterisation entry point (§7 in the case study).

## The `Material` database shape

`core/ifc_processing/data_extractor.py`'s `Material` class is the schema
every downstream stage consumes, regardless of whether it was populated
from IFC psets (`Material.create_material_database`) or from a JSON file
(`utils.dict_helper.load_material_objects`, added for the survey-data
route — both produce `{name: Material}`):

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

## What's still wired to the earlier serial workflow

- `external/gmsh2opensees/` — the STKO-era bridge, untouched, not on the
  interface-detection/parallel-export path.
- `main.py`/`in_plane_wall.py`/`out_of_plane_test.py` — still call
  `Element.add_elements_to_opensees` with `node_substitution=None`
  (backward-compatible default), i.e. no wall-to-wall interface splitting;
  they were never meant to exercise interface detection.
- `models/damage_law.py` / `masonry_cube_compression.py` — calibration
  helpers used to derive `ASDConcrete3D` parameters for a single specimen
  (the single-specimen calibration workflow), independent of the
  survey-data route in {doc}`materials_hmo_mqi`.

## Units — the one rule that matters most

The whole pipeline, after the fix described in {doc}`known_issues`, works
in **consistent SI units**: metres, Pascals, kilograms, Newtons,
seconds. This matches `core/config.py`'s `STEP_UNIT = 'M'` and the node
coordinates Gmsh/apeGmsh produce from the STEP geometry. It does **not**
match the SERA-AIMS reference STKO model's own material table, which is
in N-mm-t (because that model's mesh was built at millimetre scale) —
when comparing a Castelnuovo material value against that table, convert
first; do not copy a number across without checking its unit.
