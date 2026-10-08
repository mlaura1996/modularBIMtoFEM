# Ontologies

## `hmo.ttl` — Historic Masonry Ontology, corrected rules

Copy of the Historic Masonry Ontology
(<https://github.com/mlaura1996/HistoricMasonryOntology>, branch
`fix-swrl-rules`) with its SWRL rules corrected so that a reasoner can
execute them. It is the ontology `core/ifc_processing/hmo_reasoner.py` runs,
and `docker/opensees/castelnuovo_hmo_graph.py --reasoner` derives the
material database from it.

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

## Running the reasoner

Not part of the Docker image. Needs a Java runtime and, in any Python
environment:

    pip install owlready2==0.48 rdflib
    python docker/opensees/castelnuovo_hmo_graph.py --reasoner

owlready2 is pinned to 0.48 because later releases bundle Jena libraries
compiled for Java 25, which fail on older runtimes with
`UnsupportedClassVersionError`.
