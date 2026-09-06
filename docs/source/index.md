# modularBIMtoFEM — Chapter 7 documentation

This is the documentation for the `chapter7-castelnuovo` branch of
`modularBIMtoFEM`: the software side of a PhD thesis on automating the
BIM-to-FEM transition for the seismic assessment of unreinforced masonry
aggregates. Chapter 7 extends the pipeline validated in earlier chapters
(IFC parsing, geometry/material extraction, OpenSees generation) so that it
can run a **parallel nonlinear dynamic analysis on its own**, without the
commercial pre/post-processor (STKO) that Chapter 6 relied on.

```{image} _static/images/pipeline_diagram.svg
:alt: IFC model, through IfcOpenShell/OpenCASCADE and apeGmsh, to a TCL model run on OpenSeesMP, producing a stress-coloured result.
:width: 100%
```

The pipeline in one line: an IFC model is turned into per-solid STEP
geometry and a material database (IfcOpenShell + OpenCASCADE), meshed and
partitioned (apeGmsh/Gmsh), exported as a TCL model with wall-to-wall
contact interfaces, and run on `OpenSeesMP` inside a pinned Docker image.

This site exists so that the reasoning behind each piece — not just the
code — stays attached to the work. It has three parts, mirroring how the
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
decisions behind Task A (interface selection), Task B (parallel export)
and Task C (the Docker image). Start here to extend the pipeline.
````
````{grid-item-card} Castelnuovo Case Study
:link: case_study/index
:link-type: doc
The worked example this chapter is built around: the geometry, the
material characterisation from survey data (HMO/MQI), the interface
selection, and what is still open. Start here for the thesis narrative.
````
`````

```{toctree}
:maxdepth: 2
:hidden:

user_guide/index
developer_guide/index
case_study/index
```
