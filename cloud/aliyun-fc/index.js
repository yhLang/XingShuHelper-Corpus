/**
 * 阿里云函数计算（FC）HTTP 触发器：
 * 接收 App 端上传的金标 QA → 追加到 GitHub gold/<account>.jsonl → 触发 CI 重新构建。
 *
 * 部署：阿里云 FC 3.0 → Web 函数 → Node.js 18 自定义运行时
 *   - 必须随 zip 一起上传 bootstrap（chmod +x，里面 `exec node /code/index.js`）
 *   - 监听端口 9000（FC_SERVER_PORT，由 FC 注入）
 *   - 触发器：HTTP，认证方式 anonymous，仅允许 POST
 *   - 4 个环境变量（GITHUB_REPO / GITHUB_BRANCH / GITHUB_PAT / SHARED_SECRET）
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

async function handle(req, res) {
  const json = (status, obj) => {
    res.statusCode = status;
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.end(JSON.stringify(obj));
  };

  if (req.method !== 'POST') return json(405, { ok: false, error: 'method not allowed' });

  let raw = '';
  await new Promise((r, e) => { req.on('data', c => raw += c); req.on('end', r); req.on('error', e); });
  let payload;
  try { payload = JSON.parse(raw); }
  catch { return json(400, { ok: false, error: 'invalid json' }); }

  const { secret, account, qa } = payload;
  if (secret !== process.env.SHARED_SECRET) return json(401, { ok: false, error: 'unauthorized' });
  if (!['xingshu', 'kirin'].includes(account)) return json(400, { ok: false, error: 'invalid account' });
  if (!validQa(qa)) return json(400, { ok: false, error: 'invalid qa' });

  const repo = process.env.GITHUB_REPO;
  const branch = process.env.GITHUB_BRANCH || 'main';
  const token = process.env.GITHUB_PAT;
  const path = `gold/${account}.jsonl`;

  try {
    const cur = await ghRequest('GET', `/repos/${repo}/contents/${path}?ref=${branch}`, token);
    const oldText = Buffer.from(cur.content, 'base64').toString('utf-8');
    const line = JSON.stringify({
      scene: qa.scene || '其他',
      questions: qa.questions.map(s => s.trim()).filter(Boolean),
      answer: qa.answer,
      risk_note: qa.risk_note || '',
    });
    const newText = oldText.endsWith('\n') ? oldText + line + '\n' : oldText + '\n' + line + '\n';
    const putResp = await ghRequest('PUT', `/repos/${repo}/contents/${path}`, token, {
      message: `app: 上传金标 QA → ${account} (${qa.scene || '其他'})`,
      content: Buffer.from(newText, 'utf-8').toString('base64'),
      sha: cur.sha,
      branch,
    });
    return json(200, { ok: true, commit: putResp.commit?.sha, account });
  } catch (e) {
    return json(500, { ok: false, error: String(e.message || e) });
  }
}

const port = process.env.FC_SERVER_PORT || 9000;
require('http').createServer((req, res) => {
  handle(req, res).catch(e => {
    res.statusCode = 500;
    res.end(JSON.stringify({ ok: false, error: String(e.message || e) }));
  });
}).listen(port, () => console.log(`listening on :${port}`));
