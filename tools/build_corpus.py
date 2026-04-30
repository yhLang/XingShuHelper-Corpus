"""构建金标语料库的二进制产物。

输入:  gold/<account>.jsonl  (一行一组 QA)
输出:
  dist/<account>/qa_<account>_texts.json   - 单 question 展开形式
  dist/<account>/qa_<account>_embeddings.bin - LE int32 n + int32 d + n*d float32
  dist/<account>.manifest.json             - {version, count, updated_at, files{texts,embeddings}}

embedding 缓存:
  .embed_cache/<account>.json  - {question_hash: [vector]}  避免重复调 API

manifest version 策略:
  texts.json 内容变了就 +1（与历史 manifest 对比）；如果没变化就不更新 manifest，
  CI 据此判断是否要 push。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EMBED_MODEL = "text-embedding-v3"
EMBED_BATCH = 10
EMBED_DIM = 1024  # text-embedding-v3 默认维度


def expand_groups(groups: list[dict]) -> list[dict]:
    """gold/<account>.jsonl 的分组形式 → 单 question 形式（与 App 端 QACorpusLoader 兼容）。"""
    out = []
    for g in groups:
        scene = g.get("scene", "其他")
        answer = g["answer"]
        risk = g.get("risk_note", "")
        for q in g.get("questions", []):
            q = q.strip()
            if not q:
                continue
            out.append({
                "scene": scene,
                "question": q,
                "answer": answer,
                "business_line": "书画",
                "risk_note": risk,
                "is_gold": True,
            })
    return out


def load_jsonl(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def text_key(t: str) -> str:
    return hashlib.sha1(t.encode("utf-8")).hexdigest()


def load_cache(path: Path) -> dict[str, list[float]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_cache(cache: dict[str, list[float]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def embed_texts(texts: list[str], cache: dict[str, list[float]]) -> list[list[float]]:
    """带缓存的批量 embedding。命中缓存的不调 API。"""
    todo = [t for t in dict.fromkeys(texts) if text_key(t) not in cache]
    if todo:
        from openai import OpenAI
        api_key = os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError("环境变量 DASHSCOPE_API_KEY 未设置")
        client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        print(f"  调 embedding API: {len(todo)} 条新增")
        for i in range(0, len(todo), EMBED_BATCH):
            batch = todo[i: i + EMBED_BATCH]
            resp = client.embeddings.create(model=EMBED_MODEL, input=batch)
            for t, item in zip(batch, resp.data):
                cache[text_key(t)] = item.embedding
            print(f"    {min(i + EMBED_BATCH, len(todo))}/{len(todo)}")
    return [cache[text_key(t)] for t in texts]


def write_embeddings_bin(vectors: list[list[float]], path: Path) -> None:
    n = len(vectors)
    d = len(vectors[0]) if n else 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(struct.pack("<ii", n, d))
        for v in vectors:
            f.write(struct.pack(f"<{d}f", *v))


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def previous_version(manifest_path: Path) -> int:
    if not manifest_path.exists():
        return 0
    return json.loads(manifest_path.read_text(encoding="utf-8")).get("version", 0)


def previous_texts_sha(manifest_path: Path) -> str:
    if not manifest_path.exists():
        return ""
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    return m.get("files", {}).get("texts", {}).get("sha256", "")


def previous_structured_sha(manifest_path: Path) -> str:
    if not manifest_path.exists():
        return ""
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    s = m.get("files", {}).get("structured")
    return s.get("sha256", "") if s else ""


def build_account(account: str) -> bool:
    """返回 True 表示产物有更新。"""
    src = ROOT / "gold" / f"{account}.jsonl"
    if not src.exists():
        print(f"[skip] {src} 不存在")
        return False
    groups = load_jsonl(src)
    items = expand_groups(groups)
    print(f"[{account}] {len(groups)} 组 → {len(items)} 条单 question 条目")

    out_dir = ROOT / "dist" / account
    texts_path = out_dir / f"qa_{account}_texts.json"
    emb_path = out_dir / f"qa_{account}_embeddings.bin"
    structured_src = ROOT / "gold" / f"structured_{account}.txt"
    structured_dst = out_dir / f"structured_{account}.txt"
    manifest_path = ROOT / "dist" / f"{account}.manifest.json"

    out_dir.mkdir(parents=True, exist_ok=True)
    new_texts_json = json.dumps(items, ensure_ascii=False, indent=2)

    # 比较 texts 和 structured 内容：都未变就跳过 embedding 调用
    new_texts_sha = hashlib.sha256(new_texts_json.encode("utf-8")).hexdigest()
    new_structured_sha = sha256_of(structured_src) if structured_src.exists() else ""
    texts_unchanged = new_texts_sha == previous_texts_sha(manifest_path) and emb_path.exists()
    structured_unchanged = new_structured_sha == previous_structured_sha(manifest_path)
    if texts_unchanged and structured_unchanged:
        print(f"[{account}] 内容未变化，跳过")
        return False

    texts_path.write_text(new_texts_json, encoding="utf-8")

    # embedding（带缓存）；texts 没变化则跳过 API 调用，复用现有 emb 文件
    if not texts_unchanged:
        cache_path = ROOT / ".embed_cache" / f"{account}.json"
        cache = load_cache(cache_path)
        questions = [it["question"] for it in items]
        vectors = embed_texts(questions, cache)
        save_cache(cache, cache_path)
        write_embeddings_bin(vectors, emb_path)

    # 结构化数据：直接拷贝到 dist/，进 manifest
    files_block = {
        "texts": {
            "path": f"dist/{account}/{texts_path.name}",
            "sha256": sha256_of(texts_path),
            "size": texts_path.stat().st_size,
        },
        "embeddings": {
            "path": f"dist/{account}/{emb_path.name}",
            "sha256": sha256_of(emb_path),
            "size": emb_path.stat().st_size,
        },
    }
    if structured_src.exists():
        structured_dst.write_text(structured_src.read_text(encoding="utf-8"), encoding="utf-8")
        files_block["structured"] = {
            "path": f"dist/{account}/{structured_dst.name}",
            "sha256": sha256_of(structured_dst),
            "size": structured_dst.stat().st_size,
        }

    version = previous_version(manifest_path) + 1
    manifest = {
        "version": version,
        "count": len(items),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": files_block,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{account}] 已构建 v{version}, {len(items)} 条")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", help="只构建指定账号；留空则构建 gold/ 下所有 jsonl")
    args = ap.parse_args()

    if args.account:
        accounts = [args.account]
    else:
        accounts = sorted(p.stem for p in (ROOT / "gold").glob("*.jsonl"))

    any_changed = False
    for acc in accounts:
        if build_account(acc):
            any_changed = True

    print("\n[done] 有改动" if any_changed else "\n[done] 无改动")
    return 0


if __name__ == "__main__":
    sys.exit(main())
