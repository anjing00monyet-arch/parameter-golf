# Parameter Golf — Claude Code Guide

## What This Repo Is

OpenAI Model Craft Challenge: train the best language model that fits in a **16 MB artifact** and trains in **under 10 minutes on 8×H100s**, scored by bits-per-byte (BPB) on the FineWeb validation set. Lower BPB is better. The leaderboard record as of the repo snapshot is **1.0810 BPB**.

## Repository Layout

```
train_gpt.py            # Main CUDA training script (baseline + SOTA starting point)
train_gpt_mlx.py        # MLX variant for Apple Silicon local iteration
hierarchical_embed.py   # Tiered quantized embedding module used by train_gpt.py
data/
  cached_challenge_fineweb.py   # Downloads FineWeb shards from HuggingFace
  tokenizer_specs.json
records/
  track_10min_16mb/     # Official leaderboard submissions (≤10 min, ≤16 MB)
  track_non_record_16mb/ # Non-record / unlimited-compute submissions
requirements.txt
```

`train_gpt.py` and `train_gpt_mlx.py` must never exceed **1500 lines**.

## Environment Setup

### Local (Apple Silicon)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install mlx numpy sentencepiece huggingface-hub datasets tqdm
python3 data/cached_challenge_fineweb.py --variant sp1024 --train-shards 1
```

### Remote GPU (RunPod / H100)

All Python dependencies are pre-installed in the RunPod template image.

```bash
git clone https://github.com/openai/parameter-golf.git && cd parameter-golf
python3 data/cached_challenge_fineweb.py --variant sp1024   # full 80-shard download
```

## Running Training

### Quick smoke test (MLX, Mac)

```bash
RUN_ID=smoke ITERATIONS=200 TRAIN_BATCH_TOKENS=8192 VAL_LOSS_EVERY=0 \
  python3 train_gpt_mlx.py
```

### Single GPU (CUDA)

```bash
RUN_ID=baseline_sp1024 \
DATA_PATH=./data/datasets/fineweb10B_sp1024 \
TOKENIZER_PATH=./data/tokenizers/fineweb_1024_bpe.model \
VOCAB_SIZE=1024 \
torchrun --standalone --nproc_per_node=1 train_gpt.py
```

### Multi-GPU (8×H100 — official leaderboard run)

```bash
torchrun --standalone --nproc_per_node=8 train_gpt.py
```

Key env-var overrides (all have defaults in `Hyperparameters`):

| Variable | Default | Purpose |
|---|---|---|
| `RUN_ID` | random UUID | Log prefix |
| `ITERATIONS` | 20000 | Training steps |
| `MAX_WALLCLOCK_SECONDS` | 600 | Hard stop (0 = unlimited) |
| `NUM_LAYERS` | 9 | Transformer depth |
| `MODEL_DIM` | 512 | Hidden dimension |
| `VOCAB_SIZE` | 1024 | Must match tokenizer |
| `TRAIN_SEQ_LEN` | 1024 | Sequence length |
| `VAL_LOSS_EVERY` | 1000 | Validation cadence (0 = end only) |

## Key Architecture Details

- **Optimizer**: Muon (matrix weights) + Adam (scalars/embeddings). Muon orthogonalizes gradients via Newton-Schulz iteration.
- **Attention**: GQA with RMS-normed Q/K, RoPE, per-head Q-gain, logit softcap (tanh).
- **MLP**: ReLU² activation (`relu(x)²`).
- **Embeddings**: `HierarchicalQuantizedEmbedding` (tiered precision: fp16→int8→int6→int4 by token frequency).
- **Post-training**: Int8 quantization → zlib compression → size check against 16 MB cap.
- **Evaluation metric**: BPB = bits-per-byte, tokenizer-agnostic. Computed in `eval_val()`.

## Submitting a New Record

### 1. Create a records folder

```
records/track_10min_16mb/YYYY-MM-DD_ShortName/
  README.md        # Explain the idea and results
  submission.json  # Structured metadata (see below)
  train_gpt.py     # Your complete, runnable script
  train_seed42.log
  train_seed314.log
  train_seed999.log
```

### 2. `submission.json` fields

```json
{
  "author": "your_name",
  "github_id": "your_github_id",
  "name": "Human-readable run name",
  "date": "YYYY-MM-DD",
  "track": "10min_16mb",
  "val_bpb": 1.0800,
  "val_bpb_std": 0.0002,
  "seeds": [42, 314, 999],
  "seed_results": { "42": {"val_bpb": ..., "artifact_bytes": ...}, ... },
  "hardware": "8xH100 80GB SXM",
  "pytorch_version": "2.x.y+cuXXX",
  "technique_summary": "one-line summary of changes",
  "compliance": {
    "train_under_600s": true,
    "artifact_under_16mb": true,
    "eval_under_600s": true
  }
}
```

### 3. Acceptance criteria

- Beat current SOTA by ≥ 0.005 nats (statistical significance at p < 0.01 over 3 seeds).
- Artifact ≤ 16,000,000 bytes (decimal MB, not MiB).
- Training + evaluation each ≤ 10 minutes on 8×H100 SXM.
- No network access during evaluation; fully self-contained script.

## Common Pitfalls

- **Tokenizer edits** are scrutinized heavily — a bug can artificially lower BPB.
- **Validation data** must not be seen during training (except tokens already evaluated in TTT).
- **Code size counts** toward the 16 MB limit — large inline lookup tables inflate the artifact.
- `train_gpt.py` must stay under 1500 lines; put complex additions in helper files.
- Imports from external libraries are free (they don't count toward the byte budget), but no extra compute may be hidden in them.

## Dataset Variants

| Variant | Vocab | Download flag |
|---|---|---|
| `sp1024` | 1024 BPE tokens | `--variant sp1024` |
| `sp4096` | 4096 BPE tokens | `--variant sp4096` |
| `sp8192` | 8192 BPE tokens | `--variant sp8192` |
| `byte260` | 260 raw bytes | `--variant byte260` |

Data lives in `data/datasets/fineweb10B_<variant>/`. Train shards: `fineweb_train_*.bin`. Val shards: `fineweb_val_*.bin`.
