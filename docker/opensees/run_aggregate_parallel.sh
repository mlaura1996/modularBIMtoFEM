#!/bin/sh
# The Chapter 8 time-history of the whole aggregate on OpenSeesMP: build the
# partitioned model, run it, merge the per-rank recorders into a Chapter 8
# run directory and post-process it. See aggregate_parallel_build.py.
#
#   run_aggregate_parallel.sh <out_dir> [build arguments]
#
#   docker run -d --name aggregate-np8 -v "<repo>:/app" -v "<results>:/app_output" -w /app \
#       --entrypoint sh modularbimtofem-opensees-mp:dev \
#       docker/opensees/run_aggregate_parallel.sh /app_output/aggregate_parallel --nparts 8
#
# SKIP_BUILD=1 reuses a model already built in <out_dir>. Every partition
# count in the build's --nparts is run, one after the other.
set -u
OUT="${1:?usage: run_aggregate_parallel.sh <out_dir> [build arguments]}"
shift
mkdir -p "$OUT"
LOG="$OUT/aggregate.log"
export OMP_NUM_THREADS=1
MPI_ARGS="${MPI_ARGS:---bind-to none}"
PY="conda run --no-capture-output -n appenv python"

echo "=== Castelnuovo aggregate on OpenSeesMP $(date -u -Iseconds) on $(hostname), $(nproc --all) logical CPUs" | tee -a "$LOG"
command -v lscpu >/dev/null && lscpu | grep -E "^CPU\(s\)|Thread|Core|Model name" | tee -a "$LOG"
if [ "${SKIP_BUILD:-0}" != "1" ]; then
    $PY docker/opensees/aggregate_parallel_build.py --out-dir "$OUT" "$@" 2>&1 | tee -a "$LOG"
fi
ls "$OUT"/run_np*.tcl >/dev/null 2>&1 || { echo "build failed, no run_np*.tcl" | tee -a "$LOG"; exit 1; }

for DRIVER in "$OUT"/run_np*.tcl; do
    NP=$(basename "$DRIVER" .tcl | sed 's/run_np//')
    echo "--- np$NP: started $(date -u -Iseconds)" | tee -a "$LOG"
    START=$(date +%s)
    /usr/bin/time -v mpirun --allow-run-as-root $MPI_ARGS -np "$NP" \
        /usr/local/bin/OpenSeesMP "$DRIVER" < /dev/null 2>&1 \
        | grep --line-buffered -v -E "^\s*$" | tee "$OUT/np$NP.out" \
        | grep --line-buffered -E "^step |^done|^model built|^gravity|failed|ABORT|subdivision|Maximum resident|Elapsed \(wall|WARNING|ERROR|rror" \
        | tee -a "$LOG"
    echo "--- np$NP: finished, $(( $(date +%s) - START )) s" | tee -a "$LOG"
    $PY docker/opensees/aggregate_parallel_merge.py "$OUT" "$NP" 2>&1 | tee -a "$LOG" \
        && $PY scripts/postprocess_timehistory.py "$OUT/recorders_np$NP" "$OUT/results_np$NP" 2>&1 | tee -a "$LOG"
done
echo "=== finished $(date -u -Iseconds)" | tee -a "$LOG"
