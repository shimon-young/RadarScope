#!/usr/bin/env bash
# ============================================================
#  RadarScope - first-time environment setup (Linux)
#
#  1. Lets the user pick a local Python 3.10 interpreter
#  2. Creates a dedicated venv at RADAR_inference/env
#     (deploy/start_server.sh picks this location up automatically)
#  3. Installs PyTorch (CUDA 12.9 or CPU build) from the official
#     PyTorch wheel index
#  4. Installs all remaining dependencies from requirements-desktop.txt
#
#  Re-runnable: every step skips work that is already done, so you
#  can simply run this script again after a failure.
#
#  After setup, start the service with:
#     ./RADAR_inference/deploy/start_server.sh
# ============================================================
set -uo pipefail
cd "$(dirname "$0")"

VENV="RADAR_inference/env"
REQ="requirements-desktop.txt"
TORCH_VERSION="2.8.0"
TORCHVISION_VERSION="0.23.0"
TORCHAUDIO_VERSION="2.8.0"

echo "============================================================"
echo "  RadarScope - Environment Setup"
echo "============================================================"
echo "  Target venv : $PWD/$VENV"
echo "  Requires    : Python 3.10.x (3.10.18 is the tested version)"
echo

# ------------------------------------------------------------
# STEP 1/5 - virtual environment
# ------------------------------------------------------------
if [ -x "$VENV/bin/python" ]; then
    echo "[STEP 1/5] Virtual environment already exists - reusing it."
else
    echo "[STEP 1/5] Select a Python 3.10 interpreter"
    mapfile -t CANDS < <( { command -v python3.10 2>/dev/null || true
                            command -v python3    2>/dev/null || true
                            [ -x /usr/bin/python3.10 ] && echo /usr/bin/python3.10
                          } | sort -u )
    N=${#CANDS[@]}
    if [ "$N" -gt 0 ]; then
        echo "  Found candidates:"
        i=1
        for c in "${CANDS[@]}"; do printf "    %d. %s\n" "$i" "$c"; i=$((i+1)); done
    fi
    read -rp "Select [1-$N], Enter for manual input, or paste a full python path: " CH
    SELECTED=""
    if [[ "$CH" =~ ^[0-9]+$ ]] && [ "$CH" -ge 1 ] && [ "$CH" -le "$N" ]; then
        SELECTED="${CANDS[$((CH-1))]}"
    elif [ -n "$CH" ]; then
        SELECTED="$CH"
    else
        read -rp "Full path to python executable: " SELECTED
    fi
    if ! "$SELECTED" -c 'import sys; sys.exit(0 if sys.version_info[:2]==(3,10) else 1)'; then
        echo "[ERROR] Not a working Python 3.10: $SELECTED"
        exit 1
    fi
    echo "  Using: $SELECTED ($("$SELECTED" -c 'import sys;print(sys.version.split()[0])'))"
    echo "  Creating virtual environment..."
    "$SELECTED" -m venv "$VENV" || { echo "[ERROR] venv creation failed."; exit 1; }
fi
PYV="$VENV/bin/python"
"$PYV" -c "import sys; print('   venv python :', sys.version.split()[0], '-', sys.executable)" || exit 1

# ------------------------------------------------------------
# STEP 2/5 - PyPI mirror
# ------------------------------------------------------------
MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
echo
echo "[STEP 2/5] Choose a PyPI mirror:"
echo "    1. Tsinghua   (default)"
echo "    2. Aliyun"
echo "    3. Tencent"
echo "    4. Official   https://pypi.org/simple"
read -rp "Pick a mirror [1-4], Enter=1: " CH
case "$CH" in
    2) MIRROR="https://mirrors.aliyun.com/pypi/simple" ;;
    3) MIRROR="https://mirrors.cloud.tencent.com/pypi/simple" ;;
    4) MIRROR="https://pypi.org/simple" ;;
esac
echo "  Mirror: $MIRROR"

# ------------------------------------------------------------
# STEP 3/5 - pip bootstrap
# ------------------------------------------------------------
echo
echo "[STEP 3/5] Upgrading pip (skipped automatically if already current)..."
"$PYV" -m pip install --upgrade pip -i "$MIRROR" --quiet \
    || echo "  [WARN] pip upgrade failed - continuing with the bundled pip."

# ------------------------------------------------------------
# STEP 4/5 - PyTorch (skipped if already importable)
# ------------------------------------------------------------
echo
echo "[STEP 4/5] PyTorch"
if "$PYV" -c "import torch" 2>/dev/null; then
    "$PYV" -c "import torch; print('   [SKIP] torch', torch.__version__, 'already installed | CUDA available:', torch.cuda.is_available())"
else
    TORCH_INDEX="https://download.pytorch.org/whl/cpu"
    DEFAULT="CPU"
    if command -v nvidia-smi >/dev/null 2>&1; then
        DEFAULT="GPU"
        echo "  NVIDIA GPU detected: nvidia-smi found."
    else
        echo "  No NVIDIA GPU detected (nvidia-smi not found)."
    fi
    echo "    1. GPU build  - CUDA 12.9 wheels, ~2.5 GB download (for NVIDIA GPUs)"
    echo "    2. CPU build  - smaller download, slower inference"
    read -rp "Pick torch build [1/2], Enter=$DEFAULT: " CH
    case "$CH" in
        1) TORCH_INDEX="https://download.pytorch.org/whl/cu129" ;;
        2) TORCH_INDEX="https://download.pytorch.org/whl/cpu" ;;
        *) [ "$DEFAULT" = "GPU" ] && TORCH_INDEX="https://download.pytorch.org/whl/cu129" ;;
    esac
    echo "  Wheel index: $TORCH_INDEX"
    OK=0
    for try in 1 2 3; do
        if "$PYV" -m pip install "torch==$TORCH_VERSION" "torchvision==$TORCHVISION_VERSION" \
                "torchaudio==$TORCHAUDIO_VERSION" --index-url "$TORCH_INDEX" --retries 5 --timeout 60; then
            OK=1; break
        fi
        echo "  [RETRY] torch install failed - attempt $try of 3..."
    done
    [ "$OK" = "1" ] || { echo "[ERROR] torch installation failed after 3 attempts. Re-run this script to resume."; exit 1; }
    echo "  torch installed."
fi

# ------------------------------------------------------------
# STEP 5/5 - all remaining dependencies (pip skips satisfied ones)
# ------------------------------------------------------------
echo
echo "[STEP 5/5] Installing dependencies (already-installed ones are skipped)..."
OK=0
for try in 1 2 3; do
    if "$PYV" -m pip install -r "$REQ" -i "$MIRROR" --retries 5 --timeout 60; then OK=1; break; fi
    echo "  [RETRY] dependency install failed - attempt $try of 3..."
done
[ "$OK" = "1" ] || { echo "[ERROR] Dependency installation failed after 3 attempts. Re-run this script to resume."; exit 1; }
echo "  Dependencies installed."

# ------------------------------------------------------------
# Verify
# ------------------------------------------------------------
echo
echo "[VERIFY] Importing core packages..."
if ! "$PYV" -c "import torch, torchvision, fastapi, uvicorn, monai, transformers, timm, nibabel, SimpleITK, numpy, pandas, cv2; print('   torch', torch.__version__, '| CUDA available:', torch.cuda.is_available()); print('   ALL CORE PACKAGES OK')"; then
    echo "[ERROR] Verification failed - re-run this script to repair."
    exit 1
fi
# ------------------------------------------------------------
# Model weights & text embeddings
# ------------------------------------------------------------
echo
echo "============================================================"
echo "  Checking model weights..."
echo "============================================================"
NEED_DL=""
if [ -f "ckpt/checkpoint_radar_pretrain.pth" ]; then
    echo "  main weights          : OK"
else
    echo "  [NOTE] main weights missing: ckpt/checkpoint_radar_pretrain.pth"
    NEED_DL=1
fi
if [ -f "ckpt/bert-base-chinese/config.json" ]; then
    echo "  main bert-base-chinese: OK"
else
    echo "  [NOTE] bert-base-chinese missing - required by main."
    NEED_DL=1
fi
if [ -f "ckpt/infer_text_embedding_radar.pt" ]; then
    echo "  main text embedding   : OK"
else
    echo "  [ERROR] infer_text_embedding_radar.pt missing - restore it from the package."
fi

if [ -n "$NEED_DL" ]; then
    echo
    echo "  Model weights are required. Download now from the official repo?"
    echo "  (via hf-mirror.com, resumable - just re-run if interrupted)"
    echo "    1) main only   (~1.9 GB)"
    echo "    2) main + plus (~3.5 GB, plus has the higher AUC)"
    echo "    3) skip for now"
    printf "  Choice [1/2/3]: "
    read -r DLCH
    case "$DLCH" in
        1) "$PYV" RADAR_inference/scripts/download_weights.py --preset main \
              || echo "  [WARN] Download failed - re-run this script to retry." ;;
        2) "$PYV" RADAR_inference/scripts/download_weights.py --preset all \
              || echo "  [WARN] Download failed - re-run this script to retry." ;;
        *)
            echo "  Skipped. Download later with:"
            echo "    RADAR_inference/env/bin/python RADAR_inference/scripts/download_weights.py"
            echo "  or from the admin page (Model weights) after starting the service."
            ;;
    esac
fi

if [ -f "ckpt/checkpoint_radar_plus_finetuned_on_merlin.pth" ]; then
    echo "  plus weights          : OK"
else
    echo "  [NOTE] plus weights not found (optional) - main works standalone."
fi
if [ -f "ckpt/infer_text_embedding_merlin_en.pt" ]; then
    echo "  plus text embedding   : OK"
elif [ -f "ckpt/checkpoint_radar_plus_finetuned_on_merlin.pth" ]; then
    echo "  Generating plus text embedding from official MERLIN prompts..."
    if ( cd RADAR_inference && "$PYV" -m radar.engine.text_embed --items merlin20 \
            --checkpoint ../ckpt/checkpoint_radar_plus_finetuned_on_merlin.pth ); then
        echo "  plus text embedding   : generated"
    else
        echo "  [WARN] Generation failed. Re-run later with:"
        echo "         cd RADAR_inference && python -m radar.engine.text_embed --items merlin20"
    fi
fi

echo
echo "============================================================"
echo "  Setup finished."
echo "    venv  : $PWD/$VENV"
echo "    Start : ./RADAR_inference/deploy/start_server.sh"
echo "============================================================"
