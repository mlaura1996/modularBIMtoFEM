# Task C — the Docker image

Files: `docker/opensees/Dockerfile`, `run_analysis.sh`, `README.md`.
Implements PROJECT_BRIEF.md §7: OpenSeesMP + MPI + MUMPS, portable between
the development laptop and the (still unspecified — see
{doc}`../case_study/open_questions`) run workstation, and, per the brief's
own framing (§7.1, point 3), "a reproducibility result in itself."

## Two-stage build

- **Builder** (`ubuntu:24.04`): compiles MUMPS
  (`OpenSees/mumps` fork, pinned commit) then OpenSeesMP from source
  (tag `v3.8.0`, target `OpenSeesMP`).
- **Runtime** (`condaforge/miniforge3:25.3.1-0`): copies only the resulting
  binary and its shared-library dependencies — not the compiler toolchain —
  and installs `ifcopenshell`/`pythonocc-core` via `conda` (not readily
  pip-installable on Windows, which is why the runtime base is a
  conda-forge image rather than a plain Python one), plus
  `gmsh`/`apeGmsh`/`numpy`/`pandas` via `pip`.

Per brief §7.3: every component is pinned (base images, OpenSees tag,
MUMPS commit, apeGmsh commit) so the image doesn't silently drift, and
input data (geometry, records, selections, results) is mounted, not baked
in, so a run can be repeated with different inputs without rebuilding.

## The Ubuntu-release trap

OpenSeesMP built against Ubuntu 22.04 links `libscalapack-openmpi.so.2.1`;
Ubuntu 24.04 only ships `.so.2.2` — different SONAME, so copying the
compiled binary across a builder/runtime release mismatch fails at
container-run time with a "cannot open shared object file" error, even
though a `scalapack` package **is** installed in the runtime stage. Found
by actually hitting it, not by reading documentation. Fixed by pinning
both stages to the same Ubuntu release. If either base image is ever
bumped, both stages need rebuilding and the smoke test below needs
re-running before trusting the result again.

## Entrypoint

`run_analysis.sh <NP> <model.tcl> [extra tcl args...]` — process count is
always an argument, never hard-coded, per brief §7.3 ("make the number of
MPI processes a parameter... it differs between the two machines"). Every
invocation writes `output/run_logs/<timestamp>_np<N>.log` with wall-clock
time, peak memory (`Maximum resident set size`, from GNU `time -v`),
process count, hostname, and CPU count — the specific measurements brief
§7.4 asks Chapter 7 to report for every run, framed there as "a deliverable
... not a by-product."

## Verified

A minimal `FourNodeTetrahedron` static model with `numberer ParallelRCM` +
`system Mumps` converges to the same nodal displacement on every MPI rank,
both compiled directly and through this image's `docker run` entrypoint
with a bind-mounted model file (see `README.md`'s smoke test). Full
Task A/B reconciliation (see {doc}`task_b_parallel`) also runs inside this
image via real `mpirun`.

**Not yet verified**: the full-scale (~279k node / 954k tet) Castelnuovo
mesh, or a run on the actual workstation — its specifications are still an
open question (brief §8, point 7; see {doc}`../case_study/open_questions`).
