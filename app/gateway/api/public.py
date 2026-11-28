from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from gateway.cache.semantic import get_stats as cache_stats
from gateway.config import settings
from gateway.knowledge.store import get_domain_stats, get_stats as knowledge_stats

router = APIRouter()


async def _ollama_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


def _require_public() -> None:
    """ステータスページは、設定 status.public が true のときだけ出す（既定は出さない）。"""
    if not settings.status.public:
        raise HTTPException(status_code=404)


@router.get("/stats")
async def public_stats():
    """認証不要の公開統計 API。蓄積データの概要を返す（status.public が true のときだけ）。"""
    _require_public()
    k = await knowledge_stats()
    c = await cache_stats()
    domains = await get_domain_stats()
    ollama_ok = await _ollama_available()

    return {
        "knowledge": {
            "total_entries": k["total_entries"],
            "pending_finetuning": k["pending_finetuning"],
            "by_domain": domains,
        },
        "cache": {
            "total_entries": c["total_entries"],
            "total_hits": c["total_hits"],
        },
        "gateway": {
            "providers": list(settings.llm.providers.keys()),
            "default_provider": settings.llm.default_provider,
            "ollama_available": ollama_ok,
        },
    }


@router.get("/", response_class=HTMLResponse)
async def status_page(request: Request):
    """認証不要のステータスページ。利用方法と蓄積データを表示する（status.public が true のときだけ）。"""
    _require_public()
    base_url = str(request.base_url).rstrip("/")
    return HTMLResponse(_render_html(base_url))


def _render_html(base_url: str) -> str:
    providers = ", ".join(settings.llm.providers.keys()) or "claude"
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI Gateway</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #f0f2f5; color: #1a1a2e; min-height: 100vh; }}
    header {{ background: #1a1a2e; color: #fff; padding: 24px 32px; }}
    header h1 {{ font-size: 1.6rem; font-weight: 700; letter-spacing: -0.5px; }}
    header p  {{ margin-top: 4px; opacity: .65; font-size: .9rem; }}
    .badge {{ display: inline-block; padding: 2px 10px; border-radius: 99px;
              font-size: .75rem; font-weight: 600; margin-left: 10px; vertical-align: middle; }}
    .badge-ok  {{ background: #22c55e; color: #fff; }}
    .badge-off {{ background: #94a3b8; color: #fff; }}
    main {{ max-width: 900px; margin: 32px auto; padding: 0 16px 48px; }}
    section {{ background: #fff; border-radius: 12px; padding: 28px 32px;
               margin-bottom: 24px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
    h2 {{ font-size: 1.05rem; font-weight: 700; margin-bottom: 20px;
          padding-bottom: 10px; border-bottom: 2px solid #f0f2f5; color: #1a1a2e; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px,1fr)); gap: 16px; }}
    .card {{ background: #f8fafc; border-radius: 10px; padding: 20px 16px; text-align: center; }}
    .card .num {{ font-size: 2rem; font-weight: 800; color: #4f46e5; line-height: 1; }}
    .card .lbl {{ margin-top: 6px; font-size: .8rem; color: #64748b; }}
    .domain-bars {{ margin-top: 20px; }}
    .domain-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }}
    .domain-name {{ width: 80px; font-size: .85rem; color: #475569; text-align: right;
                    flex-shrink: 0; font-weight: 500; }}
    .bar-wrap {{ flex: 1; background: #f1f5f9; border-radius: 4px; height: 22px; overflow: hidden; }}
    .bar {{ height: 100%; background: #4f46e5; border-radius: 4px; transition: width .6s ease;
            display: flex; align-items: center; padding-left: 8px; min-width: 32px; }}
    .bar span {{ font-size: .75rem; color: #fff; font-weight: 600; white-space: nowrap; }}
    .refresh {{ font-size: .75rem; color: #94a3b8; margin-top: 16px; text-align: right; }}
    .endpoint {{ background: #1e293b; color: #e2e8f0; border-radius: 8px; padding: 14px 18px;
                 font-family: monospace; font-size: .9rem; margin-bottom: 20px;
                 display: flex; align-items: center; justify-content: space-between; gap: 12px; }}
    .endpoint span {{ color: #7dd3fc; font-weight: 600; word-break: break-all; }}
    code {{ display: block; background: #1e293b; color: #e2e8f0; border-radius: 8px;
            padding: 16px 18px; font-family: monospace; font-size: .82rem; line-height: 1.6;
            white-space: pre-wrap; word-break: break-all; margin-bottom: 16px; }}
    .tab-list {{ display: flex; gap: 4px; margin-bottom: 12px; }}
    .tab {{ padding: 6px 14px; border-radius: 6px; font-size: .82rem; cursor: pointer;
            border: 1px solid #e2e8f0; background: #f8fafc; color: #64748b; }}
    .tab.active {{ background: #4f46e5; color: #fff; border-color: #4f46e5; font-weight: 600; }}
    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; }}
    .kv {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }}
    .kv span {{ background: #f1f5f9; border-radius: 6px; padding: 4px 10px;
                font-size: .8rem; color: #475569; }}
  </style>
</head>
<body>
<header>
  <h1>AI Gateway <span id="ollamabadge" class="badge badge-off">Ollama 確認中…</span></h1>
  <p>社内 LLM プロキシ — OpenAI 互換 API</p>
</header>
<main>

  <!-- 蓄積データ -->
  <section>
    <h2>📚 ローカル蓄積データ</h2>
    <div class="cards">
      <div class="card">
        <div class="num" id="stat-knowledge">—</div>
        <div class="lbl">蓄積 Q&A 件数</div>
      </div>
      <div class="card">
        <div class="num" id="stat-cache">—</div>
        <div class="lbl">キャッシュ件数</div>
      </div>
      <div class="card">
        <div class="num" id="stat-hits">—</div>
        <div class="lbl">キャッシュヒット数</div>
      </div>
      <div class="card">
        <div class="num" id="stat-pending">—</div>
        <div class="lbl">FT 待機 Q&A</div>
      </div>
    </div>
    <div class="domain-bars" id="domain-bars"></div>
    <p class="refresh" id="refresh-ts">読み込み中…</p>
  </section>

  <!-- 利用方法 -->
  <section>
    <h2>🔌 利用方法</h2>

    <div class="endpoint">
      <span>エンドポイント</span>
      <span id="ep">{base_url}/v1/chat/completions</span>
    </div>

    <p style="font-size:.85rem;color:#64748b;margin-bottom:14px;">
      OpenAI SDK のベース URL を以下に差し替えるだけで接続できます。<br>
      <strong>model</strong> に <code style="display:inline;background:none;color:#4f46e5;padding:0;font-size:.85rem;">auto</code>
      を指定するとゲートウェイがプロバイダーを自動選択します。
      利用可能プロバイダー:
    </p>
    <div class="kv">
      {"".join(f'<span>{p}</span>' for p in providers.split(", "))}
    </div>

    <div class="tab-list" style="margin-top:24px;">
      <button class="tab active" onclick="showTab('curl')">curl</button>
      <button class="tab" onclick="showTab('python')">Python</button>
      <button class="tab" onclick="showTab('js')">JavaScript</button>
    </div>

    <div id="tab-curl" class="tab-panel active"><code>curl {base_url}/v1/chat/completions \\
  -H "Authorization: Bearer &lt;GATEWAY_API_KEY&gt;" \\
  -H "Content-Type: application/json" \\
  -d '{{
    "model": "auto",
    "messages": [{{"role": "user", "content": "在庫は何個ありますか？"}}],
    "metadata": {{"app": "my-app", "tenant": "team-a"}}
  }}'</code></div>

    <div id="tab-python" class="tab-panel"><code>from openai import OpenAI

client = OpenAI(
    base_url="{base_url}/v1",
    api_key="&lt;GATEWAY_API_KEY&gt;",
)

response = client.chat.completions.create(
    model="auto",
    messages=[{{"role": "user", "content": "在庫は何個ありますか？"}}],
    extra_body={{"metadata": {{"app": "my-app", "tenant": "team-a"}}}},
)
print(response.choices[0].message.content)</code></div>

    <div id="tab-js" class="tab-panel"><code>const response = await fetch("{base_url}/v1/chat/completions", {{
  method: "POST",
  headers: {{
    "Authorization": "Bearer &lt;GATEWAY_API_KEY&gt;",
    "Content-Type": "application/json",
  }},
  body: JSON.stringify({{
    model: "auto",
    messages: [{{ role: "user", content: "在庫は何個ありますか？" }}],
    metadata: {{ app: "my-app", tenant: "team-a" }},
  }}),
}});
const data = await response.json();
console.log(data.choices[0].message.content);</code></div>

    <p style="font-size:.8rem;color:#94a3b8;margin-top:8px;">
      レスポンスの <strong>metadata.source</strong> で応答元を確認できます:
      <span style="background:#dcfce7;color:#166534;padding:2px 8px;border-radius:4px;font-size:.75rem;">cache</span>
      <span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:.75rem;">local</span>
      <span style="background:#fef9c3;color:#854d0e;padding:2px 8px;border-radius:4px;font-size:.75rem;">external</span>
    </p>
  </section>

</main>

<script>
function showTab(name) {{
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.classList.add('active');
}}

function fmt(n) {{
  if (n === null || n === undefined) return '—';
  return Number(n).toLocaleString('ja-JP');
}}

async function loadStats() {{
  try {{
    const res = await fetch('/stats');
    const d = await res.json();

    document.getElementById('stat-knowledge').textContent = fmt(d.knowledge.total_entries);
    document.getElementById('stat-cache').textContent     = fmt(d.cache.total_entries);
    document.getElementById('stat-hits').textContent      = fmt(d.cache.total_hits);
    document.getElementById('stat-pending').textContent   = fmt(d.knowledge.pending_finetuning);

    const badge = document.getElementById('ollamabadge');
    if (d.gateway.ollama_available) {{
      badge.textContent = 'Ollama ✓'; badge.className = 'badge badge-ok';
    }} else {{
      badge.textContent = 'Ollama オフライン'; badge.className = 'badge badge-off';
    }}

    const bars = d.knowledge.by_domain;
    const container = document.getElementById('domain-bars');
    if (bars && bars.length > 0) {{
      const max = Math.max(...bars.map(b => b.count), 1);
      container.innerHTML = '<p style="font-size:.8rem;color:#64748b;margin-bottom:10px;">ドメイン別 Q&A 件数</p>'
        + bars.map(b => {{
          const pct = Math.max(4, Math.round(b.count / max * 100));
          const label = {{inventory:'在庫', hr:'HR', general:'汎用'}}[b.domain] || b.domain;
          return `<div class="domain-row">
            <div class="domain-name">${{label}}</div>
            <div class="bar-wrap"><div class="bar" style="width:${{pct}}%"><span>${{fmt(b.count)}}</span></div></div>
          </div>`;
        }}).join('');
    }} else {{
      container.innerHTML = '<p style="font-size:.85rem;color:#94a3b8;margin-top:12px;">まだデータが蓄積されていません</p>';
    }}

    const now = new Date().toLocaleTimeString('ja-JP');
    document.getElementById('refresh-ts').textContent = `最終更新: ${{now}} (30秒ごとに自動更新)`;
  }} catch(e) {{
    document.getElementById('refresh-ts').textContent = '統計の取得に失敗しました';
  }}
}}

loadStats();
setInterval(loadStats, 30000);
</script>
</body>
</html>"""
