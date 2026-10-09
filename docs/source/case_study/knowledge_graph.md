# Knowledge graph

The case study is described in a single knowledge graph built on the
Historic Survey (HSV), Historic Structure (HSTO) and Historic Masonry (HMO)
ontologies: the survey and its documents, with the people and activities
that produced them; the façades of the aggregate and the masonry wall each
is made of; and the quality index and homogenised properties of every wall,
derived by Pellet from the HMO rules (see {doc}`materials`).

```{raw} html
<p><a href="../knowledge-graph/index.html"><strong>Browse the knowledge graph</strong></a>,
with an interactive view of the graph, a 3D view of the BIM model coloured
by masonry type, and tables of façades, masonry types, documents, people and
activities, or
<a href="../knowledge-graph/knowledge_graph.ttl"><strong>download it</strong></a> in Turtle.</p>
```

## How it is produced

```bash
python scripts/export_bim_for_web.py                 # needs IfcOpenShell
pip install owlready2==0.48 rdflib pillow            # and a Java runtime
python docker/opensees/castelnuovo_knowledge_graph.py
python scripts/build_knowledge_graph_page.py --photos <folder of the survey photographs>
```

The first script exports the BIM model (`final_example.ifc`) for the page,
one glTF node per element, and lists its elements and their materials in
`resources/survey_data/castelnuovo/bim_elements.json`. The BIM model and the
graph are linked by the material name, as in the conversion to the
numerical model: every element whose material is a tufelli masonry type is
recorded in the graph as part of the BIM model and of that type. Which
façade an element belongs to is not recorded in the IFC file, so the link
is by type, not by façade.

The second script builds the graph from
`resources/survey_data/castelnuovo/survey_record.json` and
`masonry_classification.json`, runs Pellet over it together with the three
ontologies in `resources/ontologies/`, checks the derived values against
`core/ifc_processing/hmo_mqi.py`, and writes
`output/castelnuovo/knowledge_graph.ttl` and the material database. The
third reads that graph and writes the browsable page to
`docs/source/_extra/knowledge-graph/`, which Sphinx publishes at the root of
this site. Both the page's view and its tables are generated from the graph
itself, so what the page shows is what the graph says.
