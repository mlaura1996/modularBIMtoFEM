# Open questions

PROJECT_BRIEF.md §8 is explicit: "do not guess" on these. Status of each,
as of the current branch.

```{list-table}
:header-rows: 1
:widths: 30 70

* - Question (brief §8)
  - Status
* - 1. Material parameters — Chapter 6 values or a separate characterisation?
  - **Resolved**: separate characterisation from survey data via HMO/MQI — see {doc}`materials`.
* - 2. Slabs — solids with masonry properties, a different material, or mass?
  - **Open.** Not decided or implemented. Slabs are meshed as solids in the
    prepared geometry but nothing in the Task A/B/C pipeline assigns them a
    treatment yet.
* - 3. Seismic input — which record, scaling, duration?
  - **Open.** Chapter 6's Run 2.1 (shake-table campaign) does not transfer
    to a real building; no replacement chosen.
* - 4. Boundary conditions — fixed base at z = −1.50 m?
  - **Open.** Not decided. The Task A/B test scripts fix an entire
    arbitrarily-chosen volume's nodes as a stand-in "ground" side for
    verification purposes only — not a foundation model.
* - 5. Windows/doors — structurally relevant, or structure-only geometry?
  - **Open**, though the brief itself leans toward structure-only ("probably
    what the analysis should use"). Not implemented either way; the 316-solid
    geometry used so far has not been filtered to exclude the 216 frame solids.
* - 6. Unit subdivision — which walls separate distinct structural units?
  - **Partially addressed.** The HSTO graph's quoin connections
    ({doc}`materials`) encode an inferred subdivision (417/418/419/420),
    but from the cadastral-map row order, not from Task A's own
    independent, geometry-based interface detection — the two have not
    been cross-referenced. Task A's actual interface *selection* used for
    the verified test runs so far is a small, hand-picked conservative
    subset (see {doc}`overview`), not a subdivision decision for the whole
    building.
* - 7. Run machine specifications
  - **Open.** Not asked yet. Needed before partitioning/solver
    configuration can be sized for the full-scale (~279k node) mesh, and
    before the Docker image (§7) can be verified end to end on the
    intended hardware.
```

## Materials/ontology-specific gaps

Documented next to {doc}`materials` in principle, kept here so every open
item is discoverable from one page:

- Type D's classification is unverified by construction (scored by analogy
  to type B — the render was never removed, so the masonry underneath was
  never observed).
- `poisson_ratio = 0.2` for all four types is a literature default, not
  MQI-derived — HMO has no rule for it.
- Mohr-Coulomb shear strength has no source in HMO at all (only
  Turnšek-Čačovič is implemented as a rule) — relevant if the wall-to-wall
  contact interfaces (§4.2, currently μ = 0.6 generic) are ever meant to
  use a masonry-specific friction angle instead.
- The HSTO graph's unit-adjacency order is inferred from a cadastral-map
  excerpt, not checked against the IFC model's own geometry — Task A's
  `InterfaceDetection` does that check independently, on the actual STEP
  geometry, and the two have not been cross-referenced.
- HSTO's `HistoricOpening` inventory is one individual (the type-A door
  arch); the manuscript describes several other opening types (four-light
  15th-century windows, later brick-surrounded rectangular apertures) not
  individually catalogued.

## Pipeline-scale gap

The full-scale Castelnuovo mesh (~279k nodes / 954k tets) has never
actually been run — only subsets up to 18 volumes / 6 partitions (see
{doc}`overview`). This is directly downstream of question 7 above: sizing
partitions and solver configuration for the real analysis needs the run
machine's specifications first.
