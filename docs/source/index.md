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

```{image} _static/images/pipeline_diagram.svg
:alt: IFC model, through IfcOpenShell/OpenCASCADE and apeGmsh, to a TCL model run on OpenSeesMP, producing a stress-coloured result.
:width: 100%
```

The pipeline in one line: an IFC model is turned into per-solid STEP
geometry and a material database (IfcOpenShell + OpenCASCADE), meshed and
partitioned (apeGmsh/Gmsh), exported as a TCL model with wall-to-wall
contact interfaces, and run on `OpenSeesMP` inside a pinned Docker image.

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
