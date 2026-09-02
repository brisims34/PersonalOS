# PersonalOS — Model Install Guide

How to get a model onto a locked-down machine and registered with PersonalOS.

**Assume `huggingface.co` is blocked.** Manual placement is the primary path; the in-app downloader is the lucky case, not the design centre. Both end at the same place — files in a folder, validated and registered.

---

## 1. Before You Start

Run the preflight:

```bash
python preflight.py
```

It reports which backends the machine supports, how much RAM you have, whether HuggingFace is reachable, and — if a model is already present — measured tokens/sec. **Pick your model tier from its output, not from this document's assumptions.**

If `pip install onnxruntime-genai fastembed numpy` fails, stop and read §7 before doing anything else.

---

## 2. Recommended Models

For CPU-only with 16GB RAM:

| Tier | Model | Format | Size | Licence | Use |
|---|---|---|---|---|---|
| `small` | Phi-4-mini-instruct ONNX INT4 | ONNX dir | ~2.5 GB | MIT | Extraction, triage, classification |
| `small` alt | Qwen2.5-3B-Instruct ONNX INT4 | ONNX dir | ~2.0 GB | Apache 2.0 | Same, slightly faster |
| `large` | Qwen2.5-7B-Instruct ONNX INT4 | ONNX dir | ~4.7 GB | Apache 2.0 | Drafting |
| `embedding` | bge-small-en-v1.5 | ONNX | ~130 MB | MIT | Semantic search |

**Start with one `small` model plus the embedding model.** Together they sit comfortably in 16GB and cover the two features that will actually earn their keep on CPU. Add a `large` model only if drafting quality proves worth the latency.

> If your machine has a GPU that preflight detects, the calculus changes and a 7B model becomes comfortable for interactive use. Re-read the preflight output.

---

## 3. The Two File Shapes — the thing that trips people up

### GGUF — one file

```
app/data/models/qwen2.5-3b-instruct-q4/
└── qwen2.5-3b-instruct-q4_k_m.gguf
```

Simple. Download it, drop it in, done.

### ONNX Runtime GenAI — a **directory** of files

```
app/data/models/phi-4-mini-instruct-onnx-int4/
├── genai_config.json          ~2 KB    ← required
├── model.onnx                 ~1 MB    ← the graph, small
├── model.onnx.data            ~2.4 GB  ← THE WEIGHTS
├── tokenizer.json             ~2 MB    ← required
├── tokenizer_config.json      ~5 KB    ← required
└── special_tokens_map.json    ~1 KB    ← required
```

> **`model.onnx.data` is the one people miss.** `model.onnx` is only about a megabyte — it is the computation graph, not the weights. It is entirely possible to download "the model," see a file called `model.onnx`, and have nothing usable. If the folder is a few megabytes rather than a few gigabytes, the weights are missing.

The validator checks for the complete set and **names the specific missing file** rather than failing generically, precisely because this failure is so easy to hit.

---

## 4. Manual Install

### Step 1 — get the file list

In PersonalOS: **System → AI Providers & Models → Catalog → [model] → Install Sheet**.

It generates the exact file list with sizes and SHA-256 checksums, the source URLs, and ready-to-run commands. Print it or copy it to wherever you will do the download.

### Step 2 — download somewhere with access

Any machine that can reach `huggingface.co`. Three options:

**Browser** — open each URL from the install sheet and save it.

**PowerShell** (generated for you on the install sheet):

```powershell
$base = "https://huggingface.co/microsoft/Phi-4-mini-instruct-onnx/resolve/main/cpu_and_mobile/cpu-int4-rtn-block-32"
$dest = "$HOME\Downloads\phi-4-mini-instruct-onnx-int4"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

@("genai_config.json","model.onnx","model.onnx.data",
  "tokenizer.json","tokenizer_config.json","special_tokens_map.json") | ForEach-Object {
    Write-Host "Downloading $_ ..."
    Invoke-WebRequest -Uri "$base/$_" -OutFile "$dest\$_"
}
```

**huggingface-cli** — if it is available to you:

```bash
huggingface-cli download microsoft/Phi-4-mini-instruct-onnx \
  --include "cpu_and_mobile/cpu-int4-rtn-block-32/*" \
  --local-dir ./phi-4-mini
```

### Step 3 — transfer

USB, OneDrive, network share — whatever your environment allows.

> **Verify checksums after transfer, not before.** Multi-gigabyte files over USB or a sync client are truncated or corrupted often enough to matter, and a partially-written tensor file does not error — it produces subtly wrong output that is genuinely difficult to trace back to its cause. Ten seconds of hashing saves an afternoon.

### Step 4 — place

```
C:\Users\bsims\PersonalOS\app\data\models\<model-id>\
```

Use the `<model-id>` from the install sheet. One folder per model; all files at the top level of it, not in a nested subfolder — a common mistake when extracting an archive.

### Step 5 — scan and register

**System → AI Providers & Models → Scan models folder.**

The scanner:

1. Walks `app/data/models/`
2. Matches folders against the catalog by file checksums
3. Verifies completeness, naming any missing file
4. Reads `genai_config.json` for context window and architecture
5. Registers in `ai_models` with `status = 'verified'`
6. Writes a `personalos_model.json` sidecar so the folder is self-describing

### Step 6 — start the server

```bash
python personalos_ai.py serve
```

Then in PersonalOS: **AI Providers & Models → local → Test connection**.

---

## 5. Off-Catalog Models

Any compatible model works, not just catalogued ones.

1. Place it in its own folder under `app/data/models/`
2. Scan — it appears as **Unrecognised**
3. Register manually: confirm backend (`onnx_genai` or `gguf`), context window, task tier
4. PersonalOS reads what metadata it can — `genai_config.json` for ONNX, the GGUF header for GGUF — and pre-fills what it can infer

### The sidecar

On registration, `personalos_model.json` is written into the folder:

```json
{
  "model_id": "phi-4-mini-instruct-onnx-int4",
  "label": "Phi-4 Mini Instruct (INT4)",
  "backend": "onnx_genai",
  "task_tier": "small",
  "context_window": 4096,
  "files": [
    {"name": "model.onnx.data", "bytes": 2576980377, "sha256": "…"}
  ],
  "registered_at": "2026-08-29T21:00:00"
}
```

This makes the folder self-describing, so it survives a database reset, a rescan, or a move to another machine without needing re-identification.

---

## 6. In-App Download

If preflight reports HuggingFace reachable, **Catalog → [model] → Download** fetches with progress and resume, verifies checksums, and registers automatically.

If the proxy blocks it, the downloader fails clearly and shows the install sheet instead. Registration and validation are identical either way — download is simply an alternate way to fill the folder.

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "Missing required file: `model.onnx.data`" | Weights not downloaded | Re-download that file specifically; it is the multi-GB one |
| Folder is a few MB | Only the graph was downloaded | As above |
| "Checksum mismatch on `model.onnx.data`" | Truncated or corrupted transfer | Re-download; re-verify **after** transfer |
| "Unrecognised model format" | Nested folder from an archive | Move files to the top level of the model folder |
| Server starts, generation fails immediately | Insufficient RAM | Use a smaller tier; check preflight's RAM reading |
| Very slow — under 2 tok/s | Model too large for CPU | Drop to a 3B INT4 model |
| `pip install onnxruntime-genai` fails | No matching wheel, or blocked index | See below |
| "Model loaded but output is gibberish" | Corrupt weights that passed a partial check | Re-verify checksums on **every** file |

### When pip itself is the problem

If wheels will not install:

1. Check Python version and architecture — wheels are built for specific combinations, and 32-bit Python will find nothing
2. Try an explicit version: `pip install onnxruntime-genai==0.4.0`
3. Download the `.whl` on a machine with access and `pip install <file>.whl` locally
4. If a package genuinely requires a compiler, it is the wrong backend for this machine — use ONNX Runtime rather than `llama-cpp-python`

**PersonalOS runs fully without any AI dependency.** If this section becomes a wall, stop — nothing else in the application is affected.

---

## 8. Moving Models Between Machines

Copy the whole model folder including `personalos_model.json`, drop it into `app/data/models/` on the target machine, and scan. The sidecar identifies it; checksums are re-verified. No re-download.

---

## 9. Cloud Providers

When you have API access:

**System → AI Providers & Models → [Anthropic | Google] → Configure.** The key is written to `app/data/secrets.json` (gitignored, never logged, masked in the UI) and referenced by `key_ref`. **Test connection** verifies reachability.

Enabling a provider does **not** enable any feature to use it. Every feature is `max_boundary = 'local'` at seed, and raising one is a separate, per-feature action behind a confirmation naming exactly what would be sent.

Behind a TLS-inspecting proxy, set `REQUESTS_CA_BUNDLE` to your corporate CA bundle. The connectivity diagnostic reports which providers are actually reachable — check it rather than guessing.

See `AI_SUBSYSTEM.md` §4 before enabling anything external.
