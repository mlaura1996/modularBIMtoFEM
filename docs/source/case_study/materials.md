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

```{note}
The out-of-plane and in-plane columns, and so G and τ0, were corrected
after a rule-by-rule comparison with the published HMO ontology: the scores
of lime mortar and of partially staggered vertical joints had these two
directions transposed. The vertical totals, and therefore fm and E, were
never affected.
```

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
  - 4.55 / 4.20 / 4.20
  - 3.445
  - 1526.6
  - 482.8
  - 0.0591
  - fm ~10% above upper bound; E, G, τ0 inside (G near its upper limit)
* - B
  - 2.80 / 2.80 / 3.15
  - 2.616
  - 1198.7
  - 421.3
  - 0.0475
  - fm ~21%, τ0 ~16% and G ~2% above upper bound; only E inside
* - C
  - 1.40 / 1.05 / 1.40
  - 2.099
  - 987.8
  - 335.6
  - 0.0305
  - **fully inside** the NTC irregular-tufo range
* - D
  - = B (by construction)
  - 2.616
  - 1198.7
  - 421.3
  - 0.0475
  - = B
```

Types A and B still exceed the NTC compressive-strength upper bound by a
residual 10–21% after the conservative revision, and type B (so also D)
exceeds it for shear strength (~16%) and shear modulus (~2%) as well —
accepted rather than tuned further to force a match (see `ntc_comparison.note` per type in the
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
of the SERA-AIMS reference masonry (an earlier experimentally-calibrated
benchmark, see {doc}`../developer_guide/known_issues`). Current values:
type A 0.451 MPa, types B/D 0.342 MPa, type C 0.274 MPa. See
{doc}`../developer_guide/known_issues` for why this couldn't be left at 0.

**Shear strength** (Turnšek–Čačovič, computed above) is not a
`Material` field — ASDConcrete3D's shear behaviour emerges from the
triaxial damage-plasticity formulation, not an explicit input. Kept in the
JSON under `_shear_strength_turnsek_cacovic_MPa` for traceability, excluded
from the actual `Material()` object.

## Knowledge graph

`docker/opensees/castelnuovo_knowledge_graph.py` writes
`output/castelnuovo/knowledge_graph.ttl`, the case study as one graph over
the three ontologies in `resources/ontologies/` (see the README there for
how they meet and what each lacks). It is built from the case-study
workbook `resources/survey_data/castelnuovo/case.xlsx` (people,
organisations, activities, documents, which facade each photograph shows,
and the masonry classification above) by the generic pipeline in
`core/knowledge_graph`. The graph can be browsed online, see
{doc}`knowledge_graph`.

- **HSV**: historic centre, aggregate, the four structural units, the
  seven facades; the 48 photographs (each `hsv:isDocumentOf` its facade,
  with its timestamp), the raw, cleaned and indexed point clouds, the BIM
  model, the pre-survey drawings and the publications, with the people who
  acquired, processed or authored them.
- **HSTO**: each facade is a structural part built with the muratura a
  tufelli technique and `hsto:isMadeOf` one masonry wall; one generic
  `hsto:TimberFloor` per unit (timber floors alla romana are documented for
  the aggregate, not surveyed per unit; `hasAccessibility false`); the
  arched opening of facade 419 as an `hsto:HistoricOpening`.
- **HMO**: one `hmo:MasonryWall` per facade (seven walls, four types),
  each with its representative volume element, pattern, unit range and
  quality index. Pellet derives the quality indices and the four
  properties of all seven walls; the script checks that walls of the same
  type agree and that every value matches `hmo_mqi.py`, writes the derived
  values into the graph, and writes the material database from them. Each
  quality index is `prov:wasDerivedFrom` the photographs of its facade.

Not asserted, for lack of evidence at facade level: connections between
units. The manuscript documents quoined corners in the aggregate
generally, not which pair of facades they join; the earlier hand-written
graph had placed `hsto:Quoin` connections between units in cadastral-map
row order, which was an inference, not an observation. The date of the
third survey campaign is not recorded either.

### Visualising it

**The ontologies themselves** (HMO, HSTO — classes/properties, not this
case study's individuals) can be viewed interactively with no local setup,
via the WebVOWL instance each ontology repository bundles:

- HMO: `mlaura1996.github.io/HistoricMasonryOntology/webvowl/`
- HSTO: `mlaura1996.github.io/Historic-Structure-Ontology/webvowl/`

**This case study's knowledge graph** (`knowledge_graph.ttl`) is not what WebVOWL
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
pip install owlready2==0.48 rdflib openpyxl    # and a Java runtime
python docker/opensees/castelnuovo_knowledge_graph.py
```

writes `knowledge_graph.ttl` and `material_database.json`. Inside the
Docker image, which has no Java, the engine route writes the same
database:

```bash
docker run --rm -v "C:/path/to/repo:/app" --entrypoint sh \
    modularbimtofem-opensees-mp:dev -c \
    "conda run -n appenv python docker/opensees/castelnuovo_material_engine.py"
```
