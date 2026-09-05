# OpenSeesMP + MUMPS Docker image (Chapter 7 / Task C)

Parallel nonlinear dynamic analysis image: OpenSeesMP over MPI with the
MUMPS parallel direct solver, built from source. Separate from the
top-level `Dockerfile` (which only handles the IFC/STEP/material-DB
extraction route via `stko_exporter.py`) - this one runs the TCL model
files produced by the Task A/B pipeline.

Verified end-to-end (see chat log): a minimal `FourNodeTetrahedron` static
model with `numberer ParallelRCM` + `system Mumps` converges to the same
nodal displacement on every MPI rank, both compiled directly and through
this image's `docker run` entrypoint with a bind-mounted model file.

## What's pinned

| Component | Version / ref |
|---|---|
| Builder base | `ubuntu:24.04` (must match the runtime base's OS - see note below) |
| Runtime base | `condaforge/miniforge3:25.3.1-0` (same as the top-level Dockerfile) |
| OpenSees | tag `v3.8.0` |
| MUMPS (OpenSees/mumps) | commit `ec5f340acabb29dc71c6ffde93b58bdcd04af083` |
| apeGmsh (mlaura1996 fork) | commit `f8826d30c187afbf95f2d7e2569ed563ce49659f` |

**Why builder and runtime must share the same Ubuntu release**: found by
actually hitting it, not by reading docs - OpenSeesMP built against Ubuntu
22.04 links against `libscalapack-openmpi.so.2.1`; Ubuntu 24.04 only ships
`.so.2.2` (different SONAME). Copying the binary across releases fails at
runtime with "cannot open shared object file" even though a compatible
library is installed. If you bump either base image, rebuild both stages
and re-run the smoke test below before trusting the result.

## Build

```bash
# from the repository root
docker build -f docker/opensees/Dockerfile -t modularbimtofem-opensees-mp:dev .
```

Two stages: the builder compiles MUMPS then OpenSeesMP from source
(~5 minutes on a 12-core machine, most of it is OpenSees' own METIS/OTHER
sources - there is no way around this, OpenSeesMP is not distributed as a
package); the runtime stage only copies the resulting binary plus its
shared-library dependencies, so the final image doesn't carry the ~GB of
compiler toolchain.

## Smoke test (before trusting any real run)

```bash
docker run --rm modularbimtofem-opensees-mp:dev --help 2>/dev/null; true
docker run --rm --entrypoint sh modularbimtofem-opensees-mp:dev -c \
    "mpirun --allow-run-as-root -np 2 /usr/local/bin/OpenSeesMP -c 'puts [getNP]'"
```

Should print the OpenSees version banner from 2 processes with no shared-library errors.

## Run a mesh (Task A/B - apeGmsh + gmsh, inside the same image)

```bash
docker run --rm -v "$(pwd)/resources:/app/resources" -v "$(pwd)/output:/app/output" \
    --entrypoint conda modularbimtofem-opensees-mp:dev run -n appenv python castelnuovo_interfaces.py
```

## Run an analysis with N processes

The entrypoint is `run_analysis.sh <NP> <model.tcl> [extra tcl args...]`.
`NP` is never baked into the image - pass whatever the run machine has.

```bash
docker run --rm \
    -v "$(pwd)/output:/app/output" \
    modularbimtofem-opensees-mp:dev \
    6 output/castelnuovo/model.tcl
```

**Windows + Git Bash**: `$(pwd)` gets mangled by MSYS path translation and
silently produces an empty bind mount (found the hard way - the container
saw the image's own `/app/output` instead of the host directory, no error).
Use an explicit Windows-style path instead:

```bash
docker run --rm -v "C:/Users/you/path/to/output:/app/output" modularbimtofem-opensees-mp:dev 6 output/model.tcl
```

or in PowerShell, `${PWD}` (not `$(pwd)`) works directly:

```powershell
docker run --rm -v "${PWD}/output:/app/output" modularbimtofem-opensees-mp:dev 6 output/model.tcl
```

## Retrieve results

Everything under `/app/output` inside the container is the bind-mounted
host `output/` directory - nothing to copy out separately. Every run also
writes `output/run_logs/<timestamp>_np<N>.log`, capturing (per brief 7.4):
wall-clock time, peak memory (`Maximum resident set size`, via GNU `time -v`),
process/partition count, hostname and CPU count. DOF/node/element counts are
whatever the TCL model itself prints - not this wrapper's job.

## What's mounted, not baked in

Per brief 7.3 ("mount data, don't bake it"): the Castelnuovo geometry
(`resources/ifc_examples/castelnuovo/`) and the pipeline code are baked
into the image (small, versioned, part of the reproducibility claim).
Ground motion records, the interface-selection JSON, generated meshes/TCL
files, and all analysis results are expected under `output/` and
`resources/` on the host, mounted at `/app/output` and `/app/resources` -
so a run can be repeated with different inputs without rebuilding.

## Still open (do not assume - see PROJECT_BRIEF.md section 8)

- Not yet verified: this image running the actual ~279k-node/954k-tet
  Castelnuovo mesh, or a run on the workstation (run-machine specs are
  still an open question per the brief - §8 point 7).
- The node-splitting wiring described in
  `core/mesh_generation/wall_interfaces.py` (Task A) is not yet connected
  to `core/opensees_generation/model_builder.py`'s element creation, so
  there is no full TCL model to test this image against yet beyond the
  hand-written smoke test above.
