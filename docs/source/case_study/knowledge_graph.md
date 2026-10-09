# Knowledge graphs

Each case study is described in a knowledge graph built on the Historic
Survey (HSV), Historic Structure (HSTO), Historic Masonry (HMO) and
Failure Mechanism (FMO) ontologies: the survey or the publications and their documents, with the
people and activities that produced them; the façades and the masonry wall
each is made of, the floors, openings and connections; and the quality
index and homogenised properties of every wall, derived by Pellet from the
HMO rules (see {doc}`materials`); and the behaviour of every wall in each
direction and the failure mechanisms its vulnerabilities enable, derived
from the FMO rules. Each graph can be browsed online, with
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

A case study is recorded on its IFC model in the case-study editor, a web
page that runs entirely in the browser: the model is read and drawn with
[IFC-Lite](https://ifclite.dev), and nothing is uploaded.

```{raw} html
<p><a href="../editor/index.html"><strong>Open the case-study editor</strong></a>
(<a href="../editor/index.html?example=sera-aims">try it with the SERA-AIMS example</a>)</p>
```

The editor has one form for each kind of record: project, organisations,
people, activities, documents, units, façades, photographs, connections,
openings, vulnerabilities of each façade wall (FMO), masonry types (the
seven MQI parameters with the evidence for each, flags, density and
variants) and measured properties. Categories are chosen from lists, and a
record that names another (the people of an activity, the unit of a
façade) is picked from the records that exist; renaming a record renames
it wherever it is named. The walls of each façade are assigned by
selecting them in the 3D model, which can be coloured by façade or by
masonry type. *Check & save* lists what the graph cannot be built without.

*Save IFC* writes the case study into the IFC file:

| where | property set | what |
|---|---|---|
| `IfcProject` | `HSV_CaseRecord` | `Record`, the whole case study as JSON |
| each assigned element | `HSV_Facade` | `Facade`, `Unit`, `MasonryType`, `Vulnerabilities` |
| each `IfcMaterial` named as a masonry type | `HMO_MasonryQuality` (material properties) | the seven MQI categories, `MassDensity` |

The record is the source the graph is built from; the element and
material property sets repeat it where other IFC software can see it.
Saving again replaces what an earlier save wrote, and leaves every other
entity of the file as it was. Opening the saved file restores the case
study, and unsaved changes are kept in the browser until saved.

The same records can be kept as a `case.json` (*Download case.json*) or in
an Excel workbook with one sheet per form, whose categorical cells offer
the allowed values in a list.

```{raw} html
<p><a href="../case_template.xlsx">Download the empty workbook</a></p>
```

The SERA-AIMS benchmark is recorded in
`resources/ifc_examples/sera_aims/aggregate_1_case.ifc`, with its walls
assigned to the façades, and in `resources/survey_data/sera_aims/case.json`
and `case.xlsx`; Castelnuovo di Porto in
`resources/survey_data/castelnuovo/case.json` and `case.xlsx`.

## Building the graph and the page

```bash
pip install owlready2==0.48 rdflib openpyxl pillow   # and a Java runtime
python scripts/export_bim_for_web.py <model.ifc> --glb <page>/bim/model.glb \
    --elements <bim_elements.json>                     # needs IfcOpenShell
python -m core.knowledge_graph build <case> --out <output dir> \
    --bim <bim_elements.json> --site <page> [--photos <photo folder>]
```

`<case>` is the IFC file saved by the editor, a `case.json` or a workbook.
The first command exports the BIM model for the page, one glTF node per
element, and lists its elements and their materials. The BIM model and
the graph are linked by the material name, as in the conversion to the
numerical model: an element whose material is the name of a masonry type
is recorded as part of the BIM model and of that type. The elements the
editor assigned to a façade are also recorded as parts of that façade.

The second reads the case study, checks that its cross-references resolve,
builds the graph, checks that every HSV, HSTO, HMO and FMO term is declared and
every property used within its domain and range, runs Pellet over the
ontologies and the graph together, checks every derived value against
`core/ifc_processing/hmo_mqi.py`, and writes `knowledge_graph.ttl`, the
material database and the page. The variants of a classification are
recorded as hypothetical walls, so the reasoner derives them in the same
run. The page's view and tables are generated from the graph itself, and
pages written under `docs/source/_extra/` are published with this site.

`python -m core.knowledge_graph convert <case> <case.json | case.xlsx>`
converts a case study between the three forms (from an IFC file, to JSON
or a workbook), `template <path.xlsx>` writes the empty workbook, and
`schema <schema.json>` writes the description of the forms the editor is
generated from (`docs/source/_extra/editor/schema.json`).
