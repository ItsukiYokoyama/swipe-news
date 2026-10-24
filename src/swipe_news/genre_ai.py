"""Classify sub-genres with a small embedding model (ruri-v3-30m, Japanese, Apache-2.0). About 5 ms per article on a CPU.

How: pick the sub-genre whose descriptions (hints in genres.yaml) are closest to the article (title + RSS summary).
Articles from specialist sources (not marked mixed) get a small bonus for that source's genre.
Accuracy on hand-labelled articles (2026-10-20): 74% for general-interest sources;
96% of articles from specialist sources keep the source genre.

Article text is used only for classification; it is never stored or sent anywhere (the model runs on this PC).
"""
import hashlib
import json
import logging
import threading
from pathlib import Path

import httpx
import numpy as np

from .paths import BUNDLED_MODELS_DIR, MODELS_DIR

log = logging.getLogger(__name__)

MODEL_NAME = "ruri-v3-30m"
# ONNX conversion of cl-nagoya/ruri-v3-30m (Apache-2.0). Revision and file hashes are pinned
MODEL_REPO = "sirasagi62/ruri-v3-30m-ONNX"
MODEL_REVISION = "cdf9391f1ff2198daa8f63f7ccf97d7b3e7415a0"
MODEL_FILES = {
    "onnx/model_int8.onnx": "3d374a6245afef3c1710f942b25aad6b341504ba13fc82a85a844eb37b33120d",
    "tokenizer.json": "0a94ac9a0a02c067bdef25b72ae9f4ee33f48f552e55988d444f6d25eeb1d062",
}
PREFIX = "トピック: "          # ruri-v3 prefix for classification / clustering
MAX_TOKENS = 128
SPECIALIST_PRIOR = 0.04        # Bonus for the source genre on specialist sources. Larger = re-labelled less often


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _model_dir() -> Path:
    """Use the model bundled in the Windows zip if present; otherwise download it into MODELS_DIR (first time only, ~44 MB)."""
    bundled = BUNDLED_MODELS_DIR / MODEL_NAME
    if all((bundled / Path(f).name).exists() for f in MODEL_FILES):
        return bundled
    target = MODELS_DIR / MODEL_NAME
    target.mkdir(parents=True, exist_ok=True)
    for name, sha in MODEL_FILES.items():
        dest = target / Path(name).name
        if dest.exists() and _sha256(dest) == sha:
            continue
        url = f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/{name}"
        log.info("downloading model: %s", url)
        tmp = dest.with_suffix(dest.suffix + ".part")
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
        if _sha256(tmp) != sha:
            tmp.unlink()
            raise RuntimeError(f"hash mismatch for downloaded model file: {name}")
        tmp.replace(dest)
    return target


class GenreClassifier:
    def __init__(self, taxonomy: list[dict]):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        d = _model_dir()
        self.tok = Tokenizer.from_file(str(d / "tokenizer.json"))
        self.tok.enable_truncation(max_length=MAX_TOKENS)
        self.tok.enable_padding()
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2  # Runs alongside crawling; don't take every core
        self.sess = ort.InferenceSession(str(d / "model_int8.onnx"), opts, providers=["CPUExecutionProvider"])

        genre_defs = [g for t in taxonomy for g in t["genres"]]
        self.genres = [g["name"] for g in genre_defs]
        hints = [(i, h) for i, g in enumerate(genre_defs) for h in (g.get("hints") or [g["name"]])]
        hx = self._embed([PREFIX + h for _, h in hints])
        hy = np.array([i for i, _ in hints])
        self.hint_vecs = [hx[hy == i] for i in range(len(self.genres))]
        mean = np.vstack([v.mean(0) for v in self.hint_vecs])
        self.mean = mean / np.linalg.norm(mean, axis=1, keepdims=True)
        self.version = version_of(taxonomy)

    def _embed(self, texts: list[str], batch: int = 32) -> np.ndarray:
        out = []
        for i in range(0, len(texts), batch):
            enc = self.tok.encode_batch(texts[i:i + batch])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            h = self.sess.run(None, {"input_ids": ids, "attention_mask": mask})[0]
            v = (h * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)
            out.append(v / np.linalg.norm(v, axis=1, keepdims=True))
        return np.vstack(out) if out else np.zeros((0, 1))

    def embed_articles(self, items: list[dict]) -> np.ndarray:
        """Article (title + RSS summary) → normalized 256-dim vector. Also used for preference learning."""
        return self._embed([PREFIX + it["title"] + ("。" + it["description"][:160] if it.get("description") else "")
                            for it in items]).astype(np.float32)

    def classify(self, items: list[dict], x: np.ndarray | None = None) -> list[str]:
        """items: [{"title", "description", "feed_genre", "mixed"}] → sub-genre names. x: precomputed vectors."""
        if not items:
            return []
        if x is None:
            x = self.embed_articles(items)
        # Half similarity to the mean of the hints, half similarity to the closest hint
        score = 0.5 * (x @ self.mean.T) + 0.5 * np.vstack([(x @ v.T).max(1) for v in self.hint_vecs]).T
        for row, it in zip(score, items, strict=False):
            if not it.get("mixed") and it.get("feed_genre") in self.genres:
                row[self.genres.index(it["feed_genre"])] += SPECIALIST_PRIOR
        return [self.genres[i] for i in score.argmax(1)]


# Version of the article vectors. Re-embed when the model or the way vectors are built changes
EMBED_VERSION = f"{MODEL_REVISION[:8]}:{PREFIX}:{MAX_TOKENS}"


def to_blob(v: np.ndarray) -> bytes:
    return v.astype(np.float16).tobytes()


def from_blob(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float16).astype(np.float32)


def version_of(taxonomy: list[dict]) -> str:
    """Changes when the model, the hints or the specialist bonus change; unread articles are then re-classified."""
    key = json.dumps([MODEL_REVISION, SPECIALIST_PRIOR, taxonomy], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:12]


_lock = threading.Lock()
_cached: GenreClassifier | None = None


def get(taxonomy: list[dict]) -> GenreClassifier:
    """Reuse the loaded classifier unless the hints changed. The first call may take a while (model download)."""
    global _cached
    with _lock:
        if _cached is None or _cached.version != version_of(taxonomy):
            _cached = GenreClassifier(taxonomy)
        return _cached
