# Task A — wall-to-wall interface selection

Module: `core/mesh_generation/wall_interfaces.py`. Implements
PROJECT_BRIEF.md §5: after the geometry is imprinted (conformal, but not
boolean-unioned — every solid stays separate), decide which touching
wall-to-wall pairs become `ZeroLengthContactASDimplex` joints, and split the
shared nodes so the two sides can move independently.

## Why semi-automatic

Deciding which party walls separate distinct structural units is a
judgement about the building's construction history — not reliably
readable from the IFC. The brief's own design choice (§5, option (b) over
(a)): a numbered terminal table, not a viewer click-through. Cheaper to
build, and sufficient — implemented as-is, viewer selection was never
started.

## `InterfaceDetection`

- `find_touching_surface_pairs(volume_tags=None, min_area=1e-4)` — from the
  imprinted geometry, finds all touching wall-body pairs and computes each
  shared interface's area, centroid, and normal. The `min_area` filter
  exists specifically to exclude the ~62 vertex/edge-only touching pairs
  the brief flags (§3.3, §5.1) — zero contact area, would produce
  degenerate elements.
- `classify_orientation(candidates, horizontal_normal_tol=0.3,
  vertical_normal_tol=0.9)` — labels each candidate (`vertical_joint`,
  `oblique`, ...) from its normal vector, so the CLI table and the default
  selection filter can be orientation-aware.

## `InterfaceSelection`

- `key_for(candidate)` — a stable key built from the volume-pair *and*
  centroid. Volume pair alone collides: 144 of Castelnuovo's touching pairs
  touch at more than one location, so `volA-volB` silently dropped
  interfaces on reload before this was found.
- `present_cli(candidates, default_include=("vertical_joint", "oblique"))`
  — the numbered table (pair, area, centroid, normal) from brief §5.2(b).
- `save`/`load_selected` — JSON, keyed by `key_for`, so re-running with an
  existing selection file is non-interactive (brief §5.3 — the analysis
  will be run many times).
- `select_interactive_or_cached(candidates, path)` — the entry point: loads
  a cached selection if `path` exists, otherwise runs the CLI and saves it.

## `ContactInterfaceGenerator`

- `tag_physical_groups(selected)` — declares a Gmsh physical group per
  selected interface surface, so mesh queries can address it by name.
- `get_nodal_tributary_areas(surface_tag)` — per-node tributary area on an
  interface surface, needed to scale Kn/Kt per brief §4.2 (not optional —
  it's what makes the contact response mesh-independent).
- `generate(selected, Kn_nominal, Kt_nominal, mu=0.6, int_type=1,
  get_new_ops_element_tag=None)` — emits one `zeroLengthContactASDimplex`
  element per split node pair, Kn/Kt scaled by tributary area, normal taken
  from the interface's own geometry (**not** hard-coded to global X — the
  brief is explicit, §4.2, that Castelnuovo has joints in several
  directions, unlike the single-joint Chapter 6 specimen).

## `NodeSplitter`

- `TAG_OFFSET = 10_000_000` — duplicate node tags are the original tag plus
  this offset; kept far above any expected node count so collisions with
  real mesh nodes are structurally impossible, not just unlikely.
- `assign_split_side(selected)` — for each selected interface, decides
  which of the two touching volumes keeps the original nodes and which
  gets duplicates.
- `compute_node_map(gmshmodel, selected)` — pure function, returns
  `{volume_tag: {original_node: duplicate_node}}}`. Deliberately pure (no
  OpenSees/gmsh node creation side effects) so it can be reused by both the
  direct-openseespy path (`create_duplicate_nodes`) and the TCL path
  (`TclWriter.duplicate_nodes`) without duplicating the mapping logic.
- `create_duplicate_nodes(gmshmodel, selected)` — the openseespy-side
  consumer: actually creates the duplicate nodes via `ops.node(...)`.

## Real problems hit building this

**Node tag collisions across interfaces.** A node shared by two or more
selected interfaces (common at a T-junction of three walls) computed the
same duplicate tag from more than one caller, which OpenSees/TCL rejected
as "node already exists." Fixed with deduplication sets in
`NodeSplitter`, `TclWriter.duplicate_nodes`, and `TclWriter.contact_elements`
— all three needed the fix independently since none of them shared state
with the others before this.

**Selecting every candidate interface produced an unstable mechanism.**
With 39 candidate interfaces at the vertical joints, selecting all 29
`vertical_joint`-classified ones (rather than a conservative subset) made
the self-weight static analysis fail with `Matrix Singular` — not a bug in
the selection or generation code, a real modelling consequence: enough
walls were released from each other that part of the structure became a
mechanism under gravity alone. Reducing to 2 conservative interfaces
converged cleanly. This is the practical shape of the brief's warning (§5,
intro) that interface selection is "an engineering judgement," not a
detail to automate away — a selection that looks more "correct" (every
real joint modelled as a joint) can be less usable for a first converging
model. See {doc}`../case_study/overview` for how many interfaces the
current Castelnuovo selection actually uses.
