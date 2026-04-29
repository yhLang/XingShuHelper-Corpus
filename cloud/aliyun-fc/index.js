/**
 * 阿里云函数计算（FC）HTTP 触发器：
 * 接收 App 端上传的金标 QA → 追加到 GitHub gold/<account>.jsonl → 触发 CI 重新构建。
 *
 * 部署：
 *   1. 阿里云函数计算控制台 → 创建函数 → 运行环境 Node.js 18
 *   2. 触发器：HTTP，认证方式 anonymous（鉴权由 SHARED_SECRET 自己做）
 *   3. 环境变量：
 *        GITHUB_REPO     = yhLangMac/XingShuHelper-Corpus
 *        GITHUB_BRANCH   = main
 *        GITHUB_PAT      = github_pat_xxx (需要 repo 写权限)
 *        SHARED_SECRET   = 任意长字符串，App BuildConfig 里也存一份
 *   4. 把本目录所有文件打包上传
 *
 * App 端调用：
 *   POST https://<your-fc-url>
 *   Body: { "secret": "...", "account": "xingshu", "qa": {scene, questions:[], answer, risk_note} }
 */

const https = require('https');

function ghRequest(method, path, token, body) {
  return new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : null;
    const req = https.request({
      hostname: 'api.github.com',
      path,
      method,
      headers: {
        'Authorization': `Bearer ${token}`,
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'XingShuHelper-Corpus-Bot',
        ...(data ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } : {}),
      },
    }, resp => {
      let chunks = '';
      resp.on('data', c => chunks += c);
      resp.on('end', () => {
        if (resp.statusCode >= 200 && resp.statusCode < 300) {
          resolve(chunks ? JSON.parse(chunks) : {});
        } else {
          reject(new Error(`GitHub ${resp.statusCode}: ${chunks}`));
        }
      });
    });
    req.on('error', reject);
    if (data) req.write(data);
    req.end();
  });
}

function validQa(qa) {
  if (!qa || typeof qa !== 'object') return false;
  if (!qa.answer || typeof qa.answer !== 'string') return false;
  if (!Array.isArray(qa.questions) || qa.questions.length === 0) return false;
  if (qa.questions.some(q => typeof q !== 'string' || !q.trim())) return false;
  return true;
}

exports.handler = async (req, resp, _ctx) => {
  resp.setHeader('Content-Type', 'application/json; charset=utf-8');

  if (req.method !== 'POST') {
    resp.setStatusCode(405);
    return resp.send(JSON.stringify({ ok: false, error: 'method not allowed' }));
  }

  let payload;
  try {
    const raw = await new Promise((r, e) => {
      let buf = '';
      req.on('data', c => buf += c);
      req.on('end', () => r(buf));
      req.on('error', e);
    });
    payload = JSON.parse(raw);
  } catch (e) {
    resp.setStatusCode(400);
    return resp.send(JSON.stringify({ ok: false, error: 'invalid json' }));
  }

  const { secret, account, qa } = payload;
  if (secret !== process.env.SHARED_SECRET) {
    resp.setStatusCode(401);
    return resp.send(JSON.stringify({ ok: false, error: 'unauthorized' }));
  }
  if (!['xingshu', 'kirin'].includes(account)) {
    resp.setStatusCode(400);
    return resp.send(JSON.stringify({ ok: false, error: 'invalid account' }));
  }
  if (!validQa(qa)) {
    resp.setStatusCode(400);
    return resp.send(JSON.stringify({ ok: false, error: 'invalid qa' }));
  }

  const repo = process.env.GITHUB_REPO;
  const branch = process.env.GITHUB_BRANCH || 'main';
  const token = process.env.GITHUB_PAT;
  const path = `gold/${account}.jsonl`;
  const apiPath = `/repos/${repo}/contents/${path}?ref=${branch}`;

  try {
    // 1. 拉当前文件（带 sha）
    const cur = await ghRequest('GET', apiPath, token);
    const oldText = Buffer.from(cur.content, 'base64').toString('utf-8');

    // 2. 追加一行（标准化字段）
    const line = JSON.stringify({
      scene: qa.scene || '其他',
      questions: qa.questions.map(s => s.trim()).filter(Boolean),
      answer: qa.answer,
      risk_note: qa.risk_note || '',
    });
    const newText = oldText.endsWith('\n') ? oldText + line + '\n' : oldText + '\n' + line + '\n';
    const newB64 = Buffer.from(newText, 'utf-8').toString('base64');

    // 3. PUT 回 GitHub
    const putResp = await ghRequest('PUT', `/repos/${repo}/contents/${path}`, token, {
      message: `app: 上传金标 QA → ${account} (${qa.scene || '其他'})`,
      content: newB64,
      sha: cur.sha,
      branch,
    });

    resp.setStatusCode(200);
    return resp.send(JSON.stringify({
      ok: true,
      commit: putResp.commit?.sha,
      account,
    }));
  } catch (e) {
    resp.setStatusCode(500);
    return resp.send(JSON.stringify({ ok: false, error: String(e.message || e) }));
  }
};
