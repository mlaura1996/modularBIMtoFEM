# Ontologies

The three ontologies the Castelnuovo knowledge graph is built on
(`docker/opensees/castelnuovo_knowledge_graph.py`). Pellet reasons over the
three together with the case-study individuals.

| file | ontology | source |
|---|---|---|
| `hsv.ttl` | Historic Survey Ontology (HSV) | <https://github.com/mlaura1996/Historic-Survey-Ontology> @ `bb719ac` (2026-05-20), unchanged |
| `hsto.ttl` | Historic Structure Ontology (HSTO) | <https://github.com/mlaura1996/Historic-Structure-Ontology> @ `04dd898` (2026-05-20), unchanged |
| `hmo.ttl` | Historic Masonry Ontology (HMO), corrected rules | <https://github.com/mlaura1996/HistoricMasonryOntology>, branch `fix-swrl-rules` |

## `hmo.ttl` — Historic Masonry Ontology, corrected rules

Copy of the Historic Masonry Ontology with its SWRL rules corrected so that
a reasoner can execute them. It is the ontology
`core/ifc_processing/hmo_reasoner.py` runs.

As published, the rules cannot be executed: run with Pellet on the four
Castelnuovo masonry types, the published ontology is reported
inconsistent. The corrections, applied by `tools/fix_swrl_rules.py` in the
ontology repository, are:

| | correction | without it |
|---|---|---|
| F1 | unit-dimension rules read the maximum length (not the minimum twice) and average as (min + max) / 2 | 12 of 16 values wrong |
| F2 | MQI totals multiply the sum by the unit-material score (`multiply` had two arguments); `?HJoP`/`?HoP` unified | 16 of 16 values wrong |
| F3 | property formulas join RVE and quality index through the wall (`?Rpv` was free) | 16 of 16 values multiple |
| F4 | scores asserted on the quality index, as the property domains require, not on the wall | inconsistent |
| F5 | numeric literals typed `xsd:float`, as the ranges declare (13 were untyped strings) | inconsistent |
| F8 | `MasonryQualityIndex` no longer a subclass of a class it is declared disjoint with | inconsistent |
| F6 | added: unit-material rule for squared soft stone | 4 of 16 values missing (type A) |
| F7 | added: `NoHeaders` and its rule, absence of headers in non-rubble masonry | 4 of 16 values missing (type C) |

The "without it" column is the result of removing that one correction and
running Pellet again; each is necessary. With all of them, Pellet derives
one value per quantity for every type, equal to those of
`core/ifc_processing/hmo_mqi.py` within its rounding.

F6 and F7 add vocabulary rather than correct it, and are the two changes
the ontology's author should review as design decisions.

## How the three meet

HSTO's `isMadeOf` goes from an `hsto:Facade` to an `hmo:MasonryWall`; HSTO
has no wall class of its own. That property is the joint: each facade of
the case study is at the same time an `hsv:Facade` (the surveyed object,
with its photographs) and an `hsto:Facade` (a structural part), and is made
of one `hmo:MasonryWall`, on which the HMO rules derive the quality index
and the homogenised properties.

What the ontologies cannot say, and the knowledge graph records with
standard vocabularies instead:

- **Dates and activities.** HSV has neither: the survey campaigns are
  `prov:Activity` individuals, dates are `dcterms:date`/`dcterms:created`,
  derivation (raw scan, cleaned cloud, BIM model; quality index from
  photographs) is `prov:wasDerivedFrom`.
- **Roles beyond survey.** HSV has `Inspector` (acquisition),
  `PostProcesser` and `Author`; there is no role for bibliographic
  research or a pre-survey desk study, recorded as people associated with
  the corresponding `prov:Activity`.
- **Unit to facade, unit to floor.** `hsv:contains` stops at the
  structural unit (its domain is aggregate, historic centre or region) and
  HSTO has no part-whole property, so the decomposition is
  `dcterms:hasPart`.
- **Organisations and affiliations.** `foaf:Organization`, `foaf:member`.
- **Masonry types.** `skos:Concept`, linked from each wall with
  `dcterms:type`.

The builder stops if any HSV, HSTO or HMO term it uses is not declared, or
if a property is used outside its declared domain or range: OWL would not
report either, it would accept a misspelt term as new and infer that a
wrongly linked individual belongs to the domain.

## Running the reasoner

Not part of the Docker image. Needs a Java runtime and, in any Python
environment:

    pip install owlready2==0.48 rdflib
    python docker/opensees/castelnuovo_knowledge_graph.py

owlready2 is pinned to 0.48 because later releases bundle Jena libraries
compiled for Java 25, which fail on older runtimes with
`UnsupportedClassVersionError`. Without Java,
`docker/opensees/castelnuovo_material_engine.py` writes the same material
database from the Python implementation of the rules.
