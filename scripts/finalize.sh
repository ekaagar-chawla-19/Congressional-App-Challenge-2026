#!/usr/bin/env bash
# Everything downstream of a trained re-ID run, for the production model:
# species head -> export -> duplicate threshold -> calibration -> deployed-path eval
# -> operating curves -> benchmarks.
#
#   bash scripts/finalize.sh runs/reid/dino_deep_multi 322
set -euo pipefail
cd "$(dirname "$0")/.."
RUN=$1
SIZE=${2:-322}
NAME=$(basename "$RUN")
EXP=runs/export
mkdir -p $EXP runs/results runs/bench

python3 scripts/evaluate_reid.py --emb $RUN/embeddings.npy --name $NAME --out runs/results/$NAME.json
python3 training/species/train_head.py --emb $RUN/embeddings.npy --out runs/species/$NAME

IMGS=$(python3 - <<'EOF'
import json
from hemlock_sentinel.evaluation.splits import read_manifest
recs = read_manifest("runs/data/manifest.csv"); sp = json.load(open("runs/data/splits.json"))
print("\n".join([r.path for r in recs if r.tree_id in set(sp["test"]) and r.species == "tsuga_canadensis"][:6]))
EOF
)
mapfile -t IMG_ARR <<< "$IMGS"
python3 scripts/export_model.py --tail $RUN/tail.pt --species runs/species/$NAME/species_head.npz \
  --out $EXP/hemlock --image-size "$SIZE" --version "hemlock-$NAME-$(date +%Y%m%d)" --check-images "${IMG_ARR[@]}"
python3 scripts/calibrate_duplicate.py --model $EXP/hemlock.onnx --out runs/results/duplicate_$NAME.json
python3 scripts/calibrate.py --calib-species all --emb $RUN/embeddings.npy \
  --species runs/species/$NAME/species_results.json --duplicate runs/results/duplicate_$NAME.json \
  --out $EXP/calibration.json --report runs/results/decision_$NAME.json
python3 scripts/calibrate.py --calib-species hemlock --emb $RUN/embeddings.npy \
  --species runs/species/$NAME/species_results.json --duplicate runs/results/duplicate_$NAME.json \
  --out $EXP/calibration_hemlock_val.json --report runs/results/decision_${NAME}_hemlockval.json
python3 scripts/embed_with_runtime.py --model $EXP/hemlock.onnx --out runs/reid/onnx_$NAME/embeddings.npy
python3 scripts/evaluate_reid.py --emb runs/reid/onnx_$NAME/embeddings.npy --name onnx_$NAME \
  --out runs/results/onnx_$NAME.json --quick --hemlock-only
python3 scripts/operating_curve.py --emb $RUN/embeddings.npy --out runs/results/curve_$NAME.json
python3 scripts/operating_curve.py --emb $RUN/embeddings.npy --views 5 --out runs/results/curve_${NAME}_5views.json
echo FINALIZE_DONE
