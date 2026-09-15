# `models`

Constitutive-law helper formulas used to derive `ASDConcrete3D`
parameters from calibration data.

```{eval-rst}
.. automodule:: models.damage_law
   :members:
   :undoc-members:
   :show-inheritance:
```

```{note}
`models/masonry_cube_compression.py` is not documented here: it is a
top-level calibration script (builds and runs a single-cube OpenSees
model at import time), not an importable module — importing it for
autodoc would execute that analysis as a side effect. Run it directly
instead: `python models/masonry_cube_compression.py`.
```
