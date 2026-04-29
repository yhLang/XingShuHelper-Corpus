"""一次性脚本：把主项目里既有的 gold_<account>.json 转成 gold/<account>.jsonl。

JSONL 格式（一行一组）：
  {"scene": "...", "questions": ["q1","q2"], "answer": "...", "risk_note": ""}

用法：
  python tools/export_initial.py --src ../XingShuHelper/tools/qa_miner --out gold
"""
import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="包含 gold_<account>.json 的目录")
    ap.add_argument("--out", default="gold", help="输出 jsonl 目录")
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for f in src.glob("gold_*.json"):
        account = f.stem.removeprefix("gold_")
        groups = json.loads(f.read_text(encoding="utf-8"))
        dst = out / f"{account}.jsonl"
        with dst.open("w", encoding="utf-8") as w:
            for g in groups:
                line = {
                    "scene": g.get("scene", "其他"),
                    "questions": [q.strip() for q in g.get("questions", []) if q.strip()],
                    "answer": g["answer"],
                    "risk_note": g.get("risk_note", ""),
                }
                w.write(json.dumps(line, ensure_ascii=False) + "\n")
        print(f"  {account}: {len(groups)} 组 -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
