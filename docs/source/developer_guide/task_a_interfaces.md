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
build, and sufficient as the entry point every Docker-based script still
uses (`InterfaceSelection.select_interactive_or_cached`) — but picking
interfaces from a bare table of areas/centroids/normals, with no picture
of the building, turned out to be hard to do with any confidence on a
279-volume aggregate. `scripts/select_interfaces_gui.py` (below) is the
viewer click-through the brief's option (a) originally passed over — built
later, once the table alone proved impractical at this geometry's scale,
and layered on top of the same `InterfaceDetection`/`InterfaceSelection`
classes rather than replacing them: it writes the exact same
`interface_selection.json` format, so anything reading a saved selection
(the CLI path included) doesn't know or care which tool produced it.

## Interactive selection tool (`select_interfaces_gui.py`)

Run locally (not in Docker — see {doc}`../user_guide/installation`'s
`castelnuovo_viewer` conda environment):

```bash
conda activate castelnuovo_viewer
python scripts/select_interfaces_gui.py
```

It detects candidates the same way as the CLI path above, renders the
real building geometry with every default-visible candidate (vertical
joints between two wall-sized volumes) numbered and highlighted in red,
and opens a tkinter window: the picture on the left, a scrollable
yes/no checklist on the right — one row per numbered candidate,
pre-checked to match the CLI's own default filter.

```{figure} ../_static/images/task_a_gui_selection.png
:alt: select_interfaces_gui.py main window — numbered building render on the left, a scrollable checklist of candidate interfaces on the right
:width: 100%

Main window: the building rendered at three selectable camera angles
(`Vista 1/2/3` buttons, bottom-left), candidate interfaces numbered and
highlighted in red, a checkbox per candidate on the right (ticked =
export as a contact interface).
```

Clicking **"Save && preview selection"** writes
`resources/survey_data/castelnuovo/interface_selection.json` immediately
(in the same format `InterfaceSelection.save`/`.load_selected` and the
Docker-based scripts already expect), then re-renders the same building
showing *only* the interfaces just selected, in a second window, as a
visual confirmation before closing the app:

```{figure} ../_static/images/task_a_gui_confirm.png
:alt: the confirm-selection popup, showing only the interfaces that were ticked
:width: 100%

Confirmation popup after "Save && preview selection" — only the ticked
interfaces are drawn, numbered the same way as the main window, so a
mistaken tick is obvious before the analysis scripts ever run.
```

Implementation notes for anyone touching this script:

- **Candidate numbers are stable across tools** - `select_interfaces_gui.py`,
  `plot_candidate_interfaces.py`, and `inspect_interfaces.py` all detect
  candidates on the same, full, unfiltered volume set in the same order
  (`InterfaceDetection.find_touching_surface_pairs()` then
  `classify_orientation()`), so a number written down from one script's
  output means the same interface in another.
- **The gmsh session is kept alive for the whole app run**, not reloaded
  per render - loading + fragmenting the STEP geometry (~14s) is cached to
  a `.brep` file (`output/castelnuovo/cache/`, invalidated automatically if
  the source STEP changes) and `gmsh.fltk.initialize()`'s own setup cost is
  paid once. Every view is rendered lazily (only when actually shown, not
  all three up front) and cached per (selection, view) - switching between
  already-rendered views is close to instant.
- **The gmsh window is real but never visible** - `gmsh.fltk.initialize()`
  needs a native window handle for its OpenGL context (this build has no
  true headless mode), so it's moved off-screen and shrunk to 50x50px
  before creation (`General.GraphicsPositionX/Y`, `...Width/Height`)
  instead of ever appearing where you'd see it.
- **A real gmsh quirk, found while building this**: only the *first*
  `gmsh.write()` after `gmsh.fltk.initialize()` honors `Print.Width`/
  `Print.Height` - every later write in the same session silently drops to
  a smaller, screen-derived size, no matter how many times those options
  are re-set beforehand. Reproduced with no Tkinter involved at all, so
  it's a gmsh behaviour, not an artifact of mixing GUI toolkits. Fixed by
  a genuine `gmsh.fltk.finalize()` + `gmsh.fltk.initialize()` cycle before
  every `gmsh.write()` call (~0.7-1s each here, since the window is
  tiny/off-screen — see above). Also applied in
  `plot_candidate_interfaces.py`'s two-image loop, which had the exact
  same bug silently producing a lower-resolution "iso" image than "plan"
  ever since it was written.
- **Overlapping number labels get a small offset + leader arrow**
  (`declutter_positions()` in the script) when several candidates' true
  centroids fall within ~0.6m of each other - common at an L-shaped wall
  junction, see `InterfaceSelection.key_for`'s docstring: 144 of
  Castelnuovo's candidates are volume pairs that touch at more than one
  separate patch. A 3D-domain approximation, not true screen-space
  collision avoidance (that would need replicating gmsh's camera
  projection) — good enough in most views; the very densest corner
  clusters (10+ candidates within ~1m) are still only really legible by
  zooming into that area in the app.

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
