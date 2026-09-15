# API Reference

Every public module, class and function in the pipeline, generated
directly from the source's own docstrings via
[Sphinx autodoc](https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html) -
these pages are never hand-written, so they cannot drift out of sync with
the code the way a hand-maintained reference can. If a docstring here is
wrong or missing, the fix belongs in the source file, not on this page.

For *why* a module is built the way it is - the design decisions, the
things that were tried and abandoned - see the
{doc}`../developer_guide/index` instead; this section is for looking up
an exact signature, parameter, or return value once you already know
which function you need.

```{toctree}
:maxdepth: 2

ifc_processing
mesh_generation
opensees_generation
gmsh2opensees
models
utils
config
```
