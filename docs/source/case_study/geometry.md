# Geometry preparation

Prepared outside this repository; documented here because Chapter 7's
mesh-generation results depend on the specific choices made, and they
should travel with the case study rather than live only in
PROJECT_BRIEF.md.

## Provenance

- Source: `final_example.ifc` (IFC4) — 62 walls, 32 slabs, 3 stairs, 41
  windows, 16 doors.
- Converted to STEP through `ifcopenshell`, using the **iterator** with
  `SERIALIZED` output — `create_shape` was found to return corrupted BREP
  data in the version used; the iterator does not.
- 14 elements exported as open shells, repaired by sewing.
- 8 exact duplicate solids removed.
- 17 interpenetrations resolved by cutting the smaller body with the
  larger (0.2034 m³ removed).
- **General fuse (imprint)** applied, fuzzy tolerance 1e-4, so touching
  faces are conformal. Not a boolean union — all 316 solids stay separate
  bodies, which is what allows per-body material assignment (Task
  materials) and per-body interface definition (Task A) at all.

## Resulting geometry

| Property | Value |
|---|---|
| Solids | 316 |
| Faces | 3203 |
| Volume | 663.71 m³ |
| Bounding box | 14.95 × 28.49 × 15.18 m |
| Invalid solids / slivers / non-manifold edges | 0 / 0 / 0 |
| Wall thickness | predominantly 0.50 m |
| Slab thickness | 0.10 m |

## Meshing

At 0.167 m element size (3 elements through the wall thickness, matching
the brief's own sizing rationale): **278,858 nodes, 953,994 linear
tetrahedra**. This is a design variable, not a given — too large to
analyse on the development laptop (§7.1's Intel i7-10750H, 6c/12t, 16 GB
RAM); see {doc}`open_questions` for the run-machine question this is
waiting on.

## Touching pairs with zero contact area

62 touching pairs in the geometry make contact only at a vertex or along
an edge — no actual contact surface. `InterfaceDetection.find_touching_surface_pairs`'s
`min_area` filter exists specifically to exclude these (see
{doc}`../developer_guide/task_a_interfaces`); they must never generate
interface elements, since a zero-area contact surface has no meaningful
tributary area to scale Kn/Kt by.
