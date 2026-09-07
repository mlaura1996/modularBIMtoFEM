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
pip install gmsh numpy pandas matplotlib "apeGmsh[viewer] @ git+https://github.com/mlaura1996/apeGmsh.git@f8826d30c187afbf95f2d7e2569ed563ce49659f"
```

Same `ifcopenshell`/`pythonocc-core`/Python-3.10 recipe as the Docker
image's runtime stage (`docker/opensees/Dockerfile`), just installed
locally with plain `conda`/`pip` instead of inside a container — apeGmsh
itself requires Python ≥ 3.10, so an existing older environment (e.g. one
built for a different project, on Python 3.8) won't work even if it
already has `ifcopenshell`/`pythonocc-core`.

```{note}
Windows + Anaconda: if `conda create` fails with `CondaSSLError:
OpenSSL appears to be unavailable`, the base environment's own
`Library\bin` (which carries its OpenSSL DLLs) isn't on `PATH`. Fix:
`$env:PATH = "<conda root>\Library\bin;<conda root>\Scripts;" + $env:PATH`
before running `conda`, or use an "Anaconda Prompt" shortcut, which sets
this up automatically.
```

Then:

```bash
python scripts/inspect_interfaces.py
```

Loads the Castelnuovo geometry, detects every candidate wall-to-wall
interface (`core.mesh_generation.wall_interfaces.InterfaceDetection` —
the exact same code the Docker-based analysis scripts use, so a selection
made here is directly compatible with them), tags each one as its own
numbered physical group, and opens gmsh's own GUI (`gmsh.fltk.run()`) so
you can toggle each candidate's visibility by name and see exactly where
it is. After closing the window, it prints the same numbered table
`InterfaceSelection.present_cli()` always has and asks which interfaces to
confirm, then saves the selection to
`resources/survey_data/castelnuovo/interface_selection.json` for reuse by
the Docker-based scripts.

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
