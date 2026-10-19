# From the IFC model to the analysis

openBIMtoFEM takes a masonry aggregate from its IFC model to a numerical
analysis in seven steps. The steps marked *user* need an engineering
judgement; the others are done by the software, and each is checked before
the next one starts. Three steps use software that is not part of
openBIMtoFEM: the authoring tool, the IDS checker and OpenSees.

| | step | who | tool |
|---|---|---|---|
| 1 | Model and export | user | authoring tool (external) |
| 2 | Record the knowledge | user | enrichment editor |
| 3 | Save into the IFC file | software | enrichment editor |
| 4 | Build and reason | software | knowledge-graph builder |
| 5 | Check against the IDS | software | IDS checker (external) |
| 6 | Set up the conversion | user | Python script |
| 7 | Analyse | software | OpenSees (external) |

## 1. Model and export

Build the federated model of the aggregate following the modelling
requirements (building breakdown, geometric detail, materials and
quantities) and export it as IFC4 with the **Design Transfer View**, so that
irregular walls arrive as solids rather than tessellations. Name each masonry
material after the masonry type it represents, and leave its mechanical
properties empty: they are derived in step 4. Other materials (timber,
concrete, steel) get their properties in the authoring tool.

## 2. Record the knowledge

Open the IFC file in the enrichment editor (<a href="../editor/index.html">open it</a>), which
runs in the browser and needs no installation. Record the survey and its
sources, the structural units, the façades and their connections, assign the
walls to the façades by selecting them in the 3D view, classify each masonry
type through the seven parameters of the masonry quality index with the
evidence for each, and record the vulnerabilities of each façade. Alternative
classifications can be recorded as variants. See
{doc}`../case_study/knowledge_graph` for what each form contains.

## 3. Save into the IFC file

When *Check & save* reports no problems, *Save IFC* writes the knowledge
record into the IFC file (`HSV_CaseRecord` on the project, `HSV_Facade` on
the assigned elements, `HMO_MasonryQuality` on the masonry materials).

## 4. Build and reason

```bash
python -m core.knowledge_graph build <model.ifc> --out <output dir>
```

The builder checks the record, builds the knowledge graph, runs Pellet over
the HSV, HSTO, HMO and FMO rules (Java and owlready2 are required, see
{doc}`installation`), checks every derived value against an independent
implementation of the quality index, and writes the graph, the material
database and a copy of the IFC file with the derived properties on the
masonry materials. If a reference does not resolve or a check fails, it
stops with a message naming the record: correct it in the editor and save
again.

## 5. Check against the IDS

openBIMtoFEM does not include an IDS checker. The enriched file can be
checked against the Information Delivery Specification with an external
tool, for instance IfcTester of the IfcOpenShell project, so that a missing
property or a wrong data type is found on the model rather than during the
analysis.

## 6. Set up the conversion

The conversion is a short Python script that calls the subpackages
(`ifc_processing`, `mesh_generation`, `opensees_generation`) in sequence and
sets what depends on the problem: mesh size and adaptive meshing, the
interfaces between structural units to be modelled as contact joints, and
the analysis settings. {doc}`running_the_pipeline` walks through a complete
script for the Castelnuovo aggregate.

## 7. Analyse

Run the model in OpenSees, either directly through OpenSeesPy or, for large
models, in parallel with OpenSeesMP through the Docker image
({doc}`docker_image`).
