# Installation

There are two ways to get a working environment, and which one you want
depends on what you're doing.

## Docker image (recommended for anything past IFC/mesh exploration)

The `docker/opensees/Dockerfile` image bundles everything: IfcOpenShell,
OpenCASCADE (pythonocc-core), Gmsh + apeGmsh, and OpenSees built with
**OpenSeesMP + MPI + MUMPS**. This is the only environment the parallel
analysis (Task B/C) actually runs in — OpenSeesPy in parallel does not work
for this project (see {doc}`../developer_guide/task_c_docker`), so there is
no "just pip install openseespy" path for that part.

```bash
# from the repository root
docker build -f docker/opensees/Dockerfile -t modularbimtofem-opensees-mp:dev .
```

Takes a few minutes — most of it is compiling OpenSeesMP from source, which
only needs to happen once per image build. See
{doc}`docker_image` for the full build/run/smoke-test instructions.

## Local Python environment (IFC extraction, quick scripts only)

`requirements.txt` at the repository root currently lists only
`gmsh`, `openseespy`, and `lark` — it does **not** include
`ifcopenshell`, `pythonocc-core`, `numpy`, `pandas`, or `matplotlib`, all of
which `core/config.py` imports at module load time. A plain
`pip install -r requirements.txt` will not get you a runnable environment
for the IFC/geometry stage; see
{doc}`../developer_guide/known_issues` for the exact gap. Until that's
fixed, the reliable path for anything touching `core/config.py`'s imports is
the Docker image above, which installs `ifcopenshell` and
`pythonocc-core` via `conda` (they are not readily pip-installable on
Windows).

## Local conda environment with the interactive viewer (Task A visual selection)

Neither of the two environments above can open a GUI window: the Docker
image is headless (deliberately excludes apeGmsh's `viewer` extra —
PySide6/pyvista/vtk — per brief 7.2, not needed for the run image), and
plain `pip install -r requirements.txt` doesn't reach `ifcopenshell`/
`pythonocc-core` at all (previous section). Visually inspecting where the
Task A candidate wall-to-wall interfaces actually are on the building
(instead of only reading their area/centroid/normal off a text table)
needs a real window, on the host, not in a container.

```bash
conda create -y -n castelnuovo_viewer -c conda-forge python=3.10.12 pip ifcopenshell pythonocc-core
conda activate castelnuovo_viewer
pip install gmsh numpy pandas matplotlib openseespy lark apeGmsh
pip install PySide2 pyvistaqt pyvista
```

Same `ifcopenshell`/`pythonocc-core`/Python-3.10 recipe as the Docker
image's runtime stage (`docker/opensees/Dockerfile`), just installed
locally with plain `conda`/`pip` instead of inside a container — apeGmsh
itself requires Python ≥ 3.10, so an existing older environment (e.g. one
built for a different project, on Python 3.8) won't work even if it
already has `ifcopenshell`/`pythonocc-core`. `openseespy`/`lark` are only
needed because `core/config.py` imports them at module load time even for
geometry-only scripts (`utils/dict_helper` etc. pull in `core.config`
transitively) - not because anything in this environment actually runs
OpenSees.

```{note}
Windows + Anaconda: if `conda create` fails with `CondaSSLError:
OpenSSL appears to be unavailable`, the base environment's own
`Library\bin` (which carries its OpenSSL DLLs) isn't on `PATH`. Fix:
`$env:PATH = "<conda root>\Library\bin;<conda root>\Scripts;" + $env:PATH`
before running `conda`, or use an "Anaconda Prompt" shortcut, which sets
this up automatically.
```

```{note}
**Use `PySide2`, not `PySide6`** for apeGmsh's interactive `MeshViewer`
(`apeGmsh[viewer]`'s own default extra pulls PySide6). On Windows, a
conda-forge `pythonocc-core` install pulls in its own native Qt6
(`qt6-main`) as a transitive dependency; PySide6 bundles a *different*
build of the same Qt6 DLLs (e.g. `Qt6Core.dll`) under `site-packages`,
and the two collide - `import PySide6.QtCore` (and, one level up,
`import qtpy`) fails with `ImportError: DLL load failed while importing
QtCore: The specified procedure could not be found.` `os.add_dll_directory`
pointed at PySide6's own folder does **not** fix it (tried). PySide2 is
Qt5-based (`Qt5Core.dll`, a different name from `Qt6Core.dll`), so it
doesn't collide with `qt6-main` at all - confirmed working by actually
constructing apeGmsh's `ViewerWindow`, not just importing the binding.
```

Then, either of two scripts, both loading the same repaired geometry
(`resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp` - see
`scripts/repair_step_geometry.py` for how it was produced from a
slab-free IFC) and both saving to
`resources/survey_data/castelnuovo/interface_selection.json` for reuse by
the Docker-based scripts via `InterfaceSelection.select_interactive_or_cached()`:

```bash
python scripts/inspect_interfaces.py           # gmsh's native GUI, list-based
python scripts/inspect_interfaces_apegmsh.py    # apeGmsh's viewer, click-to-pick in 3D
```

Both detect every candidate wall-to-wall interface
(`core.mesh_generation.wall_interfaces.InterfaceDetection` - the exact
same code the Docker-based analysis scripts use) and exclude slabs/
windows/doors by default, using the original IFC element types recovered
via `core.ifc_processing.ifc_step_matching` (the STEP geometry itself
carries no such label). They differ only in the selection UI:
`inspect_interfaces.py` tags each candidate as a physical group and reads
back which ones are left **visible** (toggle checkboxes in the "Physical
groups" panel) when the gmsh window closes;
`inspect_interfaces_apegmsh.py` opens apeGmsh's own PyVista/VTK viewer in
"brep" pick mode - click a surface to select it, ctrl+click to deselect,
and the script reads back `MeshViewer.tags` when the window closes. Both
print what was captured and offer a manual index/range override as a
safety net.

## Repository layout at a glance

```text
core/                     # IFC parsing, mesh generation, OpenSees generation
  ifc_processing/         #   IFC -> STEP + material database
  mesh_generation/        #   Gmsh meshing, wall-to-wall interface detection (Task A)
  opensees_generation/    #   model_builder.py (element creation), tcl_export.py (Task B)
external/gmsh2opensees/   # STKO-era gmsh -> OpenSees bridge (Chapter 4, kept for reference)
models/                   # constitutive-law helper formulas (damage_law.py, ...)
utils/                    # shared helpers (dict/gmsh/math/string, tag numbering)
docker/opensees/          # Task C image, run script, README, and the standing
                           #   regression test scripts (test_*.py)
scripts/                  # local (non-Docker) interactive tools, e.g. inspect_interfaces.py
resources/                # input data: IFC/STEP geometry, survey data, ontologies-derived JSON
output/                   # generated artefacts: TCL models, material DB, run logs
docs/                     # this documentation site
main.py, in_plane_wall.py, out_of_plane_test.py   # Chapter 4/6-era entry points (kept working)
```
