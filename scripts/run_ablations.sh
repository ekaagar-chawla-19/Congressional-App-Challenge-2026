#!/usr/bin/env bash
# Controlled ablations in the cheap "last block + head" regime
# (training/reid/recache_last_block.py): only the backbone's last block, its
# final layers, GeM and BN are trained, on a second-level feature cache. Every
# run uses the same caches, sampler, schedule and epochs; one variable changes
# versus the sub-center ArcFace reference; each is repeated over SEEDS.
#
#   bash scripts/run_ablations.sh                 # all
#   bash scripts/run_ablations.sh arcface triplet # some
#
# Prerequisites: runs/cache_last (EfficientNetV2-M) and runs/cache_dinov2_last.
set -euo pipefail
cd "$(dirname "$0")/.."
EPOCHS=${EPOCHS:-8}
SEEDS=${SEEDS:-"0 1 2"}
THREADS=${THREADS:-4}

declare -A RUNS=(
  [subcenter]="--loss subcenter_arcface --cache runs/cache_last"
  [arcface]="--loss arcface --cache runs/cache_last"
  [supcon]="--loss supcon --cache runs/cache_last"
  [triplet]="--loss triplet --cache runs/cache_last"
  [hemlock_only]="--loss subcenter_arcface --cache runs/cache_last --hemlock-only"
  [dinov2]="--loss subcenter_arcface --cache runs/cache_dinov2_last"
)

names=("$@")
[ ${#names[@]} -eq 0 ] && names=(subcenter arcface supcon triplet hemlock_only dinov2)
for n in "${names[@]}"; do
  for s in $SEEDS; do
    out=runs/reid/lb_${n}_s${s}
    [ -f runs/results/lb_${n}_s${s}.json ] && { echo "skip $out"; continue; }
    mkdir -p "$out" runs/results
    # shellcheck disable=SC2086
    python3 training/reid/train_tail.py --epochs "$EPOCHS" --threads "$THREADS" --seed "$s" --out "$out" ${RUNS[$n]} \
      > "$out/train.log" 2>&1
    python3 scripts/evaluate_reid.py --emb "$out/embeddings.npy" --name "lb_${n}_s${s}" \
      --out "runs/results/lb_${n}_s${s}.json" --quick > "$out/eval.log" 2>&1
    echo "done lb_${n}_s${s}"
  done
done
