# Knowledge graphs

Each case study is described in a knowledge graph built on the Historic
Survey (HSV), Historic Structure (HSTO) and Historic Masonry (HMO)
ontologies: the survey or the publications and their documents, with the
people and activities that produced them; the façades and the masonry wall
each is made of, the floors, openings and connections; and the quality
index and homogenised properties of every wall, derived by Pellet from the
HMO rules (see {doc}`materials`). Each graph can be browsed online, with
an interactive view of the graph, a 3D view of the BIM model coloured by
masonry type, and tables of the same content.

```{raw} html
<ul>
<li><a href="../knowledge-graph/index.html"><strong>Castelnuovo di Porto</strong></a>:
seven façades of a masonry aggregate, four masonry types, the survey
campaigns and their 48 photographs
(<a href="../knowledge-graph/knowledge_graph.ttl">graph in Turtle</a>).</li>
<li><a href="../knowledge-graph-sera-aims/index.html"><strong>SERA-AIMS benchmark</strong></a>:
the half-scale stone masonry aggregate tested on the shake table, the
interface between its units, and the properties derived for its masonry
next to the measured ones
(<a href="../knowledge-graph-sera-aims/knowledge_graph.ttl">graph in Turtle</a>).</li>
</ul>
```

## Recording a case study

A case study is entered in one Excel workbook, one sheet per kind of
record: project, organisations, people, activities, documents, units,
façades, photographs, connections, openings, masonry types (the seven MQI
parameters with the evidence for each, flags, density and variants) and
measured properties. Categorical cells offer the allowed values in a list,
and every header carries a note on what goes in it.

```{raw} html
<p><a href="../case_template.xlsx"><strong>Download the empty workbook</strong></a></p>
```

The filled workbooks of the two case studies are
`resources/survey_data/castelnuovo/case.xlsx` and
`resources/survey_data/sera_aims/case.xlsx`.

## Building the graph and the page

```bash
pip install owlready2==0.48 rdflib openpyxl pillow   # and a Java runtime
python scripts/export_bim_for_web.py <model.ifc> --glb <page>/bim/model.glb \
    --elements <bim_elements.json>                     # needs IfcOpenShell
python -m core.knowledge_graph build <case.xlsx> --out <output dir> \
    --bim <bim_elements.json> --site <page> [--photos <photo folder>]
```

The first command exports the BIM model for the page, one glTF node per
element, and lists its elements and their materials. The BIM model and
the graph are linked by the material name, as in the conversion to the
numerical model: an element whose material is the name of a masonry type
is recorded as part of the BIM model and of that type. Which façade an
element belongs to is not recorded in the IFC file, so the link is by type.

The second reads the workbook, checks that its cross-references resolve,
builds the graph, checks that every HSV, HSTO and HMO term is declared and
every property used within its domain and range, runs Pellet over the
ontologies and the graph together, checks every derived value against
`core/ifc_processing/hmo_mqi.py`, and writes `knowledge_graph.ttl`, the
material database and the page. The variants of a classification are
recorded as hypothetical walls, so the reasoner derives them in the same
run. The page's view and tables are generated from the graph itself, and
pages written under `docs/source/_extra/` are published with this site.

`python -m core.knowledge_graph template <path.xlsx>` writes the empty
workbook.
