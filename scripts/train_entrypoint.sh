#!/usr/bin/env bash
set -euo pipefail

# Argumentos
EXPTID="${1:?Usage: $0 <EXPTID> [ours|real] [MAX_ITER]}"
DATASET_MODE="${2:-ours}"
MAX_ITER="${3:-5000}"

cd /workspace

DATASET_ORIG="/workspace/legged_gym/resources/datasets/goalkeeper"
DATASET_BACKUP="${DATASET_ORIG}.orig"
DATASET_OURS="/workspace/data/goalkeeper_ours"

if [ "$DATASET_MODE" = "ours" ]; then
    # Backup do original (se ainda for diretório real, mover para .orig)
    if [ -d "$DATASET_ORIG" ] && [ ! -L "$DATASET_ORIG" ]; then
        mv "$DATASET_ORIG" "$DATASET_BACKUP"
    fi
    # Remove symlink antigo se existir
    [ -L "$DATASET_ORIG" ] && rm "$DATASET_ORIG"
    # Cria symlink para nosso dataset
    ln -sfn "$DATASET_OURS" "$DATASET_ORIG"
    echo "=== Dataset: ours (symlinked) ==="
elif [ "$DATASET_MODE" = "real" ]; then
    # Restaurar dataset original se backup existir
    if [ -L "$DATASET_ORIG" ]; then
        rm "$DATASET_ORIG"
    fi
    if [ -d "$DATASET_BACKUP" ] && [ ! -e "$DATASET_ORIG" ]; then
        mv "$DATASET_BACKUP" "$DATASET_ORIG"
    fi
    echo "=== Dataset: real (original) ==="
else
    echo "ERROR: DATASET_MODE must be 'ours' or 'real', got '$DATASET_MODE'" >&2
    exit 1
fi

# Verificar que o dataset e joint_id.txt estão acessíveis
if [ ! -f "$DATASET_ORIG/joint_id.txt" ]; then
    echo "ERROR: joint_id.txt not found in $DATASET_ORIG/" >&2
    ls -la "$DATASET_ORIG/" 2>/dev/null || echo "(directory does not exist)"
    exit 1
fi

ls -la "$DATASET_ORIG/"

echo "=== Starting training ==="
echo "exptid:         $EXPTID"
echo "dataset_mode:   $DATASET_MODE"
echo "max_iterations: $MAX_ITER"
echo "task:           29"
echo "headless:       yes"

cd /workspace/legged_gym/legged_gym/scripts
exec python -u train.py --task 29 --exptid "$EXPTID" --headless --max_iterations "$MAX_ITER"
