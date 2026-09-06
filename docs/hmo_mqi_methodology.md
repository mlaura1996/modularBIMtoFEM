# Deriving masonry mechanical properties from survey data: HMO/MQI

Addresses PROJECT_BRIEF.md section 8, open question 1 ("Material
parameters for Castelnuovo... what does the IFC material database
actually contain for this building?"). Documents the method, the code,
and the Castelnuovo worked example together, so the three stay in sync.

## 1. Why this exists

`core/ifc_processing/data_extractor.py`'s `Material` class expects every
`IfcMaterial` to carry `Pset_MaterialCommon` / `Pset_MaterialMechanical`
property sets with the mechanical parameters already filled in. Castelnuovo's
IFC file has four masonry materials (`Tufelli_masonry_typeA` through `typeD`)
with **no mechanical properties attached at all** - confirmed directly by
opening the file:

```python
import ifcopenshell, ifcopenshell.util.element as ue
f = ifcopenshell.open("resources/ifc_examples/castelnuovo/final_example.ifc")
[ue.get_psets(m) for m in f.by_type("IfcMaterial")]  # -> all empty dicts for the 4 tufelli types
```

The thesis's own methodology (Chapter 3/4, the Historic Masonry Ontology)
is built for exactly this gap: derive mechanical properties from
morphological survey observations via the **Masonry Quality Index (MQI)**,
a method from Borri et al. formalised as SWRL rules in HMO
(https://w3id.org/hmo, published at
github.com/mlaura1996/HistoricMasonryOntology). This document and the code
under `core/ifc_processing/hmo_mqi.py` are that pipeline stage for
Castelnuovo, run once outside the automated pipeline (survey classification
is a judgement call, not something to re-run per pipeline execution) and
persisted as `resources/survey_data/castelnuovo/masonry_classification.json`
+ `output/castelnuovo/material_database.json`.

## 2. Where the rules came from

**Not** from the thesis prose, which works one example (unit-dimensions
parameter, shear-modulus formula) end to end and leaves the rest as "the
full set is available in the online documentation." **Not** from the
published documentation page (`mlaura1996.github.io/HistoricMasonryOntology`)
either - that page lists all 35 SWRL rule *names* but not their thresholds
or coefficients, by its own admission ("does not contain the actual rule
definitions or threshold tables").

The actual source is the ontology's Turtle serialisation itself:
`github.com/mlaura1996/HistoricMasonryOntology/blob/main/ontology.ttl`
(412 KB, downloaded and read directly). Every SWRL rule is encoded as RDF
(`swrl:Imp` individuals with `swrl:body`/`swrl:head` atom lists), which is
verbose but has an `rdfs:comment` on every rule stating its logic in plain
English, and the rule bodies themselves carry the exact numeric literals.
Both were read directly - the comments to build the score tables in
`hmo_mqi.py`, the numeric literals in the rule bodies to verify the four
mechanical-property formulas below.

## 3. The Masonry Quality Index

MQI scores a masonry wall on 7 parameters, each 0-3 depending on the
parameter, in three load directions (vertical, out-of-plane, in-plane) -
see `core/ifc_processing/hmo_mqi.py`'s `UNIT_DIMENSIONS` / `UNIT_SHAPE` /
`UNIT_MATERIAL` / `MORTAR_QUALITY` / `HORIZONTAL_JOINTS` / `VERTICAL_JOINTS`
/ `WALL_CONNECTIONS` dicts for the complete, exact score tables (category
name -> `(vertical, out_of_plane, in_plane)` tuple), transcribed from the
rule comments.

The three directional totals combine six of the seven parameters
additively and the seventh (unit material quality) multiplicatively -
confirmed from the `MQI_InPlane` rule body, not assumed from the pattern
of the other six:

```
MQI_dir = (HorizontalJoints + VerticalJoints + MortarQuality + UnitShape
           + WallConnections + UnitDimensions)_dir  *  UnitMaterial_dir
```

## 4. From MQI to mechanical properties

Four SWRL rules (`ShearModulusMQI`, `ShearStrengthMQI`,
`CompressiveStrenghMQI` [sic - the ontology's own typo], `YoungModulusMQI`)
derive homogenised properties from the totals. G and shear strength use
`MQITotalInPlane`; compressive strength and E use `MQITotalVertical` - this
split is in the ontology, not introduced here.

| Property | Formula | Uses |
|---|---|---|
| Shear modulus G | `279.82 * 2.72^(0.1298 * MQI)` | in-plane total |
| Shear strength (Turnšek-Čačovič) τ0 | `0.0192 + 0.0005*MQI² + 0.0074*MQI` | in-plane total |
| Compressive strength fm | `1.6841 * 2.72^(0.1572 * MQI)` | vertical total |
| Young's modulus E | `814.06 * 2.72^(0.1381 * MQI)` | vertical total |

**Two real gaps in the ontology, found by looking for the rules rather
than assuming they exist:**
- No SWRL rule derives **mass density** - it's a material physical
  constant, not a workmanship-quality output, so it has to come from
  elsewhere (literature value for the specific stone/brick, or direct
  measurement).
- No SWRL rule derives the **Mohr-Coulomb shear strength**, even though
  HMO defines the class for it (`hmo:ShearStrengthMohrCoulomb`). Only the
  Turnšek-Čačovič criterion is implemented. `hmo_mqi.py` returns `None`
  for this rather than inventing a formula.

## 5. The code: `core/ifc_processing/hmo_mqi.py`

Generic, reusable, has no Castelnuovo-specific content. Three pieces:

- The seven score-table dicts (Section 3).
- `MasonryObservation` - a dataclass holding one masonry type's 7
  parameters as *category names* (`unit_shape="cut_or_squared"`), not raw
  numbers, so a classification stays legible without cross-referencing the
  tables.
- `mqi_total()`, `mechanical_properties()`, `evaluate()` - the formulas
  from Sections 3-4.

Classifying an actual masonry (which category each parameter falls into,
for a specific wall) is deliberately **not** this module's job - that's a
survey judgement call, kept in per-case-study data files instead (Section
6), so the reasoning behind a classification travels with the data, not
buried in code.

## 6. Castelnuovo worked example

### 6.1 Inputs consulted

- **Manuscript** (`Downloads/Manuscript (3).docx`) - the case-study section
  gives the historical/technical context: the aggregate sits in the
  "second ring of minor dwellings... between Piazza Garibaldi and Via
  Umberto I" (confirmed against a cadastral map excerpt showing parcels
  363/364/367/417-420), local technique is *muratura a tufelli* (small
  lithoid tuff units, thin lime-pozzolana joints, coursing regularity and
  joint finish as the key quality discriminators between phases), and -
  important for calibrating scores conservatively - this specific
  residential fabric is explicitly described as **lower quality** than the
  representative architecture the general technique description is based
  on ("more frequent use of reused bricks, and greater variability in
  coursing and joint execution").
- **On-site survey photos**, 2023-06-01 (`Downloads/A-417/418/419/420`
  zips, WhatsApp images, organised by parcel/facade). Reviewed a
  representative sample per facade rather than every photo.
- **Reference typology text** (`Downloads/libro.zip`, 209 photographed
  pages of a masonry-restoration manual citing Carbonara, with comparison
  tables for tufo litoide masonry types in the Roman area) - used to
  cross-check terminology (bozzette/blocchetti/blocchi unit-shape
  categories, coursing description) against what the photos show, not
  transcribed in full.
- **NTC18 Circolare n.7/2019, Tabella C8.5.I** (tufo/calcarenite rows) -
  used as a plausibility range for the MQI-derived values, not as their
  source. HMO's own stated logic (thesis text) is that code-tabulated
  values are used *only* when a masonry matches a code category exactly;
  otherwise MQI infers project-specific values, which can legitimately
  exceed a generic table for masonry executed better than the code's
  baseline assumption.

### 6.2 The four types

Full classification, with photo/manuscript citations and every judgement
call flagged, is in
`resources/survey_data/castelnuovo/masonry_classification.json`. Summary:

| Type | Character | Key evidence |
|---|---|---|
| A | Regular coursing, well-cut stone voussoirs at openings | `A-419/a419` photos: door arch with dressed voussoirs |
| B | Irregular coursing, brick relieving arches, squared quoins | `A-417/417_c` (corner building), `A-418/418-a` (brick arch) |
| C | Patched/reworked, mixed exposed stone and infill, brick dentil cornice | `A-417/417_a` |
| D | Fully rendered - masonry not observable | `A-417/417_b`, `A-420` - **scored by analogy to type B**, the weakest-grounded of the four; revisit if render is ever removed |

**First pass vs. final pass.** The first classification credited the
lime-pozzolana mortar at hydraulic-lime quality and assumed "properly
staggered" vertical joints for type A (plausible for well-coursed masonry,
but not directly observable in the photos). That pass produced
compressive strength and Young's modulus 20-58% above the NTC C8.5.I tufo
range for types A, B and D. Per explicit direction, the mortar assumption
was walked back to plain "lime" (the pozzolana's real contribution wasn't
tested, only described) and type A's joint staggering to "partially
staggered," for all four types. Final results:

| Type | MQI (v / oop / ip) | fm (MPa) | E (MPa) | G (MPa) | τ0 (MPa) | vs. NTC tufo range |
|---|---|---|---|---|---|---|
| A | 4.55 / 4.90 / 3.50 | 3.445 | 1526.6 | 440.9 | 0.0512 | fm ~10% above upper bound; E, G, τ0 inside |
| B | 2.80 / 3.50 / 2.45 | 2.616 | 1198.7 | 384.7 | 0.0403 | fm ~21% above upper bound; E, G, τ0 inside (τ0 at top) |
| C | 1.40 / 1.40 / 1.05 | 2.099 | 987.8 | 320.7 | 0.0275 | **fully inside** the NTC irregular-tufo range |
| D | = B (by construction) | 2.616 | 1198.7 | 384.7 | 0.0403 | = B |

Types A and B still exceed the NTC compressive-strength upper bound by a
residual 10-21% after the conservative revision. Accepted rather than
tuned further to force a match - see the `ntc_comparison.note` field per
type in the classification JSON for the specific reasoning (type A's
voussoir-quality stonework at openings is observed evidence, not an
assumption, so some excess over a generic code table is expected for that
specific type). Type B's larger residual gap is flagged as the one worth
revisiting first if better evidence turns up (e.g. point-cloud-measured
unit dimensions smaller than the "medium" (20-40 cm) category assumed
here).

Mass density (no MQI rule - Section 4): taken as 1450 kg/m³, the midpoint
of NTC18's tufo/calcarenite range (1300-1600 kg/m³), for all four types.
Not measured on this building specifically.

### 6.3 Reproducing this

```bash
docker run --rm -v "$(pwd):/app" --entrypoint sh modularbimtofem-opensees-mp:dev \
    -c "conda run -n appenv python docker/opensees/castelnuovo_hmo_graph.py"
```

Reads `resources/survey_data/castelnuovo/masonry_classification.json`, runs
each type through `hmo_mqi.py`, and writes:

- `output/castelnuovo/hmo_graph.ttl` - RDF/Turtle graph instantiating HSV
  (survey-document provenance), HSTO (structural decomposition), and HMO
  (masonry characterisation) individuals for the four types. Hand-written
  Turtle (no `rdflib` in the Docker image) rather than a dependency for
  something this straightforward. HSTO classes/properties
  (`hsto:StructuralPart`, `hsto:Facade`, `hsto:Quoin`, `hsto:TimberFloor`,
  `hsto:HistoricOpening`, `hsto:isMadeOf`, `hsto:isConnectedTo`,
  `hsto:hasHistoricOpening`) were verified against
  `github.com/mlaura1996/Historic-Structure-Ontology/blob/main/ontology.ttl`
  (375 lines, read in full - much shorter than HMO's) the same way HMO's
  were. One real finding from reading it: **HSTO has no object property
  linking a `hsto:StructuralPart` to the `hsto:Facade`/
  `hsto:HorizontalStructure` instances that decompose it** - composition
  is presumably left to BEO/IFC spatial containment rather than duplicated
  in HSTO. `castelnuovo_hmo_graph.py`'s `hsto_ttl()` records that
  relationship as an `rdfs:comment` instead of forcing it through a
  property with the wrong domain/range, which would silently produce an
  invalid graph. Four structural units (417-420, from the survey photo
  subfolders) each get their facades, one generic `hsto:TimberFloor`
  ("timber floors alla romana" per the manuscript, not surveyed per unit),
  and `hsto:Quoin` connections to their row-neighbours (manuscript: "quoined
  corners indicating originally detached buildings that were later
  physically and structurally joined" - the *existence* of quoins is
  documentary evidence, but which specific unit pairs is inferred from the
  cadastral-map row order the user shared, not confirmed on site or
  against the IFC model's own geometry). One `hsto:HistoricOpening` is
  recorded (the dressed-stone door arch on `Facade_419`).
- `output/castelnuovo/material_database.json` - flat JSON, field-compatible
  with `core.ifc_processing.data_extractor.Material` (same field names:
  `density`, `young_modulus`, `poisson_ratio`, `compressive_strength`, ...),
  keyed by the same material names the IFC file uses
  (`Tufelli_masonry_typeA` etc.), so it merges into that pipeline's
  `material_db` without a translation step. `tensile_strength` is left
  `null` (no HMO rule for it, not invented); `compression_fracture_energy`
  / `tensile_fracture_energy` are left at `0`, which is not a silent gap -
  `model_builder.py`'s `create_plastic_damage_elements` already falls back
  to `Gc = 15 + 0.43*fc - 0.0036*fc²` / `Gt = 0.025*(fc/10)^0.7` (Bažant)
  when a material's own values are `0`, so leaving them at `0` activates an
  existing, deliberate fallback rather than leaving a real gap unhandled.

## 7. Visualising the graph

**The ontologies themselves** (HMO, HSTO - the TBox, i.e. the classes and
properties, not this case study's individuals) can be viewed interactively
without any local setup: both ontology repositories bundle a WebVOWL
instance, already deployed via GitHub Pages, pre-loaded with the
co-located ontology (`webvowl/data/ontology.json`, generated by Widoco at
publication time):

- HMO: `mlaura1996.github.io/HistoricMasonryOntology/webvowl/`
- HSTO: `mlaura1996.github.io/Historic-Structure-Ontology/webvowl/`

Open either URL directly in a browser; it should auto-load the ontology
(nodes = classes, edges = object properties, hover for `rdfs:comment`
definitions). If it comes up empty ("Drag ontology file here"), drag the
repository's own `ontology.owl` onto the page.

**This case study's instance graph** (`output/castelnuovo/hmo_graph.ttl` -
the ABox, the four masonry types / structural units / quoins / etc. as
individuals) is not what WebVOWL is for (it visualises ontology schemas,
not arbitrary instance data) and isn't hosted anywhere. To view it:
convert to WebVOWL's JSON format with the standalone
[VOWL converter](https://github.com/VisualDataWeb/OWL2VOWL) and drop the
result onto either WebVOWL instance above, or - simpler for instance data
specifically - load the `.ttl` file into
[GraphDB](https://www.ontotext.com/products/graphdb/) (free tier) or a
local [Apache Jena Fuseki](https://jena.apache.org/documentation/fuseki2/)
and use their built-in graph browsers, which are built for exploring
individuals and their relationships (WebVOWL is built for exploring class
hierarchies).

## 8. Feeding this into the modularBIMtoFEM pipeline

`in_plane_wall.py` and `out_of_plane_test.py` already import and call
`utils.dict_helper.load_material_objects(material_file_path)` - but that
function had never actually been implemented (confirmed: `dict_helper.py`
only had `filter_materials_by_name` before this work), so neither script
could have run. Implemented now, as the natural counterpart to
`data_extractor.py`'s `Material.create_material_database` (same output
shape, `{name: Material}`, built from a JSON file instead of IFC psets):

```python
from utils.dict_helper import load_material_objects
materials = load_material_objects("output/castelnuovo/material_database.json")
# -> {"Tufelli_masonry_typeA": Material(...), "Tufelli_masonry_typeB": Material(...), ...}
```

Verified against the actual file this pipeline stage produces (Docker
image, see chat log) - loads all four types correctly, `tensile_strength`
coerced from JSON `null` to `0` (matching how the rest of the codebase
already treats an absent numeric property, e.g.
`Material.assign_material_tags`'s `info.get('thickness', 0) or 0`), and
the loaded `Material.__repr__` output confirmed field-for-field against
what `castelnuovo_hmo_graph.py` wrote.

**Not yet wired further than that.** `load_material_objects` produces a
`materials_dict` in the exact shape
`core.opensees_generation.model_builder.Element.add_elements_to_opensees`
already expects as its second argument - so
`in_plane_wall.py`/`out_of_plane_test.py` should now get past their import
error, but those two scripts have their own other issues (missing
`EXPORT_DIR_PART_*` config constants, missing `utils.plot_helper` /
`utils.modelbuilder_helper` modules - see the repo-map chat log from
earlier in this session) that are unrelated to this fix and weren't
addressed here.

## 9. What's still open

- Type D's classification is unverified by construction - see 6.2.
- `poisson_ratio = 0.2` for all four types is a literature default, not
  MQI-derived (HMO has no rule for it either).
- Mohr-Coulomb shear strength (needed if the brief's contact-interface
  friction model, section 4.2, is meant to use a masonry-specific friction
  angle rather than the generic μ=0.6 - currently unrelated parameters)
  has no source in HMO at all yet.
- The HSTO graph's unit-adjacency order (which quoin connects which pair
  of units) is inferred from a cadastral-map excerpt, not checked against
  the IFC model's own geometry - `core.mesh_generation.wall_interfaces`
  (Task A) does that check independently, on the actual STEP geometry, and
  the two have not been cross-referenced against each other.
- HSTO's `HistoricOpening` inventory here is one individual (the type-A
  door arch); the manuscript describes several other opening types
  (four-light 15th-century windows, later brick-surrounded rectangular
  apertures) that were not individually catalogued.
