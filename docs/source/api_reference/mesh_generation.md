# `core.mesh_generation`

Meshing (via apeGmsh), wall-to-wall interface detection/selection, and the
gap-closing routine for junctions drawn apart in the source geometry.

```{eval-rst}
.. automodule:: core.mesh_generation.mesh
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: core.mesh_generation.wall_interfaces
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: core.mesh_generation.geometry_healing
   :members:
   :undoc-members:
   :show-inheritance:
```

```{note}
`core/mesh_generation/connections.py` is not documented here: the entire
file is commented out (an earlier, abandoned approach kept for reference,
not live code). See {doc}`../developer_guide/architecture` for what
replaced it.
```
