# all-MiniLM-L6-v2 ONNX artifact

Do not commit the ONNX binary. Acquire it with:

```
python -m scripts.prepare_minilm_onnx --out models/minilm
```

Runtime inference never downloads. The directory must contain:

- `model.onnx`
- `tokenizer.json`
- `config.json`
- `manifest.json`
- `checksums.sha256`
- `LICENSE`

Upstream: `sentence-transformers/all-MiniLM-L6-v2` (Apache-2.0).
Quantized ONNX export consumed from `Xenova/all-MiniLM-L6-v2` at the
revision pinned in `scripts/prepare_minilm_onnx.py`.

Native output is 384-d mean-pooled L2-normalized; storage pads 128 zeros
to preserve the existing 512-d contract without a learned projection.
