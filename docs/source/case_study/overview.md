# Overview

## The building

Castelnuovo di Porto, a masonry aggregate in the "second ring of minor
dwellings... between Piazza Garibaldi and Via Umberto I" (per the survey
manuscript, cross-checked against a cadastral map excerpt showing parcels
363/364/367/417–420). Local construction technique is *muratura a
tufelli* — small lithoid tuff units in thin lime-pozzolana joints, with
coursing regularity and joint finish as the key discriminators between
construction phases.

## Geometry state

Prepared outside this repository (IFC → STEP via `ifcopenshell`, cleaned,
imprinted) — see {doc}`geometry` for the full provenance trail:

- 316 solids, 3203 faces, 663.71 m³, bounding box 14.95 × 28.49 × 15.18 m
- zero invalid solids, zero slivers, zero non-manifold edges
- wall thickness predominantly 0.50 m; slabs 0.10 m
- source IFC: 62 walls, 32 slabs, 3 stairs, 41 windows, 16 doors
- a trial mesh at 0.167 m (3 elements through the wall thickness) gives
  **278,858 nodes / 953,994 linear tetrahedra** — the full-scale model, not
  yet run (see {doc}`open_questions`)

## What has actually been run

Not the full-scale model yet. What's verified, end to end, via real
`mpirun -np N OpenSeesMP` (not mocked):

- a 2-volume touching pair, 1 selected interface (`test_task_ab_reconciled.py`)
- an 18-volume connected cluster (built by BFS over touching pairs from
  the geometry), **2 selected interfaces** out of 39 candidates (29
  classified as `vertical_joint`), **6 partitions** — matching the
  Chapter 6/7 reference partition count (`test_task_ab_scaled.py`)

The 2-out-of-29 selection is deliberate, not a placeholder: selecting all
29 candidate vertical joints produced a `Matrix Singular` failure under
self-weight alone — enough walls released from each other that part of the
cluster became a mechanism. See
{doc}`../developer_guide/task_a_interfaces` for the full account. The
selection that converges is conservative on purpose; extending it further
is future work, one interface at a time, checking convergence after each
addition rather than selecting the full candidate set up front.

## Material characterisation

Castelnuovo's IFC has four masonry materials
(`Tufelli_masonry_typeA`–`typeD`) with no mechanical properties attached.
Characterised from survey data (photos, manuscript, cadastral map,
reference typology text) using the thesis's own HMO/MQI methodology — full
account in {doc}`materials`.

## What this demonstrates for the chapter

Per PROJECT_BRIEF.md §1, Chapter 7 must demonstrate (a) mesh generation
from as-built geometry and (b) the computational demand an analysis at
this scale entails. (a) is demonstrated by the geometry pipeline and the
278,858-node trial mesh above. (b) — actual wall-clock time, peak memory,
DOF count, reported per brief §7.4 — is not yet measured, because the
full-scale run itself hasn't happened (see {doc}`open_questions`).
