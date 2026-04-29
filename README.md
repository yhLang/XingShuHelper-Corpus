# XingShuHelper-Corpus

行恕客服助手金标知识库的数据仓库 + 构建管线。

## 仓库结构

```
gold/                           # 人工维护的金标 QA（PR/Web 编辑入口）
  xingshu.jsonl                 # 一行一条 JSON：{scene, questions[], answer, risk_note}
  kirin.jsonl
dist/                           # CI 自动产出，App 直接拉这里
  <account>.manifest.json       # {version, count, updated_at, files{texts,embeddings}}
  <account>/qa_<account>_texts.json
  <account>/qa_<account>_embeddings.bin
tools/
  build_corpus.py               # gold/*.jsonl → dist/*  （embed + manifest）
  export_initial.py             # 一次性：从 App assets 反向导出 gold/*.jsonl
.github/workflows/
  build.yml                     # 监听 gold/* 变更，跑 build_corpus.py 并自动 commit dist/
```

## 工作流

1. **维护者**改 `gold/<account>.jsonl`（直接 commit、PR、或 Web 端提交）
2. **CI** 自动跑 `build_corpus.py`：
   - 读 jsonl，展开成单 question 条目
   - 调 DashScope `text-embedding-v3` 拿向量（增量缓存）
   - 写 `dist/<account>/*.json|*.bin` 和 `dist/<account>.manifest.json`
   - manifest 的 `version` 自增,`sha256` 校验
   - 把 dist/ 变更 commit 回 main
3. **App** 启动或用户手动触发 → 拉 manifest（走反代镜像）→ 比版本号 → 下载新文件 → 校验 sha256 → 替换本地

## 本地构建

```bash
python -m venv .venv && source .venv/bin/activate
pip install openai
export DASHSCOPE_API_KEY=sk-xxx
python tools/build_corpus.py --account xingshu
python tools/build_corpus.py --account kirin
```

## CI 配置

GitHub repo Settings → Secrets → `DASHSCOPE_API_KEY` 配好即可。

## App 端配置

在主项目 `local.properties` 加：
```
CORPUS_REPO=yhLang/XingShuHelper-Corpus
CORPUS_BRANCH=main
```

App 启动后在「设置 → 金标知识库」里点检查更新。
