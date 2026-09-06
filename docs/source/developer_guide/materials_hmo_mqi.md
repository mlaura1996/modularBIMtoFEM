# Material characterisation from survey data (HMO/MQI)

Module: `core/ifc_processing/hmo_mqi.py`. Addresses PROJECT_BRIEF.md §8,
open question 1: Castelnuovo's IFC file has four masonry materials with no
mechanical properties attached at all (`Pset_MaterialCommon`/
`Pset_MaterialMechanical` are empty — confirmed by opening the file, not
assumed). This module is the pipeline stage that fills that gap using the
thesis's own methodology: the **Masonry Quality Index** (Borri et al.),
formalised as SWRL rules in the author's own **Historic Masonry Ontology**
(HMO, published at `w3id.org/hmo`).

For the Castelnuovo-specific classification and results, see
{doc}`../case_study/materials`. This page covers the reusable code only —
`hmo_mqi.py` has no Castelnuovo-specific content.

## Where the rules actually came from

Not the thesis prose (works one example end to end, defers the rest to
"the online documentation"). Not the published documentation site either —
it lists all 35 SWRL rule *names* but explicitly does not contain their
thresholds. The real source is the ontology's own Turtle serialisation
(`github.com/mlaura1996/HistoricMasonryOntology/blob/main/ontology.ttl`,
412 KB, read directly): every SWRL rule carries an `rdfs:comment` stating
its logic in plain English, and the rule bodies carry the exact numeric
literals — both were read directly rather than trusting a secondary
description.

## The Masonry Quality Index

Seven parameters, each scored 0–3, in three load directions (vertical,
out-of-plane, in-plane):

```python
DIRECTIONS = ("vertical", "out_of_plane", "in_plane")
```

Score tables (`UNIT_DIMENSIONS`, `UNIT_SHAPE`, `UNIT_MATERIAL`,
`MORTAR_QUALITY`, `HORIZONTAL_JOINTS`, `VERTICAL_JOINTS`,
`WALL_CONNECTIONS`) — dicts of `category_name -> (vertical, out_of_plane,
in_plane)` — transcribed verbatim from the rule comments, not
re-derived. Six parameters combine additively, the seventh (unit material
quality) multiplicatively — confirmed from the `MQI_InPlane` rule body
directly, not assumed from the pattern of the other six:

```
MQI_dir = (HorizontalJoints + VerticalJoints + MortarQuality + UnitShape
           + WallConnections + UnitDimensions)_dir  *  UnitMaterial_dir
```

## From MQI to mechanical properties

Four SWRL rules. G and shear strength use `MQITotalInPlane`; compressive
strength and E use `MQITotalVertical` — this split is in the ontology, not
introduced here.

```{list-table}
:header-rows: 1

* - Property
  - Formula
  - Uses
* - Shear modulus G
  - `279.82 * 2.72^(0.1298 * MQI)`
  - in-plane total
* - Shear strength τ0 (Turnšek–Čačovič)
  - `0.0192 + 0.0005*MQI² + 0.0074*MQI`
  - in-plane total
* - Compressive strength fm
  - `1.6841 * 2.72^(0.1572 * MQI)`
  - vertical total
* - Young's modulus E
  - `814.06 * 2.72^(0.1381 * MQI)`
  - vertical total
```

**Two real gaps in the ontology, found by looking for the rules rather
than assuming they exist**, both returned as `None` by `hmo_mqi.py` rather
than invented:

- No SWRL rule derives **mass density** — a material physical constant,
  not a workmanship-quality output, so it must come from elsewhere
  (literature or measurement).
- No SWRL rule derives **Mohr-Coulomb shear strength**, even though HMO
  defines the class for it (`hmo:ShearStrengthMohrCoulomb`) — only the
  Turnšek-Čačovič criterion is actually implemented as a rule.

## API

- `MasonryObservation` — dataclass holding one masonry type's 7 parameters
  as *category names* (e.g. `unit_shape="cut_or_squared"`), not raw
  numbers, so a classification stays legible without cross-referencing the
  score tables.
- `mqi_total(observation, direction)` / `mechanical_properties(observation)`
  / `evaluate(observation)` — the formulas above.

Classifying an actual masonry (which category each of the 7 parameters
falls into, for a specific wall) is deliberately **not** this module's job
— a survey judgement call, kept in per-case-study data files instead (see
{doc}`../case_study/materials`), so the reasoning behind a classification
travels with the data, not buried in code.

## Feeding results into the pipeline

`output/castelnuovo/material_database.json` (written by
`docker/opensees/castelnuovo_hmo_graph.py`) is field-compatible with
`core.ifc_processing.data_extractor.Material` — same field names, same
`{name: Material}` output shape as `Material.create_material_database`.
`utils/dict_helper.py`'s `load_material_objects(json_path)` is the loader
(this function was imported and called by `in_plane_wall.py`/
`out_of_plane_test.py` already, but had never actually been implemented —
implemented now, as the JSON-backed counterpart to the IFC-backed
`create_material_database`).

```python
from utils.dict_helper import load_material_objects
materials = load_material_objects("output/castelnuovo/material_database.json")
# -> {"Tufelli_masonry_typeA": Material(...), ...}
```

`load_material_objects` coerces JSON `null` to `0` for numeric fields only
(matching how the rest of the codebase already treats an absent property).
This matters specifically for `compression_fracture_energy`/
`tensile_fracture_energy` — see {doc}`known_issues` for why leaving those
at `0` is a deliberate fallback, not a gap, and why `tensile_strength`
could **not** be left at `0`/`null` the same way.
