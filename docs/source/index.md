# openBIMtoFEM documentation

openBIMtoFEM turns the IFC model of an unreinforced masonry aggregate into
a finite-element model in OpenSees, and carries along the knowledge on which
its mechanical characterisation rests. Masonry aggregates, clusters of
adjacent and structurally interacting units built and transformed over
centuries, are the case a generic BIM-to-FEM tool handles worst, because
their geometry is irregular and the properties of their walls are not
measured but inferred from what a survey can observe.

The framework works in two stages, connected only through the IFC file.

- **Semantic enrichment.** What is known about the building, from the
  survey and its sources to the structural units, the façades, the
  classification of the masonry and its vulnerabilities, is recorded on the
  model in the **enrichment editor**, a web page that runs in the browser.
  The **knowledge-graph builder** turns this record into a knowledge graph
  on four ontologies (HSV, HSTO, HMO, FMO), has the Pellet reasoner derive
  the mechanical properties of each masonry type and the behaviour and
  failure mechanisms of each wall, and writes the properties back into the
  IFC file.
- **Conversion.** The enriched model is turned into the OpenSees model.
  The geometry is recovered as closed solids and meshed with Gmsh, the
  materials are read from the IFC property sets, contact interfaces can be
  placed between the structural units, and the model is analysed in
  OpenSees, in parallel on **OpenSeesMP** for large models.

Everything is open source, with no commercial pre- or post-processor in
the loop.

```{figure} _static/images/workflow/overview.png
:alt: Overview of the openBIMtoFEM workflow, from the survey evidence and the IFC model to the OpenSees engine.
:width: 100%

The openBIMtoFEM workflow. The semantic enrichment (left) records the
survey evidence on the IFC model and derives the mechanical properties of
the masonry, which are written back into the model; the conversion (right)
reads the geometry and the material properties from the same IFC file and
meets them in the OpenSees engine. The icons are the libraries used at each
step.
```

The seven steps a user goes through, from the authoring tool to the
analysis, are described in {doc}`user_guide/workflow`.

This site exists so that the reasoning behind each piece - not just the
code - stays attached to the work. It has four parts, mirroring how the
[OpenSees documentation](https://opensees.github.io/OpenSeesDocumentation/)
itself is organised:

`````{grid} 1
:gutter: 2

````{grid-item-card} User Guide
:link: user_guide/index
:link-type: doc
The seven steps from the IFC model to the analysis, with the enrichment
editor, the knowledge-graph builder and the conversion; installation and
the Docker image. Start here to use openBIMtoFEM.
````
````{grid-item-card} Framework for Developer
:link: developer_guide/index
:link-type: doc
How the code is organised (the `core` subpackages, the editor, `utils`,
`models`, `external`), and the design decisions behind the knowledge graph,
interface selection, parallel export and the Docker image. Start here to
extend openBIMtoFEM.
````
````{grid-item-card} API Reference
:link: api_reference/index
:link-type: doc
Every public module, class and function, generated from the source's own
docstrings. Start here to look up an exact signature or return value.
````
````{grid-item-card} Castelnuovo Case Study
:link: case_study/index
:link-type: doc
A real aggregate in Castelnuovo di Porto taken through the whole
workflow: its knowledge record and knowledge graph, the masonry
characterisation (HMO/MQI) and failure mechanisms (FMO), the geometry, the
interface selection, the analyses, and what is still open. The knowledge
graph of the SERA-AIMS shake-table benchmark is published alongside it.
````
`````

```{toctree}
:maxdepth: 2
:hidden:

user_guide/index
developer_guide/index
api_reference/index
case_study/index
```
