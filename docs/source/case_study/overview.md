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

A second, cleaned STEP (`example_clean_PRONTO.stp`,
`scripts/repair_step_geometry.py`) was produced later, from a slab-free
source IFC (0 slabs vs. the original's 32, 115 elements vs. 154):
duplicate solids and real interpenetrations removed, 279 volumes after
fragment, 623.06 m³ (no slabs, so not directly comparable to the 663.71 m³
above). This is the geometry Task A's interactive selection tool and the
full-aggregate runs below use - the 316-solid/663.71 m³ figures above
still describe the original, still used by the smaller Task A/B test
scripts (`test_task_ab_*.py`).

## What has actually been run

Not the brief's full-resolution model yet (0.167 m element size,
~279k nodes/954k tets - see {doc}`open_questions`). What's verified, end
to end, via real `mpirun -np N OpenSeesMP` (not mocked), smallest to
largest:

- a 2-volume touching pair, 1 selected interface (`test_task_ab_reconciled.py`)
- an 18-volume connected cluster (built by BFS over touching pairs from
  the geometry), **2 selected interfaces** out of 39 candidates (29
  classified as `vertical_joint`), **6 partitions** — matching the
  Chapter 6/7 reference partition count (`test_task_ab_scaled.py`)
- **the full aggregate** - all 279 volumes of the cleaned geometry (no
  slabs, duplicates/interpenetrations resolved - see {doc}`geometry`), a
  coarse 0.6 m mesh (17,700 nodes / 57,827 elements), **11 selected
  interfaces** out of 885 candidates, chosen interactively against the
  real building picture with `scripts/select_interfaces_gui.py` (not a
  hand-picked table subset - see
  {doc}`../developer_guide/task_a_interfaces`), **6 partitions**
  (`docker/opensees/full_aggregate_with_interfaces_clean.py`). Converges
  on all 6 ranks; self-weight vs. base-reaction balance 0.028% error, same
  accuracy as the bonded (no-interfaces) reference case.

An earlier 29-candidate attempt (all `vertical_joint` interfaces at once,
on the 18-volume cluster above) produced a `Matrix Singular` failure under
self-weight alone, read at the time as a real mechanism (too many walls
released from each other). **That reading turned out to be incomplete**:
building and verifying the full-aggregate run above surfaced a genuine
node-substitution bug in `TclWriter.solid_elements` that independently
produced the identical failure mode - see
{doc}`../developer_guide/task_a_interfaces` for the full account,
including why the 2-interface case converging doesn't actually prove the
underlying model was sound at 29. With the bug fixed, the full-aggregate
run above shows 11 interfaces - more than the earlier "2 is safe, more
fails" conclusion suggested - converging cleanly; extending the selection
further, and re-checking convergence after each addition, remains
worthwhile practice, just no longer backed by that specific data point.

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
