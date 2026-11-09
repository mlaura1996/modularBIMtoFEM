#!/bin/sh
# Scalability benchmark on unit 417: build the model once, run every timed
# configuration one after the other on the same machine, then the results
# run (whole record, fields recorded), then collect everything. See
# benchmark_unit417_build.py for what the model is.
#
#   run_benchmark_unit417.sh <out_dir> [extra arguments for the build]
#
# Inside the opensees-mp image, with the repository mounted on /app:
#   docker run -d --name unit417-benchmark -v "<repo>:/app" -v "<results>:/app_output" -w /app \
#       --entrypoint sh modularbimtofem-opensees-mp:dev \
#       docker/opensees/run_benchmark_unit417.sh /app_output/benchmark_unit417
#
# Runs are sequential on purpose: two runs sharing the cores would time
# each other. Nothing else heavy should run on the machine meanwhile.
# --bind-to none: binding fails inside Docker on WSL2 ("failed to bind
# memory") and only prints a warning.
# SKIP_BUILD=1 reuses an existing model; ONLY="np4_mumps results_np8" runs a subset.
set -u
OUT="${1:?usage: run_benchmark_unit417.sh <out_dir> [build arguments]}"
shift
mkdir -p "$OUT"
LOG="$OUT/benchmark.log"
export OMP_NUM_THREADS=1          # one core per MPI process, BLAS included

echo "=== unit 417 benchmark $(date -u -Iseconds) on $(hostname), $(nproc --all) logical CPUs" | tee -a "$LOG"
if [ "${SKIP_BUILD:-0}" != "1" ]; then
    conda run --no-capture-output -n appenv python docker/opensees/benchmark_unit417_build.py \
        --out-dir "$OUT" "$@" 2>&1 | tee -a "$LOG"
fi
[ -f "$OUT/runs.txt" ] || { echo "build failed, no runs.txt" | tee -a "$LOG"; exit 1; }

run_list() {
    while read -r LABEL NP; do
        if [ -n "${ONLY:-}" ] && ! echo " $ONLY " | grep -q " $LABEL "; then continue; fi
        echo "--- $LABEL: $NP process(es), started $(date -u -Iseconds)" | tee -a "$LOG"
        START=$(date +%s)
        /usr/bin/time -v mpirun --allow-run-as-root --bind-to none -np "$NP" \
            /usr/local/bin/OpenSeesMP "$OUT/run_$LABEL.tcl" > "$OUT/$LABEL.out" 2>&1 < /dev/null
        STATUS=$?
        grep -E "^step |^done|Maximum resident|Elapsed \(wall|WARNING|ERROR|error" "$OUT/$LABEL.out" | tail -8 | tee -a "$LOG"
        echo "--- $LABEL: exit $STATUS, $(( $(date +%s) - START )) s" | tee -a "$LOG"
    done < "$1"
}

run_list "$OUT/runs.txt"
conda run --no-capture-output -n appenv python docker/opensees/benchmark_unit417_post.py "$OUT" 2>&1 | tee -a "$LOG"

run_list "$OUT/runs_results.txt"
conda run --no-capture-output -n appenv python docker/opensees/benchmark_unit417_fields.py "$OUT" 2>&1 | tee -a "$LOG"
echo "=== finished $(date -u -Iseconds)" | tee -a "$LOG"
