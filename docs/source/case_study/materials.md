# Material characterisation

Addresses PROJECT_BRIEF.md §8, open question 1. For the reusable MQI code
and formulas, see {doc}`../developer_guide/materials_hmo_mqi`; this page is
the Castelnuovo-specific classification, its evidence, and the results.

## Inputs consulted

- **Manuscript** (case-study section) — historical/technical context: the
  aggregate's location (cross-checked against a cadastral map excerpt),
  local technique (*muratura a tufelli*), and — important for calibrating
  scores conservatively — an explicit statement that this specific
  residential fabric is **lower quality** than the representative
  architecture the general technique description is based on ("more
  frequent use of reused bricks, and greater variability in coursing and
  joint execution").
- **On-site survey photos**, organised by parcel/facade (417/418/419/420).
  A representative sample per facade was reviewed, not every photo.
- **Reference typology text** (a masonry-restoration manual citing
  Carbonara, comparison tables for tufo litoide masonry in the Roman area)
  — used to cross-check terminology (bozzette/blocchetti/blocchi
  unit-shape categories, coursing description) against what the photos
  show, not transcribed in full.
- **NTC18 Circolare n.7/2019, Tabella C8.5.I** (tufo/calcarenite rows) —
  used as a *plausibility range* for the MQI-derived values, not as their
  source. HMO's own logic: code-tabulated values are used only when a
  masonry matches a code category exactly; otherwise MQI infers
  project-specific values, which can legitimately exceed a generic table
  for masonry executed better than the code's baseline assumption.

## The four types

Full classification, with photo/manuscript citations and every judgement
call flagged explicitly, lives in
`resources/survey_data/castelnuovo/masonry_classification.json` — the
source of record; the table below is a summary.

```{list-table}
:header-rows: 1

* - Type
  - Character
  - Key evidence
* - A
  - Regular coursing, well-cut stone voussoirs at openings
  - Door arch with dressed voussoirs (facade 419)
* - B
  - Irregular coursing, brick relieving arches, squared quoins
  - Corner building (417); brick arch (418)
* - C
  - Patched/reworked, mixed exposed stone and infill, brick dentil cornice
  - Facade 417
* - D
  - Fully rendered — masonry not observable
  - Facades 417/420 — **scored by analogy to type B**, the weakest-grounded of the four
```

## First pass vs. final pass

The first classification credited the lime-pozzolana mortar at
hydraulic-lime quality and assumed "properly staggered" vertical joints for
type A — plausible for well-coursed masonry, but not directly observable
in the photos. That pass produced compressive strength and Young's modulus
**20–58% above** the NTC C8.5.I tufo range for types A, B and D.

Per explicit direction, walked back to a more conservative reading: plain
"lime" mortar (the pozzolana's real contribution was never tested, only
described) and type A's joint staggering downgraded to "partially
staggered," applied to all four types.

## Final results

```{list-table}
:header-rows: 1

* - Type
  - MQI (v / oop / ip)
  - fm (MPa)
  - E (MPa)
  - G (MPa)
  - τ0 (MPa)
  - vs. NTC tufo range
* - A
  - 4.55 / 4.90 / 3.50
  - 3.445
  - 1526.6
  - 440.9
  - 0.0512
  - fm ~10% above upper bound; E, G, τ0 inside
* - B
  - 2.80 / 3.50 / 2.45
  - 2.616
  - 1198.7
  - 384.7
  - 0.0403
  - fm ~21% above upper bound; E, G, τ0 inside (τ0 at top)
* - C
  - 1.40 / 1.40 / 1.05
  - 2.099
  - 987.8
  - 320.7
  - 0.0275
  - **fully inside** the NTC irregular-tufo range
* - D
  - = B (by construction)
  - 2.616
  - 1198.7
  - 384.7
  - 0.0403
  - = B
```

Types A and B still exceed the NTC compressive-strength upper bound by a
residual 10–21% after the conservative revision — accepted rather than
tuned further to force a match (see `ntc_comparison.note` per type in the
classification JSON for the specific reasoning; type A's voussoir-quality
stonework at openings is *observed* evidence, not an assumption, so some
excess over a generic code table is expected specifically for that type).
Type B's larger residual gap is flagged as the one worth revisiting first
if better evidence turns up — e.g. point-cloud-measured unit dimensions
smaller than the "medium" (20–40 cm) category assumed here.

**Mass density** (no MQI rule — see
{doc}`../developer_guide/materials_hmo_mqi`): 1450 kg/m³, the midpoint of
NTC18's tufo/calcarenite range (1300–1600 kg/m³), for all four types. Not
measured on this building specifically.

**Tensile strength**: HMO has no rule for it either.
`tensile_strength = compressive_strength × (0.17 / 1.30)` — the ft/fc ratio
of the brief's own Chapter 6 (SERA-AIMS) reference masonry. Current values:
type A 0.451 MPa, types B/D 0.342 MPa, type C 0.274 MPa. See
{doc}`../developer_guide/known_issues` for why this couldn't be left at 0.

**Shear strength** (Turnšek–Čačovič, computed above) is not a
`Material` field — ASDConcrete3D's shear behaviour emerges from the
triaxial damage-plasticity formulation, not an explicit input. Kept in the
JSON under `_shear_strength_turnsek_cacovic_MPa` for traceability, excluded
from the actual `Material()` object.

## HSTO instance graph

`docker/opensees/castelnuovo_hmo_graph.py` also writes
`output/castelnuovo/hmo_graph.ttl`: an RDF/Turtle graph instantiating HSV
(survey-document provenance), HSTO (structural decomposition), and HMO
(masonry characterisation) individuals for the four types. Hand-written
Turtle — no `rdflib` in the Docker image, and not needed for something
this straightforward.

One real finding from reading `Historic-Structure-Ontology/ontology.ttl` in
full (375 lines) to verify class/property usage before writing this:
**HSTO has no object property linking a `hsto:StructuralPart` to the
`hsto:Facade`/`hsto:HorizontalStructure` instances that decompose it** —
composition is presumably left to BEO/IFC spatial containment instead.
Recorded as an `rdfs:comment` rather than forced through a property with
the wrong domain/range, which would have silently produced an invalid
graph.

Four structural units (417–420) each get their facades, one generic
`hsto:TimberFloor` ("timber floors alla romana" per the manuscript, not
surveyed per unit), and `hsto:Quoin` connections to their row-neighbours.
The quoins' *existence* is documentary evidence (manuscript: "quoined
corners indicating originally detached buildings that were later
physically and structurally joined"), but which specific unit pairs is
inferred from the cadastral-map row order, not confirmed on site or
against the IFC model's own geometry (see {doc}`open_questions`). One
`hsto:HistoricOpening` is recorded — the dressed-stone door arch on
`Facade_419`.

### Visualising it

**The ontologies themselves** (HMO, HSTO — classes/properties, not this
case study's individuals) can be viewed interactively with no local setup,
via the WebVOWL instance each ontology repository bundles:

- HMO: `mlaura1996.github.io/HistoricMasonryOntology/webvowl/`
- HSTO: `mlaura1996.github.io/Historic-Structure-Ontology/webvowl/`

**This case study's instance graph** (`hmo_graph.ttl`) is not what WebVOWL
is for (it visualises schemas, not arbitrary instance data). To view it:
convert to WebVOWL's JSON with the
[VOWL converter](https://github.com/VisualDataWeb/OWL2VOWL) and drop the
result onto either instance above, or — simpler for instance data — load
the `.ttl` into [GraphDB](https://www.ontotext.com/products/graphdb/)
(free tier) or a local
[Apache Jena Fuseki](https://jena.apache.org/documentation/fuseki2/), whose
built-in graph browsers are built for exploring individuals and their
relationships.

## Reproducing this

```bash
docker run --rm -v "C:/path/to/repo:/app" --entrypoint sh \
    modularbimtofem-opensees-mp:dev -c \
    "conda run -n appenv python docker/opensees/castelnuovo_hmo_graph.py"
```

Reads `resources/survey_data/castelnuovo/masonry_classification.json`,
runs each type through `hmo_mqi.py`, and writes `hmo_graph.ttl` +
`material_database.json`.
