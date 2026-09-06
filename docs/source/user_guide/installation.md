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
resources/                # input data: IFC/STEP geometry, survey data, ontologies-derived JSON
output/                   # generated artefacts: TCL models, material DB, run logs
docs/                     # this documentation site
main.py, in_plane_wall.py, out_of_plane_test.py   # Chapter 4/6-era entry points (kept working)
```
