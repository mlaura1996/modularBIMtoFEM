# The Docker image

Full reference: `docker/opensees/README.md` in the repository (kept as the
canonical, always-up-to-date source; this page is the narrative version).

## What's pinned

| Component | Version / ref |
|---|---|
| Builder base | `ubuntu:24.04` |
| Runtime base | `condaforge/miniforge3:25.3.1-0` |
| OpenSees | tag `v3.8.0`, built with target `OpenSeesMP` |
| MUMPS (OpenSees/mumps fork) | commit `ec5f340acabb29dc71c6ffde93b58bdcd04af083` |
| apeGmsh (mlaura1996 fork) | commit `f8826d30c187afbf95f2d7e2569ed563ce49659f` |

Builder and runtime **must** share the same Ubuntu release. OpenSeesMP built
against Ubuntu 22.04 links `libscalapack-openmpi.so.2.1`; 24.04 only ships
`.so.2.2` (different SONAME) — copying the binary across releases fails at
runtime with a "cannot open shared object file" error even though a
compatible library is installed. If you bump either base image, rebuild
both stages and re-run the smoke test below.

## Build

```bash
# from the repository root
docker build -f docker/opensees/Dockerfile -t modularbimtofem-opensees-mp:dev .
```

Two stages: the builder compiles MUMPS then OpenSeesMP from source; the
runtime stage only copies the resulting binary and its shared-library
dependencies, so the final image doesn't carry the compiler toolchain.

## Smoke test — run this before trusting any real run

```bash
docker run --rm --entrypoint sh modularbimtofem-opensees-mp:dev -c \
    "mpirun --allow-run-as-root -np 2 /usr/local/bin/OpenSeesMP -c 'puts [getNP]'"
```

Should print `2` from both ranks with no shared-library errors.

## Run the Python side (IFC, mesh, interfaces — Task A/B)

```bash
docker run --rm -v "C:/path/to/repo:/app" --entrypoint sh \
    modularbimtofem-opensees-mp:dev -c "conda run -n appenv python <script>"
```

This is the invocation used throughout development and testing — the whole
repository is bind-mounted at `/app` so code changes on the host are picked
up without rebuilding.

## Run a parallel analysis (Task C)

The default entrypoint is `run_analysis.sh <NP> <model.tcl> [extra tcl args...]`.
`NP` is never baked into the image.

```bash
docker run --rm \
    -v "C:/path/to/repo/output:/app/output" \
    modularbimtofem-opensees-mp:dev \
    6 output/castelnuovo/model.tcl
```

```{note}
**Windows + Git Bash**: `$(pwd)` is mangled by MSYS path translation and
silently produces an *empty* bind mount — the container sees the image's
own `/app/output` instead of the host directory, with no error. Use an
explicit Windows-style path (as above), or in PowerShell, `${PWD}` works
directly: `docker run --rm -v "${PWD}/output:/app/output" ...`.
```

## Retrieve results

Everything under `/app/output` in the container is the bind-mounted host
`output/` directory. Every run also writes
`output/run_logs/<timestamp>_np<N>.log`, capturing wall-clock time, peak
memory (`Maximum resident set size`), process/partition count, hostname and
CPU count — the measurements the brief asks Chapter 7 to report for every
run (§7.4).

## What's mounted vs. baked in

The Castelnuovo geometry (`resources/ifc_examples/castelnuovo/`) and the
pipeline code are baked into the image. Ground motion records, the
interface-selection JSON, generated meshes/TCL files, and all analysis
results live under `output/` and `resources/` on the host, so a run can be
repeated with different inputs without rebuilding.

## Not yet verified

- Running the actual full-scale Castelnuovo mesh (~279k nodes / 954k tets)
  inside this image.
- A run on the workstation described in PROJECT_BRIEF.md §7.1 — its
  specifications are still an open question (brief §8, point 7).
