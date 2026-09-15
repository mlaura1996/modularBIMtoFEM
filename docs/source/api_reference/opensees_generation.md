# `core.opensees_generation`

OpenSees element/material construction, junction-tie remapping, the
partition-aware TCL exporter, static/gravity analysis, and the shared
element-sampling policy used by both live time-history runs and post-hoc
reconstruction.

```{eval-rst}
.. automodule:: core.opensees_generation.model_builder
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: core.opensees_generation.junction_ties
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: core.opensees_generation.tcl_export
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: core.opensees_generation.analysis_run
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: core.opensees_generation.element_sampling
   :members:
   :undoc-members:
   :show-inheritance:
```

```{note}
`core/opensees_generation/cyclic_test.py` is not documented here: it is a
top-level script (reads a CSV, runs an OpenSees analysis at import time),
not an importable module — importing it for autodoc would execute the
analysis as a side effect. Run it directly instead:
`python core/opensees_generation/cyclic_test.py`.
```
