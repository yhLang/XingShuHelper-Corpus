# 阿里云函数计算中转 (FC)

App 端在大陆访问 `api.github.com` 不稳定，本函数作为中转：App → FC（国内可达）→ GitHub。

## 部署步骤

### 1. 创建 GitHub PAT

GitHub → Settings → Developer settings → Personal access tokens (Fine-grained)
- Repository access: `XingShuHelper-Corpus` only
- Permissions: Contents (Read and write)
- 复制生成的 token

### 2. 阿里云函数计算控制台

1. 控制台 → 函数计算 FC 3.0 → 创建函数
   - 创建方式：使用内置运行时
   - 运行时：Node.js 18
   - 处理程序：`index.handler`
   - 上传代码：把本目录（`index.js` + `package.json`）打成 zip 上传
2. 触发器：HTTP，认证方式 `anonymous`，请求方式 `POST`
3. 环境变量：
   - `GITHUB_REPO` = `yhLang/XingShuHelper-Corpus`
   - `GITHUB_BRANCH` = `main`
   - `GITHUB_PAT` = 步骤 1 拿到的 token
   - `SHARED_SECRET` = 一段随机字符串（自己用 `openssl rand -hex 32` 生成）
4. 函数 URL：`https://<service>-<function>.<region>.fcapp.run/`

### 3. App 端配置

主项目 `local.properties` 加：
```
CORPUS_UPLOAD_URL=https://xxx.fcapp.run/
CORPUS_UPLOAD_SECRET=<步骤 2 的 SHARED_SECRET>
```
重新打 APK，App 添加金标后会出现「同步上传到云」按钮。

## 调用协议

```http
POST /
Content-Type: application/json

{
  "secret": "...",
  "account": "xingshu" | "kirin",
  "qa": {
    "scene": "试听课",
    "questions": ["可以试听吗", "有体验课吗"],
    "answer": "您放心，第一次来上课是免费的…",
    "risk_note": ""
  }
}
```

成功返回：
```json
{ "ok": true, "commit": "<sha>", "account": "xingshu" }
```

失败返回 4xx/5xx + `{"ok": false, "error": "..."}`。

## 安全模型

- `SHARED_SECRET` 写进 App `BuildConfig`，**只有从你打的 release APK 里反编译能拿到**。这不是高强度鉴权，只是防止有人扫到 FC URL 后随便调用。
- `GITHUB_PAT` 只在 FC 环境变量里，App 端拿不到。
- 真出现滥用就轮换 SHARED_SECRET + 重打 APK。

## 本地测试

```bash
# 启 nodejs 模拟环境（实际部署不需要）
SHARED_SECRET=test GITHUB_REPO=foo/bar GITHUB_BRANCH=main GITHUB_PAT=xxx \
  node -e "
    const h = require('./index').handler;
    const req = { method: 'POST', on: (e, cb) => e === 'data' ? cb(JSON.stringify({secret:'test',account:'xingshu',qa:{scene:'测试',questions:['q1'],answer:'a'}})) : e === 'end' ? cb() : null };
    const resp = { setHeader:()=>{}, setStatusCode:c=>console.log('status',c), send:b=>console.log(b) };
    h(req, resp);
  "
```
