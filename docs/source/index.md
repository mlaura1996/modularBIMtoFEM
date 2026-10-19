# openBIMtoFEM documentation

openBIMtoFEM turns an IFC building model into a nonlinear finite-element
model of a masonry aggregate and runs the resulting seismic analysis,
without a commercial pre/post-processor in the loop. It targets
unreinforced masonry aggregates specifically - clusters of adjacent,
structurally interacting units, the case a generic BIM-to-FEM tool tends
to handle worst - and automates the parts of that workflow that are
normally done by hand: wall-to-wall interface detection and selection,
mesh generation and partitioning, contact-element and constraint
generation, and a **parallel nonlinear dynamic analysis on OpenSeesMP**.

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

The workflow in one line: the IFC model is enriched with what is known
about the building, in the enrichment editor, and the knowledge-graph
builder derives from it, through the ontologies and the Pellet reasoner,
the mechanical properties of the masonry, which it writes back into the
model; the enriched model is then converted into the OpenSees model, its
geometry meshed with Gmsh and its materials read from the IFC property
sets, and analysed in OpenSees, in parallel with `OpenSeesMP` inside a
pinned Docker image for large models. The seven steps are described in
{doc}`user_guide/workflow`.

This site exists so that the reasoning behind each piece - not just the
code - stays attached to the work. It has four parts, mirroring how the
[OpenSees documentation](https://opensees.github.io/OpenSeesDocumentation/)
itself is organised:

`````{grid} 1
:gutter: 2

````{grid-item-card} User Guide
:link: user_guide/index
:link-type: doc
Install the pipeline, run it end to end, build and use the Docker image.
Start here if you just want to reproduce a result.
````
````{grid-item-card} Framework for Developer
:link: developer_guide/index
:link-type: doc
How the codebase is organised, what each module does, and the design
decisions behind interface selection, parallel export, and the Docker
image. Start here to extend the pipeline.
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
A worked example the pipeline was developed and validated against: the
geometry, the material characterisation from survey data (HMO/MQI), the
interface selection, and what is still open.
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
