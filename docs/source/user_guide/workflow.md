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

```{figure} ../_static/images/workflow/seven_steps.png
:alt: the seven steps, grouped by the tool that performs them
:width: 100%

The seven steps. Green steps are performed by the user, blue ones by the software; dashed frames are software outside openBIMtoFEM; below each step, what it produces. The section numbers refer to Chapter 5 of the thesis.
```

The two stages meet only in the IFC file: the enrichment (steps 2 to 4) writes the mechanical properties of the masonry into it, and the conversion (steps 6 and 7) reads them together with the geometry.

```{figure} ../_static/images/workflow/overview.png
:alt: overview of the workflow from the survey evidence to the OpenSees engine
:width: 100%

Overview: the enrichment on the left, the conversion on the right, the IFC model in between. The icons are the libraries used at each operation.
```

The diagrams of each step below share one legend.

```{figure} ../_static/images/workflow/legend.png
:alt: legend of the flow diagrams
:width: 60%

Legend of the flow diagrams: processing steps (blue), decisions (pink), data and produced objects (white), phases and external inputs or outputs (grey).
```

## 1. Model and export

Build the federated model of the aggregate following the modelling
requirements (building breakdown, geometric detail, materials and
quantities) and export it as IFC4 with the **Design Transfer View**, so that
irregular walls arrive as solids rather than tessellations. IFC4X3 files are
read as well: the editor, the knowledge-graph builder and the conversion
were checked on the Castelnuovo model exported in both schemas, with the
same results. Name each masonry
material after the masonry type it represents, and leave its mechanical
properties empty: they are derived in step 4. Other materials (timber,
concrete, steel) get their properties in the authoring tool.

## 2. Record the knowledge

Open the IFC file in the enrichment editor (<a href="../editor/index.html">open it</a>), which
runs in the browser and needs no installation. Record the survey and its
sources, the structural units, the façades and their connections, assign the
walls to the façades by selecting them in the 3D view, classify each masonry
type through its seven morphological characteristics, each chosen among the
categories of the masonry quality index, with the evidence for each (the
scores of the index are derived in step 4), and record the vulnerabilities
of each façade. Alternative classifications can be recorded as variants. See
{doc}`../case_study/knowledge_graph` for what each form contains.

```{figure} ../_static/images/workflow/editor_sera_aims.png
:alt: the enrichment editor with the SERA-AIMS benchmark
:width: 100%

The enrichment editor with the SERA-AIMS benchmark: (a) 3D view coloured by façade, (b) its legend, (c) the selected wall and its assignment, (d) the tabs of the records, (e) a masonry type with the evidence for each morphological characteristic, (f) the final check.
```

```{figure} ../_static/images/workflow/editor_castelnuovo.png
:alt: the enrichment editor with the Castelnuovo di Porto aggregate
:width: 100%

The same editor with the Castelnuovo di Porto aggregate: the seven façades, a wall of façade 417a with its vulnerabilities, and the vulnerabilities recorded for each façade with their evidence.
```

```{figure} ../_static/images/workflow/flow_enrichment_editor.png
:alt: flow of the enrichment editor
:width: 80%

What the editor does, from the opening of the file to the enriched IFC model.
```

## 3. Save into the IFC file

When *Check & save* reports no problems, *Save IFC* writes the knowledge
record into the IFC file (`HSV_CaseRecord` on the project, `HSV_Facade` on
the assigned elements, `HMO_MasonryQuality` on the masonry materials).

```{figure} ../_static/images/workflow/editor_sera_aims_check.png
:alt: the Check & save tab of the editor
:width: 70%

*Check & save*: what the graph cannot be built without, the save into the IFC file and the command of the next step.
```

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

```{figure} ../_static/images/workflow/enrichment_architecture.png
:alt: architecture of the enrichment
:width: 100%

How the editor and the knowledge-graph builder work together: inputs, ontologies, editor, enriched IFC model, graph builder and outputs. Grey elements are reused, blue ones were developed in this work.
```

```{figure} ../_static/images/workflow/flow_knowledge_graph.png
:alt: flow of the knowledge-graph builder
:width: 80%

What the builder does, from the enriched IFC model to the knowledge graph and the derived properties written back into the model.
```

The reasoning and the analysis run in two engines outside Python, which openBIMtoFEM drives through their Python interfaces.

```{figure} ../_static/images/workflow/external_engines.png
:alt: Pellet and OpenSees driven from Python
:width: 70%

Pellet (Java) and OpenSees (C++) are driven from Python through Owlready2 and OpenSeesPy.
```

## 5. Check against the IDS

openBIMtoFEM does not include an IDS checker. The enriched file can be
checked against the Information Delivery Specification with an external
tool, for instance IfcTester of the IfcOpenShell project, so that a missing
property or a wrong data type is found on the model rather than during the
analysis. The specification is in `resources/ids/modelling_requirements.ids`, and each
of its specifications lists both IFC4 and IFC4X3_ADD2 in `ifcVersion`.
The prefix `Pset_` is reserved for the property sets of the IFC standard, so
these hold only the properties the standard defines (mass density, Young's
modulus, Poisson's ratio): the constitutive model, the strengths and the
connection state of the beams are kept in the sets `OBTF_MaterialModel` and
`OBTF_BeamConnection`.

## 6. Set up the conversion

The conversion is a short Python script that calls the subpackages
(`ifc_processing`, `mesh_generation`, `opensees_generation`) in sequence and
sets what depends on the problem: mesh size and adaptive meshing, the
interfaces between structural units to be modelled as contact joints, and
the analysis settings. {doc}`running_the_pipeline` walks through a complete
script for the Castelnuovo aggregate.

```{figure} ../_static/images/workflow/package.png
:alt: architecture of the openBIMtoFEM package
:width: 80%

The package: `core` holds the subpackages called by the script, `utils`, `models` and `external` the shared routines, the constitutive models and the third-party code.
```

```{figure} ../_static/images/workflow/flow_data_extractor.png
:alt: flow of data_extractor.py
:width: 80%

`ifc_processing/data_extractor.py`: from the materials of the IFC model to the material database.
```

```{figure} ../_static/images/workflow/flow_geometry_extractor.png
:alt: flow of geometry_extractor.py
:width: 80%

`ifc_processing/geometry_extractor.py`: from the IFC elements to the labelled solids of the STEP file.
```

```{figure} ../_static/images/workflow/flow_mesh_generation.png
:alt: flow of mesh_generation
:width: 80%

`mesh_generation`: physical groups, boundary conditions and the optional adaptive mesh.
```

```{figure} ../_static/images/workflow/flow_opensees_generation.png
:alt: flow of opensees_generation
:width: 80%

`opensees_generation`: nodes, materials, elements and the analysis settings chosen by the user.
```

## 7. Analyse

Run the model in OpenSees, either directly through OpenSeesPy or, for large
models, in parallel with OpenSeesMP through the Docker image
({doc}`docker_image`). For the nonlinear dynamic analyses of the thesis, the last part of the chain was replaced by STKO, which reads the same STEP geometry and material database.

```{figure} ../_static/images/workflow/extension_stko.png
:alt: extension of the workflow through STKO
:width: 80%

Extension through STKO: the same artefacts, assembled and solved in an existing modelling environment.
```
