# Running the pipeline end to end

This walks through the full route — IFC → geometry/material extraction →
mesh + partition → interface selection → TCL export → OpenSeesMP — using
the same steps proven in `docker/opensees/test_task_ab_reconciled.py`
(a real, passing regression test, not a hypothetical). All commands run
inside the Docker image (see {doc}`docker_image`).

## 1. IFC → STEP + material database

Chapter 4-era stage, unchanged by this chapter's work — see
{doc}`../developer_guide/architecture` for what it produces. For
Castelnuovo, the prepared geometry (already cleaned, imprinted, and
verified — 316 solids, 663.71 m³) ships in the repository at
`resources/ifc_examples/castelnuovo/final_example_PRONTO.stp`, so this step
does not need to be re-run to reproduce the case study.

## 2. Mesh (apeGmsh) - not partitioned yet

```python
from apeGmsh import apeGmsh
import gmsh

with apeGmsh(model_name="castelnuovo") as g:
    g.mesh.sizing.set_size_sources(from_points=False)
    g.model.io.load_step("resources/ifc_examples/castelnuovo/final_example_PRONTO.stp")
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()
    all_vols = gmsh.model.getEntities(3)
    g.parts.from_model("castelnuovo")
    g.physical.add_volume([t for _, t in all_vols], name="Masonry")
    g.mesh.sizing.set_global_size(0.5)              # metres
    g.mesh.generation.generate(dim=3)
```

```{note}
Use raw `gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])` for
conformal interfaces, not apeGmsh's `make_conformal()` — the latter breaks
meshing on this geometry (Tetgen PLC error) and its default tolerance is
calibrated for millimetre-scale models, not this metre-scale one. See
{doc}`../developer_guide/task_b_parallel`.
```

**Don't partition yet** — `g.mesh.partitioning.partition()` mutates
gmsh's element/entity bookkeeping in a way that breaks both
`InterfaceDetection.find_touching_surface_pairs()` and
`gmsh.model.mesh.getElements(dim=3, tag=vol)` afterward (found the hard
way — see {doc}`../developer_guide/task_a_interfaces`). Everything in
step 3 below must run first.

## 3. Task A — select wall-to-wall interfaces

Which candidate interfaces to select is an engineering judgement (see
{doc}`../developer_guide/task_a_interfaces` for why, and a real case where
selecting too many produced an unstable mechanism) — make that decision
once, locally, with `scripts/select_interfaces_gui.py`
({doc}`installation`'s recommended path, screenshots and implementation
notes in {doc}`../developer_guide/task_a_interfaces`), **before** running
this step in Docker. It saves to
`resources/survey_data/castelnuovo/interface_selection.json`; everything
below just loads that file back.

```python
from core.mesh_generation.wall_interfaces import (
    InterfaceDetection, InterfaceSelection, ContactInterfaceGenerator, NodeSplitter,
)

candidates = InterfaceDetection.find_touching_surface_pairs()
InterfaceDetection.classify_orientation(candidates)

selected = InterfaceSelection.select_interactive_or_cached(
    candidates, path="resources/survey_data/castelnuovo/interface_selection.json"
)
ContactInterfaceGenerator.tag_physical_groups(selected)
substitution = NodeSplitter.compute_node_map(gmsh.model, selected)

# Also before partition(), for the same reason - TclWriter.solid_elements()
# (step 5) needs this to scope node substitution to each interface's own
# split_volume; computed too late (i.e. inside solid_elements() itself,
# after partitioning), gmsh.model.mesh.getElements() silently returns
# empty and nothing gets substituted at all (see
# {doc}`../developer_guide/task_a_interfaces`).
split_element_ids = set()
for vol in substitution:
    _etypes, etags, _enodes = gmsh.model.mesh.getElements(dim=3, tag=vol)
    for tags in etags:
        split_element_ids.update(int(t) for t in tags)
```

The first run prompts on the terminal (a numbered table: pair, area,
centroid, normal — see {doc}`../developer_guide/task_a_interfaces`); the
selection is saved to the given path, and every subsequent run with the
same path is non-interactive. **Be deliberate about which interfaces you
select as contact joints**: selecting every candidate interface can produce
a mechanism that is unstable under self-weight alone (a real result hit
during development — see {doc}`../developer_guide/task_a_interfaces` for
the full account, including a genuine implementation bug that turned out
to produce the identical failure mode).

## 4. Partition and get the FEM data

```python
    info = g.mesh.partitioning.partition(n_parts=6)
    fem = g.mesh.queries.get_fem_data(dim=3)
```

Only now — after detection, selection, and `split_element_ids` above are
all done.

## 5. Export TCL and write the model

```python
from core.opensees_generation.tcl_export import TclWriter

writer = TclWriter(ndm=3, ndf=3)
writer.header()
writer.nodes(fem)
writer.duplicate_nodes(gmsh.model, selected)
writer.material_asdconcrete3d(mat_tag, E, nu, Te, Ts, Td, Ce, Cs, Cd, lch)
for rank in range(6):
    writer.solid_elements(fem, "Masonry", mat_tag, rank,
                           body_force=(0.0, 0.0, -rho * 9.81),
                           node_substitution=substitution,
                           split_element_ids=split_element_ids)
writer.contact_elements(fem, selected, Kn_nominal=69000.0e9, Kt_nominal=0.001e9)
writer.fix(fem, "Fixed", dofs=[1, 1, 1])
writer.analysis_static_gravity(n_steps=10)
writer.write("output/castelnuovo/model.tcl")
```

A complete, verified version of steps 2-5 above (the full 279-volume
aggregate, cleaned geometry, a real interactively-selected interface set)
is `docker/opensees/full_aggregate_with_interfaces_clean.py` — converges
on all 6 ranks, 0.028% self-weight/reaction balance error. See
{doc}`../case_study/overview` for the numbers and
{doc}`../developer_guide/task_a_interfaces` for what building it surfaced.

## 6. Run with OpenSeesMP

```bash
docker run --rm -v "C:/path/to/repo/output:/app/output" \
    modularbimtofem-opensees-mp:dev 6 output/castelnuovo/model.tcl
```

`6` above is the process count — match it to the number of partitions
requested in step 4, and to what the run machine actually has (see
{doc}`../case_study/open_questions`, run-machine specification is still
unresolved for the full-scale model).

## Materials from survey data

If a material's mechanical properties aren't in the IFC (Castelnuovo's
four masonry types aren't), derive them from morphological survey data
before step 2:

```bash
docker run --rm -v "C:/path/to/repo:/app" --entrypoint sh \
    modularbimtofem-opensees-mp:dev -c \
    "conda run -n appenv python docker/opensees/castelnuovo_hmo_graph.py"
```

writes `output/castelnuovo/material_database.json`, then:

```python
from utils.dict_helper import load_material_objects
materials = load_material_objects("output/castelnuovo/material_database.json")
```

gives the `{name: Material}` dict `Element.add_elements_to_opensees`
expects. Full derivation method in {doc}`../case_study/materials`.
