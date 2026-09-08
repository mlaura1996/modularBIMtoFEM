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

## Local conda environment for Task A interface selection

Neither of the two environments above can open a GUI window or (for the
Docker image) run matplotlib to a file conveniently: visually inspecting
where the Task A candidate wall-to-wall interfaces actually are on the
building needs a real window, on the host, not in a container.

```bash
conda create -y -n castelnuovo_viewer -c conda-forge python=3.10.12 pip ifcopenshell pythonocc-core
conda activate castelnuovo_viewer
pip install gmsh numpy pandas matplotlib openseespy lark apeGmsh
```

Same `ifcopenshell`/`pythonocc-core`/Python-3.10 recipe as the Docker
image's runtime stage (`docker/opensees/Dockerfile`), just installed
locally with plain `conda`/`pip` instead of inside a container — apeGmsh
itself requires Python ≥ 3.10. `openseespy`/`lark` are only needed
because `core/config.py` imports them at module load time even for
geometry-only scripts - not because anything in this environment actually
runs OpenSees.

```{note}
Windows + Anaconda: if `conda create` fails with `CondaSSLError:
OpenSSL appears to be unavailable`, the base environment's own
`Library\bin` (which carries its OpenSSL DLLs) isn't on `PATH`. Fix:
`$env:PATH = "<conda root>\Library\bin;<conda root>\Scripts;" + $env:PATH`
before running `conda`, or use an "Anaconda Prompt" shortcut, which sets
this up automatically.
```

```{note}
**Do not add PySide2/PySide6/pyvista/pyvistaqt to this environment** for
apeGmsh's interactive `MeshViewer` (`inspect_interfaces_apegmsh.py`) -
real time was spent trying, without success, on Windows: PySide6
collides with a Qt6 (`qt6-main`) conda-forge pulls in as a transitive
`pythonocc-core` dependency (`ImportError: DLL load failed while
importing QtCore`); switching to PySide2 avoids that collision but hits
`pyvistaqt`'s Qt-embedded VTK render surface coming up a literal
transparent hole (confirmed not an occlusion or missing-data issue -
plain, non-Qt-embedded PyVista renders fine on the same machine);
`QT_OPENGL=angle` crashes outright (`eglError: 3005`,
`QOpenGLContext.getProcAddress` missing from this PySide2 build);
`QT_OPENGL=software` still renders the same transparent hole; rebuilding
the whole environment with conda-forge's own `pyside2` build (rather than
pip's) to get a more complete Qt binding hit conda's classical solver
hanging for 30-50+ minutes (repeatedly), then, once switched to
`micromamba` for a fast solve, a `gdk-pixbuf` post-link script crashing
(`ffi.dll` not found) on every attempt regardless of install path length.
`inspect_interfaces_apegmsh.py` is kept in the repo as-is, documenting
exactly what was tried, in case a future environment doesn't hit the same
Windows-specific packaging issues - it is **not** the recommended path.
```

The recommended path instead - two scripts, both on the repaired
geometry (`resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp` -
see `scripts/repair_step_geometry.py` for how it was produced from a
slab-free IFC), agreeing on the same candidate numbering (same detection
order, same `MIN_VOLUME_M3` door/window-frame filter in both scripts -
**not** the real, much slower IFC-type point-in-solid classifier in
`core/ifc_processing/ifc_step_matching.py`, which took several minutes
here):

```bash
python scripts/plot_candidate_interfaces.py   # matplotlib PNG, numbered, headless - look at this first
python scripts/inspect_interfaces.py          # gmsh's native GUI - confirm a selection by number
```

`plot_candidate_interfaces.py` writes
`output/castelnuovo/plots/candidate_interfaces_overview.png` - a numbered
point per candidate interface's centroid, over a cheap wall-centroid
"silhouette" for spatial orientation. Look at it, note the numbers you
want. `inspect_interfaces.py` then opens gmsh's own GUI with every
candidate tagged as its own numbered physical group (the same numbers as
the PNG); tick/untick each `IF_###` checkbox in the "Physical groups"
panel (List tab) - visible when you close the window = selected. It
prints what was captured and offers a manual index/range override as a
safety net, then saves to
`resources/survey_data/castelnuovo/interface_selection.json` for reuse by
the Docker-based scripts via `InterfaceSelection.select_interactive_or_cached()`.

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
