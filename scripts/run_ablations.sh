#!/usr/bin/env bash
# Controlled ablations at an equal, reduced budget (2 epochs each, same cache,
# same sampler/schedule/seed). One variable changes per run versus the
# "abl_subcenter" reference. PAR runs at a time (default 1), 2 threads each.
#
#   bash scripts/run_ablations.sh            # all
#   bash scripts/run_ablations.sh abl_triplet # one
set -euo pipefail
cd "$(dirname "$0")/.."
EPOCHS=${EPOCHS:-2}

declare -A RUNS=(
  [abl_subcenter]="--loss subcenter_arcface"
  [abl_arcface]="--loss arcface"
  [abl_supcon]="--loss supcon"
  [abl_triplet]="--loss triplet"
  [abl_hemlock_only]="--loss subcenter_arcface --hemlock-only"
  [abl_dinov2]="--loss subcenter_arcface --cache runs/cache_dinov2"
)

run_one() {
  name=$1; shift
  mkdir -p runs/reid/$name runs/results
  python3 training/reid/train_tail.py --epochs "$EPOCHS" --threads 2 --out runs/reid/$name "$@" \
    > runs/reid/$name/train.log 2>&1
  python3 scripts/evaluate_reid.py --emb runs/reid/$name/embeddings.npy --name $name \
    --out runs/results/$name.json --quick > runs/reid/$name/eval.log 2>&1
  echo "done $name"
}
export -f run_one
export EPOCHS

names=("${@:-${!RUNS[@]}}")
for n in "${names[@]}"; do echo "$n ${RUNS[$n]}"; done | xargs -P "${PAR:-1}" -L 1 bash -c 'run_one "$@"' _
