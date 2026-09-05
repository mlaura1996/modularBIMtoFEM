#!/bin/sh
# Entrypoint: run an OpenSeesMP TCL model with N processes and record the
# measurements the brief asks for every run (7.4): wall-clock time, peak
# memory, number of partitions (=NP here), and which machine it ran on.
# The DOF/node/element counts are the model's own business to log (they are
# printed by OpenSees itself / by the TCL script, not by this wrapper).
#
# Usage:
#   docker run --rm -v $(pwd)/output:/app/output <image> <NP> <model.tcl> [extra tcl args...]
#   docker run --rm -v $(pwd)/output:/app/output -e NP=6 <image> "" model.tcl
#
# NP and MODEL_TCL can come from the first two positional args or from the
# NP / MODEL_TCL environment variables (positional args win if given) - the
# point is that N is never hard-coded in the image, per brief 7.3.

set -eu

NP="${1:-${NP:-1}}"
MODEL_TCL="${2:-${MODEL_TCL:-}}"
shift $(( $# > 0 ? 1 : 0 )) 2>/dev/null || true
shift $(( $# > 0 ? 1 : 0 )) 2>/dev/null || true

if [ -z "$MODEL_TCL" ]; then
    echo "Usage: docker run ... <image> <NP> <model.tcl> [extra args passed to the tcl script]" >&2
    exit 1
fi

LOG_DIR="/app/output/run_logs"
mkdir -p "$LOG_DIR"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/${RUN_ID}_np${NP}.log"

{
    echo "=== OpenSeesMP run ${RUN_ID} ==="
    echo "model:      $MODEL_TCL"
    echo "processes:  $NP"
    echo "host:       $(hostname)"
    echo "cpu count:  $(nproc)"
    echo "started:    $(date -u -Iseconds)"
    echo "---"
} | tee "$LOG_FILE"

START_EPOCH=$(date +%s)

# `time -v` (GNU time, not the shell builtin) gives peak RSS via
# "Maximum resident set size"; mpirun's own children are what actually
# consume the memory, so this measures the mpirun process tree's peak.
/usr/bin/time -v mpirun --allow-run-as-root -np "$NP" \
    /usr/local/bin/OpenSeesMP "$MODEL_TCL" "$@" 2>&1 | tee -a "$LOG_FILE"
STATUS=$?

END_EPOCH=$(date +%s)
{
    echo "---"
    echo "finished:   $(date -u -Iseconds)"
    echo "wall-clock: $((END_EPOCH - START_EPOCH)) s"
    echo "exit code:  $STATUS"
} | tee -a "$LOG_FILE"

exit "$STATUS"
