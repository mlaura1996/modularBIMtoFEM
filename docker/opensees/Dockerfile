# OpenSeesMP + MUMPS image (Task C, PROJECT_BRIEF.md section 7).
# Separate from the top-level Dockerfile (which serves stko_exporter.py /
# the geometry+material extraction route) - this one is the parallel
# nonlinear dynamic analysis route: OpenSeesMP over MPI with the MUMPS
# parallel direct solver, per Chapter 6/7's STKO reference configuration
# (ParallelRCM numberer, N processes as a parameter, see run_analysis.sh).
#
# Two stages (brief 7.3): this builder compiles MUMPS and OpenSeesMP from
# source (~5 min on 12 cores); the runtime stage copies only the compiled
# binary and its shared-library dependencies, plus the gmsh/ifcopenshell/
# apeGmsh toolchain. See docker/opensees/README.md for build/run commands
# and what's been verified end-to-end so far.

# Same Ubuntu release as the runtime stage's base (condaforge/miniforge3
# 25.3.1-0 is noble/24.04 - verified via its apt sources). Found the hard
# way: building against 22.04 links OpenSeesMP against
# libscalapack-openmpi.so.2.1, but 24.04 only ships .so.2.2 (different
# SONAME) - runtime "cannot open shared object file" even though a
# compatible library is installed under the other version.
FROM ubuntu:24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gfortran \
    cmake \
    git \
    wget \
    ca-certificates \
    libopenmpi-dev \
    openmpi-bin \
    liblapack-dev \
    libblas-dev \
    libscalapack-openmpi-dev \
    libhdf5-openmpi-dev \
    pkg-config \
    tcl-dev \
    tk-dev \
    libeigen3-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# --- MUMPS (pinned commit, per brief: pin versions) ---
ARG MUMPS_COMMIT=ec5f340acabb29dc71c6ffde93b58bdcd04af083
RUN git clone https://github.com/OpenSees/mumps.git mumps \
    && git -C mumps checkout ${MUMPS_COMMIT}
RUN cmake -S mumps -B mumps/build -Darith=d \
    && cmake --build mumps/build --config Release --parallel $(nproc)

# --- OpenSees (pinned tag) ---
ARG OPENSEES_VERSION=v3.8.0
RUN git clone --depth 1 --branch ${OPENSEES_VERSION} https://github.com/OpenSees/OpenSees.git OpenSees

# -DOPENMPI=TRUE and -DSCALAPACK_LIBRARIES are not optional here: without
# them, CMake fails to find MPI on Debian/Ubuntu (github.com/OpenSees/OpenSees
# issue #1101) and the final link fails with undefined references to
# numroc_/blacs_*/pdgetrf_ etc. (MUMPS needs ScaLAPACK/BLACS but OpenSees'
# CMakeLists does not auto-link it) - both found by actually running this
# build and reading the errors, not by guessing.
RUN cmake -S OpenSees -B OpenSees/build \
    -DMUMPS_DIR=/build/mumps/build \
    -DOPENMPI=TRUE \
    -DSCALAPACK_LIBRARIES=/usr/lib/x86_64-linux-gnu/libscalapack-openmpi.so \
    && cmake --build OpenSees/build --target OpenSeesMP --parallel $(nproc)

# Verified (see chat log): mpirun -np N OpenSeesMP correctly reports
# getPID()/getNP() across all N ranks, and a minimal FourNodeTetrahedron
# static model with `numberer ParallelRCM` + `system Mumps` converges to
# the same nodal displacement on every rank.


# ============================================================================
# Runtime stage - slim image with the compiled OpenSeesMP binary plus the
# geometry/meshing/IFC toolchain (brief 7.2/7.3: two stages, mount data
# rather than bake it in, MPI process count as a run-time parameter).
# Reuses the conda-forge route already working in the repo's top-level
# Dockerfile for ifcopenshell + pythonocc-core, for consistency.
# ============================================================================
FROM condaforge/miniforge3:25.3.1-0 AS runtime

# Runtime-only shared libraries. First block is what `ldd OpenSeesMP` (run
# against the builder stage) actually links against - no -dev / compiler
# packages. Second block is the X11/GL stack the pip gmsh wheel needs even
# headless (it bundles FLTK) - same set already proven to work for
# pythonocc-core in the repo's top-level Dockerfile; gmsh needs it too
# (verified here: `import gmsh` failed on libXft.so.2 without it). xvfb is
# for gmsh.fltk.initialize() specifically - it still needs a real X11
# display to create its (off-screen, on the host side - see scripts/
# select_interfaces_gui.py) window, and this container has none at all
# ("Can't open display" - found running docker/opensees/
# full_aggregate_with_interfaces_clean.py's gmsh-screenshot rendering).
# Run under `xvfb-run -a <cmd>` to get one.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libtcl8.6 \
    openmpi-bin \
    libopenmpi3 \
    libscalapack-openmpi2.2 \
    liblapack3 \
    libblas3 \
    libgfortran5 \
    libquadmath0 \
    zlib1g \
    time \
    libglu1-mesa \
    libglx-mesa0 \
    libgl1 \
    libx11-6 \
    libxi6 \
    libfreetype6 \
    fontconfig \
    libxft2 \
    libxinerama1 \
    libxcursor1 \
    libxrender1 \
    libxext6 \
    libsm6 \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/OpenSees/build/OpenSeesMP /usr/local/bin/OpenSeesMP
RUN chmod +x /usr/local/bin/OpenSeesMP

WORKDIR /app

RUN conda install -y mamba -n base -c conda-forge && \
    mamba create -y -n appenv -c conda-forge \
    python=3.10.12 \
    pip \
    ifcopenshell \
    pythonocc-core \
    && conda clean -afy

COPY requirements.txt /app/requirements.txt

ARG APEGMSH_COMMIT=f8826d30c187afbf95f2d7e2569ed563ce49659f
RUN conda run -n appenv python -m pip install --upgrade pip && \
    conda run -n appenv pip install --no-cache-dir -r /app/requirements.txt && \
    conda run -n appenv pip install --no-cache-dir \
        "apeGmsh @ git+https://github.com/mlaura1996/apeGmsh.git@${APEGMSH_COMMIT}" \
        h5py
# apeGmsh's own deps are just gmsh/numpy/pandas (checked its pyproject.toml) -
# the "viewer" extra (PySide6/pyvista/vtk) is deliberately NOT installed here,
# per brief 7.2: not needed in the run image. h5py is added explicitly:
# apeGmsh's Results.from_recorders()/native HDF5 writer imports it
# unconditionally (results/writers/_native.py), but it isn't declared under
# ANY of apeGmsh's own extras (plot/opensees/vtk/dxf/viewer/all - checked
# apegmsh-1.5.0.dist-info/METADATA directly) - a gap in apeGmsh's own
# packaging, not something requirements.txt should silently work around.
# matplotlib (apeGmsh's "plot" extra, for headless results.plot) is already
# in requirements.txt for core/config.py's own needs.

# Pipeline code and Castelnuovo geometry are baked in (small, versioned
# inputs); records, interface selection and results are NOT - see the
# volume mounts in docker/opensees/README.md. Re-COPY happens last so
# code changes don't invalidate the expensive layers above.
COPY . /app

COPY docker/opensees/run_analysis.sh /usr/local/bin/run_analysis.sh
RUN chmod +x /usr/local/bin/run_analysis.sh

ENTRYPOINT ["/usr/local/bin/run_analysis.sh"]
