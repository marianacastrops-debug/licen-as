"""
InfinityLive - Backend de Licenças v1.1
Flask + Supabase
"""
import os, json, random, string
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, jsonify

app = Flask(__name__)

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL  = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY  = os.environ.get("SUPABASE_KEY", "")
ADMIN_TOKEN   = os.environ.get("ADMIN_TOKEN", "TROQUE_ESTE_TOKEN")

def get_sb():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Helpers ───────────────────────────────────────────────────────────────────
def agora():
    return datetime.now(timezone.utc).isoformat()

def gerar_chave():
    chars = string.ascii_uppercase + string.digits
    bloco = ''.join(random.choices(chars, k=4))
    return "IL-" + bloco

def cors(response):
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Admin-Token"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, DELETE"
    return response

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("X-Admin-Token", "")
        if token != ADMIN_TOKEN:
            return jsonify({"ok": False, "msg": "Não autorizado."}), 401
        return f(*args, **kwargs)
    return decorated

@app.after_request
def after(response):
    return cors(response)

@app.route("/", methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def options(path=""):
    return jsonify({"ok": True})

@app.route("/", methods=["GET"])
def index():
    return jsonify({"ok": True, "msg": "InfinityLive Licenças v1.1"})

# ══════════════════════════════════════════════════════════════════════════════
#  ROTAS PÚBLICAS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/ativar", methods=["POST"])
def ativar():
    body = request.get_json(silent=True) or {}
    chave       = (body.get("chave") or "").strip().upper()
    device_uuid = (body.get("device_uuid") or "").strip()
    device_nome = (body.get("device_nome") or "Desconhecido").strip()[:60]

    if not chave or not device_uuid:
        return jsonify({"ok": False, "msg": "Dados incompletos."})

    sb = get_sb()
    res = sb.table("licencas").select("*").eq("chave", chave).execute()
    if not res.data:
        return jsonify({"ok": False, "msg": "Chave não encontrada."})

    lic = res.data[0]

    if not lic["ativa"]:
        return jsonify({"ok": False, "msg": "Chave inativa ou revogada."})

    if lic["expira_em"]:
        expira = datetime.fromisoformat(lic["expira_em"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expira:
            return jsonify({"ok": False, "msg": "Chave expirada."})

    devs_res = sb.table("licenca_devices").select("*").eq("licenca_id", lic["id"]).execute()
    devices  = devs_res.data or []

    device_existente = next((d for d in devices if d["device_uuid"] == device_uuid), None)
    if device_existente:
        sb.table("licenca_devices").update({"ultimo_acesso": agora()}).eq("id", device_existente["id"]).execute()
        return jsonify({"ok": True, "msg": "Dispositivo já autorizado."})

    max_dev = lic.get("max_devices", 1)
    if len(devices) >= max_dev:
        return jsonify({"ok": False, "msg": f"Limite de dispositivos atingido ({max_dev}/{max_dev}). Contate a Mariana."})

    sb.table("licenca_devices").insert({
        "licenca_id":    lic["id"],
        "device_uuid":   device_uuid,
        "device_nome":   device_nome,
        "ativado_em":    agora(),
        "ultimo_acesso": agora()
    }).execute()

    if not lic.get("ativada_em"):
        sb.table("licencas").update({"ativada_em": agora()}).eq("id", lic["id"]).execute()

    return jsonify({"ok": True, "msg": "Dispositivo autorizado com sucesso!"})


@app.route("/validar", methods=["POST"])
def validar():
    body = request.get_json(silent=True) or {}
    chave       = (body.get("chave") or "").strip().upper()
    device_uuid = (body.get("device_uuid") or "").strip()

    if not chave or not device_uuid:
        return jsonify({"ok": False, "msg": "Dados incompletos."})

    sb  = get_sb()
    res = sb.table("licencas").select("*").eq("chave", chave).execute()
    if not res.data:
        return jsonify({"ok": False, "msg": "Chave não encontrada."})

    lic = res.data[0]

    if not lic["ativa"]:
        return jsonify({"ok": False, "msg": "Chave revogada."})

    if lic["expira_em"]:
        expira = datetime.fromisoformat(lic["expira_em"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expira:
            return jsonify({"ok": False, "msg": "Chave expirada."})

    devs_res = sb.table("licenca_devices").select("*").eq("licenca_id", lic["id"]).eq("device_uuid", device_uuid).execute()
    if not devs_res.data:
        return jsonify({"ok": False, "msg": "Dispositivo não autorizado para esta chave."})

    sb.table("licenca_devices").update({"ultimo_acesso": agora()}).eq("id", devs_res.data[0]["id"]).execute()
    return jsonify({"ok": True, "msg": "Acesso válido."})


# ══════════════════════════════════════════════════════════════════════════════
#  ROTAS ADMIN
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/admin/chaves", methods=["GET"])
@admin_required
def admin_listar_chaves():
    sb  = get_sb()
    res = sb.table("licencas").select("*").order("criada_em", desc=True).execute()
    chaves = res.data or []
    for c in chaves:
        devs = sb.table("licenca_devices").select("*").eq("licenca_id", c["id"]).order("ativado_em").execute()
        c["devices"]     = devs.data or []
        c["slots_usados"] = len(c["devices"])
    return jsonify({"ok": True, "chaves": chaves})


@app.route("/admin/gerar", methods=["POST"])
@admin_required
def admin_gerar():
    body        = request.get_json(silent=True) or {}
    tipo        = body.get("tipo", "mensal")
    max_devices = int(body.get("max_devices", 1))
    expira_em   = body.get("expira_em", None)
    quantidade  = min(int(body.get("quantidade", 1)), 50)
    observacao  = (body.get("observacao") or "")[:200]

    sb = get_sb()
    geradas = []
    for _ in range(quantidade):
        chave = gerar_chave()
        sb.table("licencas").insert({
            "chave":       chave,
            "tipo":        tipo,
            "max_devices": max_devices,
            "ativa":       True,
            "expira_em":   expira_em,
            "criada_em":   agora(),
            "observacao":  observacao,
        }).execute()
        geradas.append(chave)

    return jsonify({"ok": True, "chaves": geradas})


@app.route("/admin/revogar/<chave_id>", methods=["POST"])
@admin_required
def admin_revogar(chave_id):
    get_sb().table("licencas").update({"ativa": False}).eq("id", chave_id).execute()
    return jsonify({"ok": True, "msg": "Chave revogada."})


@app.route("/admin/reativar/<chave_id>", methods=["POST"])
@admin_required
def admin_reativar(chave_id):
    get_sb().table("licencas").update({"ativa": True}).eq("id", chave_id).execute()
    return jsonify({"ok": True, "msg": "Chave reativada."})


@app.route("/admin/resetar_devices/<chave_id>", methods=["POST"])
@admin_required
def admin_resetar_devices(chave_id):
    get_sb().table("licenca_devices").delete().eq("licenca_id", chave_id).execute()
    return jsonify({"ok": True, "msg": "Devices resetados. Slots liberados."})


@app.route("/admin/remover_device/<device_id>", methods=["DELETE"])
@admin_required
def admin_remover_device(device_id):
    get_sb().table("licenca_devices").delete().eq("id", device_id).execute()
    return jsonify({"ok": True, "msg": "Device removido."})


@app.route("/admin/atualizar/<chave_id>", methods=["POST"])
@admin_required
def admin_atualizar(chave_id):
    body   = request.get_json(silent=True) or {}
    update = {}
    if "max_devices" in body: update["max_devices"] = int(body["max_devices"])
    if "expira_em"   in body: update["expira_em"]   = body["expira_em"]
    if "observacao"  in body: update["observacao"]  = body["observacao"][:200]
    if update:
        get_sb().table("licencas").update(update).eq("id", chave_id).execute()
    return jsonify({"ok": True, "msg": "Chave atualizada."})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


# ══════════════════════════════════════════════════════════════════════════════
#  PAINEL ADMIN WEB
# ══════════════════════════════════════════════════════════════════════════════

ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>InfinityLive · Admin</title>
<style>
:root{--bg:#060C18;--surface:#0D1526;--card:#111927;--border:#1E2D45;--red:#E8000F;--green:#00E676;--yellow:#FFD600;--blue:#00C8FF;--text:#EEF0F6;--muted:#6B7A90;--danger:#FF3355}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:Inter,system-ui,sans-serif;font-size:13px;min-height:100vh}

/* LOGIN */
#login-screen{display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px}
.login-box{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:40px 32px;width:100%;max-width:360px;text-align:center}
.login-logo{width:52px;height:52px;background:var(--red);border-radius:14px;display:flex;align-items:center;justify-content:center;font-size:26px;font-weight:900;color:#fff;margin:0 auto 16px}
.login-title{font-size:20px;font-weight:800;margin-bottom:4px}
.login-sub{color:var(--muted);font-size:12px;margin-bottom:28px}
.login-input{width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:10px;padding:12px 16px;font-size:13px;outline:none;margin-bottom:12px;font-family:inherit}
.login-input:focus{border-color:var(--red)}
.login-btn{width:100%;background:var(--red);color:#fff;border:none;border-radius:10px;padding:13px;font-size:14px;font-weight:800;cursor:pointer;letter-spacing:.3px}
.login-btn:hover{opacity:.88}
.login-err{color:var(--danger);font-size:12px;margin-top:10px;min-height:18px}

/* HEADER */
#app-screen{display:none}
.header{background:var(--surface);border-bottom:1px solid var(--border);padding:14px 24px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}
.logo{display:flex;align-items:center;gap:10px}
.logo-icon{width:32px;height:32px;background:var(--red);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:900;color:#fff}
.logo-txt{font-size:16px;font-weight:800}
.logo-txt span{color:var(--red)}
.btn-sair{background:var(--border);color:var(--muted);border:none;border-radius:8px;padding:7px 14px;font-size:12px;font-weight:700;cursor:pointer}
.btn-sair:hover{color:var(--text)}

/* MAIN */
.main{padding:24px;max-width:1200px;margin:0 auto}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px 20px}
.stat-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.stat-value{font-size:28px;font-weight:800;margin-top:6px}
.stat-value.green{color:var(--green)}.stat-value.red{color:var(--danger)}.stat-value.blue{color:var(--blue)}.stat-value.yellow{color:var(--yellow)}
.toolbar{display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap}
.toolbar-title{font-size:15px;font-weight:700;flex:1}
.btn{padding:8px 16px;border-radius:8px;border:none;font-size:12px;font-weight:700;cursor:pointer;transition:opacity .15s}
.btn:hover{opacity:.85}
.btn-primary{background:var(--red);color:#fff}.btn-success{background:var(--green);color:#000}
.btn-warning{background:var(--yellow);color:#000}.btn-danger{background:var(--danger);color:#fff}
.btn-ghost{background:var(--border);color:var(--text)}.btn-sm{padding:5px 10px;font-size:11px}
.filter-input,.filter-select{background:var(--card);border:1px solid var(--border);color:var(--text);border-radius:8px;padding:8px 14px;font-size:12px;outline:none}
.filter-input{width:220px}
.table-wrap{background:var(--card);border:1px solid var(--border);border-radius:12px;overflow:hidden}
table{width:100%;border-collapse:collapse}
thead th{background:var(--surface);padding:11px 16px;text-align:left;font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--border)}
tbody tr{border-bottom:1px solid var(--border);transition:background .1s}
tbody tr:last-child{border-bottom:none}
tbody tr:hover{background:rgba(255,255,255,0.025)}
tbody td{padding:12px 16px;vertical-align:middle}
.badge{display:inline-flex;align-items:center;padding:3px 9px;border-radius:20px;font-size:11px;font-weight:700;letter-spacing:.3px}
.badge-ativa{background:rgba(0,230,118,.15);color:var(--green)}.badge-inativa{background:rgba(255,51,85,.15);color:var(--danger)}
.badge-expirada{background:rgba(255,214,0,.15);color:var(--yellow)}.badge-mensal{background:rgba(0,200,255,.12);color:var(--blue)}
.badge-mentoria{background:rgba(232,0,15,.12);color:#ff6b6b}.badge-vitalicio{background:rgba(0,230,118,.12);color:var(--green)}
.chave-txt{font-family:monospace;font-size:14px;font-weight:700;letter-spacing:2px;color:var(--blue)}
.slots-bar{display:flex;align-items:center;gap:8px}
.slots-dots{display:flex;gap:4px}
.slot-dot{width:10px;height:10px;border-radius:50%;background:var(--border)}
.slot-dot.usado{background:var(--green)}.slot-dot.cheio{background:var(--danger)}
.slots-txt{font-size:11px;color:var(--muted);white-space:nowrap}
.actions{display:flex;gap:6px;flex-wrap:wrap}
.devices-wrap{background:var(--bg);border:1px solid var(--border);border-radius:8px;overflow:hidden}
.device-item{display:flex;align-items:center;gap:10px;padding:9px 12px;border-bottom:1px solid rgba(255,255,255,0.04);font-size:11px}
.device-item:last-child{border-bottom:none}
.device-icon{width:28px;height:28px;background:rgba(0,200,255,0.1);border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0}
.device-info{flex:1;min-width:0}
.device-nome{font-weight:700;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.device-uuid{font-family:monospace;font-size:10px;color:var(--muted);margin-top:1px}
.device-acesso{font-size:10px;color:var(--muted);white-space:nowrap}
.row-detail{background:rgba(0,0,0,.3)!important}
.row-detail td{padding:0 16px 14px!important}
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(4,7,16,0.85);z-index:200;align-items:center;justify-content:center}
.modal-overlay.show{display:flex}
.modal{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:28px;width:420px;max-width:95vw}
.modal-title{font-size:15px;font-weight:800;margin-bottom:20px}
.form-group{margin-bottom:14px}
.form-label{font-size:11px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px;display:block}
.form-input,.form-select{width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:8px;padding:10px 14px;font-size:13px;outline:none;font-family:inherit}
.form-input:focus,.form-select:focus{border-color:var(--red)}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.modal-actions{display:flex;gap:10px;margin-top:22px;justify-content:flex-end}
#toast{position:fixed;bottom:24px;right:24px;z-index:999;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 20px;font-size:13px;font-weight:600;display:none;align-items:center;gap:8px;box-shadow:0 8px 32px rgba(0,0,0,.5)}
#toast.show{display:flex}
#toast.ok{border-color:rgba(0,230,118,.4);color:var(--green)}
#toast.err{border-color:rgba(255,51,85,.4);color:var(--danger)}
.loading{color:var(--muted);text-align:center;padding:40px;font-size:13px}
.empty{color:var(--muted);text-align:center;padding:40px;font-size:13px}
@media(max-width:768px){.stats{grid-template-columns:1fr 1fr}}
</style>
</head>
<body>

<!-- LOGIN -->
<div id="login-screen">
  <div class="login-box">
    <div class="login-logo">∞</div>
    <div class="login-title">Infinity Live</div>
    <div class="login-sub">Painel de Administração</div>
    <input class="login-input" id="login-token" type="password" placeholder="Token de acesso" autocomplete="current-password">
    <button class="login-btn" onclick="fazerLogin()">Entrar</button>
    <div class="login-err" id="login-err"></div>
  </div>
</div>

<!-- APP -->
<div id="app-screen">
  <div class="header">
    <div class="logo">
      <div class="logo-icon">∞</div>
      <div class="logo-txt">Infinity<span>Live</span> · Admin</div>
    </div>
    <div style="display:flex;align-items:center;gap:10px">
      <button class="btn btn-ghost btn-sm" onclick="carregar()">↻ Atualizar</button>
      <button class="btn-sair" onclick="sair()">Sair</button>
    </div>
  </div>

  <div class="main">
    <div class="stats">
      <div class="stat-card"><div class="stat-label">Total de chaves</div><div class="stat-value blue" id="s-total">—</div></div>
      <div class="stat-card"><div class="stat-label">Ativas</div><div class="stat-value green" id="s-ativas">—</div></div>
      <div class="stat-card"><div class="stat-label">Revogadas</div><div class="stat-value red" id="s-inativas">—</div></div>
      <div class="stat-card"><div class="stat-label">Expiradas</div><div class="stat-value yellow" id="s-expiradas">—</div></div>
    </div>
    <div class="toolbar">
      <div class="toolbar-title">Chaves de licença</div>
      <input class="filter-input" id="filtro-busca" placeholder="Buscar chave, cliente…" oninput="filtrar()">
      <select class="filter-select" id="filtro-tipo" onchange="filtrar()">
        <option value="">Todos os tipos</option>
        <option value="mensal">Mensal</option>
        <option value="mentoria">Mentoria</option>
        <option value="vitalicio">Vitalício</option>
      </select>
      <select class="filter-select" id="filtro-status" onchange="filtrar()">
        <option value="">Todos os status</option>
        <option value="ativa">Ativas</option>
        <option value="inativa">Inativas</option>
        <option value="expirada">Expiradas</option>
      </select>
      <button class="btn btn-primary" onclick="abrirModalGerar()">＋ Gerar chave</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Chave</th><th>Cliente / Obs.</th><th>Tipo</th><th>Status</th>
            <th>Devices</th><th>Expira em</th><th>Último acesso</th><th>Ações</th>
          </tr>
        </thead>
        <tbody id="tabela-body">
          <tr><td colspan="8" class="loading">Faça login para carregar.</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</div>

<!-- MODAL GERAR -->
<div class="modal-overlay" id="modal-gerar">
  <div class="modal">
    <div class="modal-title">＋ Gerar nova(s) chave(s)</div>
    <div class="form-group"><label class="form-label">Cliente / Observação</label><input class="form-input" id="g-obs" placeholder="Ex: João Silva — Mentoria Março"></div>
    <div class="form-row">
      <div class="form-group"><label class="form-label">Tipo</label><select class="form-select" id="g-tipo"><option value="mensal">Mensal</option><option value="mentoria">Mentoria</option><option value="vitalicio">Vitalício</option></select></div>
      <div class="form-group"><label class="form-label">Máx. dispositivos</label><input class="form-input" id="g-maxdev" type="number" value="1" min="1" max="10"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label class="form-label">Expira em (vazio = sem expiração)</label><input class="form-input" id="g-expira" type="date"></div>
      <div class="form-group"><label class="form-label">Quantidade</label><input class="form-input" id="g-qtd" type="number" value="1" min="1" max="50"></div>
    </div>
    <div class="modal-actions">
      <button class="btn btn-ghost" onclick="fecharModal('modal-gerar')">Cancelar</button>
      <button class="btn btn-primary" onclick="gerarChave()">Gerar</button>
    </div>
  </div>
</div>

<!-- MODAL EDITAR -->
<div class="modal-overlay" id="modal-editar">
  <div class="modal">
    <div class="modal-title">✏️ Editar chave</div>
    <input type="hidden" id="e-id">
    <div class="form-group"><label class="form-label">Cliente / Observação</label><input class="form-input" id="e-obs"></div>
    <div class="form-row">
      <div class="form-group"><label class="form-label">Máx. dispositivos</label><input class="form-input" id="e-maxdev" type="number" min="1" max="10"></div>
      <div class="form-group"><label class="form-label">Nova expiração (vazio = sem expiração)</label><input class="form-input" id="e-expira" type="date"></div>
    </div>
    <div class="modal-actions">
      <button class="btn btn-ghost" onclick="fecharModal('modal-editar')">Cancelar</button>
      <button class="btn btn-success" onclick="salvarEdicao()">Salvar</button>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
const SERVIDOR = 'https://infinitylive-licencas.onrender.com';
let todasChaves = [];
let expandidoId = null;
let adminToken  = '';

function fazerLogin() {
  const t = document.getElementById('login-token').value.trim();
  if (!t) { document.getElementById('login-err').textContent = 'Digite o token.'; return; }
  const btn = document.querySelector('.login-btn');
  const err = document.getElementById('login-err');
  btn.disabled = true;
  btn.textContent = 'Conectando...';
  err.style.color = 'var(--muted)';
  err.textContent = 'Aguardando servidor...';
  let dots = 0;
  const dotTimer = setInterval(() => {
    dots = (dots + 1) % 4;
    err.textContent = 'Aguardando servidor' + '.'.repeat(dots+1);
  }, 600);
  fetch(SERVIDOR + '/admin/chaves', {
    headers: { 'X-Admin-Token': t }
  })
  .then(r => r.json())
  .then(res => {
    clearInterval(dotTimer);
    btn.disabled = false;
    btn.textContent = 'Entrar';
    if (!res.ok) {
      err.style.color = 'var(--danger)';
      err.textContent = 'Token invalido.';
      return;
    }
    adminToken = t;
    sessionStorage.setItem('il_token', t);
    document.getElementById('login-screen').style.display = 'none';
    document.getElementById('app-screen').style.display   = 'block';
    todasChaves = res.chaves || [];
    atualizarStats();
    filtrar();
  })
  .catch(() => {
    clearInterval(dotTimer);
    btn.disabled = false;
    btn.textContent = 'Entrar';
    err.style.color = 'var(--danger)';
    err.textContent = 'Erro de conexao. Tente novamente.';
  });
}

function sair() {
  sessionStorage.removeItem('il_token');
  adminToken = '';
  document.getElementById('login-screen').style.display = 'flex';
  document.getElementById('app-screen').style.display   = 'none';
  document.getElementById('login-token').value = '';
}

async function api(path, method='GET', body=null) {
  const opts = { method, headers: { 'Content-Type': 'application/json', 'X-Admin-Token': adminToken } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(SERVIDOR + path, opts);
  return r.json();
}

async function carregar() {
  document.getElementById('tabela-body').innerHTML = '<tr><td colspan="8" class="loading">Carregando…</td></tr>';
  const res = await api('/admin/chaves');
  if (!res.ok) { toast('Erro ao carregar.', 'err'); return; }
  todasChaves = res.chaves || [];
  atualizarStats();
  filtrar();
}

function atualizarStats() {
  const agora = new Date();
  let ativas=0, inativas=0, expiradas=0;
  todasChaves.forEach(c => {
    if (!c.ativa) { inativas++; return; }
    if (c.expira_em && new Date(c.expira_em) < agora) { expiradas++; return; }
    ativas++;
  });
  document.getElementById('s-total').textContent    = todasChaves.length;
  document.getElementById('s-ativas').textContent   = ativas;
  document.getElementById('s-inativas').textContent = inativas;
  document.getElementById('s-expiradas').textContent = expiradas;
}

function filtrar() {
  const busca  = document.getElementById('filtro-busca').value.toLowerCase();
  const tipo   = document.getElementById('filtro-tipo').value;
  const status = document.getElementById('filtro-status').value;
  const agora  = new Date();
  const filtradas = todasChaves.filter(c => {
    if (busca && !c.chave.toLowerCase().includes(busca) && !(c.observacao||'').toLowerCase().includes(busca)) return false;
    if (tipo && c.tipo !== tipo) return false;
    if (status === 'ativa')    { if (!c.ativa || (c.expira_em && new Date(c.expira_em) < agora)) return false; }
    if (status === 'inativa')  { if (c.ativa) return false; }
    if (status === 'expirada') { if (!c.expira_em || new Date(c.expira_em) >= agora) return false; }
    return true;
  });
  renderTabela(filtradas);
}

function renderTabela(chaves) {
  const tbody = document.getElementById('tabela-body');
  if (!chaves.length) { tbody.innerHTML = '<tr><td colspan="8" class="empty">Nenhuma chave encontrada.</td></tr>'; return; }
  const agora = new Date();
  tbody.innerHTML = '';
  chaves.forEach(c => {
    let statusClass, statusLabel;
    if (!c.ativa) { statusClass='badge-inativa'; statusLabel='Revogada'; }
    else if (c.expira_em && new Date(c.expira_em) < agora) { statusClass='badge-expirada'; statusLabel='Expirada'; }
    else { statusClass='badge-ativa'; statusLabel='Ativa'; }
    const tipoLabel = {mensal:'Mensal',mentoria:'Mentoria',vitalicio:'Vitalício'}[c.tipo] || c.tipo;
    const max = c.max_devices || 1;
    const usados = c.slots_usados || 0;
    let dotsHtml = '';
    for (let i=0;i<max;i++) {
      const cls = i < usados ? (usados >= max ? 'slot-dot cheio' : 'slot-dot usado') : 'slot-dot';
      dotsHtml += `<div class="${cls}"></div>`;
    }
    const expiraFmt = c.expira_em ? new Date(c.expira_em).toLocaleDateString('pt-BR') : '—';
    const ultimoAcesso = ultimoAcessoGeral(c.devices);
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><div class="chave-txt">${c.chave}</div><div style="font-size:10px;color:var(--muted);font-family:monospace">${c.id.slice(0,8)}…</div></td>
      <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${c.observacao?`<span>${esc(c.observacao)}</span>`:'<span style="color:var(--muted);font-style:italic">sem descrição</span>'}</td>
      <td><span class="badge badge-${c.tipo||'mensal'}">${tipoLabel}</span></td>
      <td><span class="badge ${statusClass}">${statusLabel}</span></td>
      <td>
        <div class="slots-bar"><div class="slots-dots">${dotsHtml}</div><div class="slots-txt">${usados}/${max}</div></div>
        <div style="font-size:10px;color:var(--muted);margin-top:3px">${c.devices.length} dispositivo${c.devices.length!==1?'s':''} <span style="cursor:pointer;color:var(--blue);margin-left:4px" onclick="toggleDevices('${c.id}')">${expandidoId===c.id?'▲ ocultar':'▼ ver'}</span></div>
      </td>
      <td style="color:${!c.expira_em?'var(--muted)':(new Date(c.expira_em)<agora?'var(--yellow)':'var(--text)'}}">${expiraFmt}</td>
      <td style="color:var(--muted);font-size:11px">${ultimoAcesso}</td>
      <td><div class="actions">
        <button class="btn btn-ghost btn-sm" onclick="abrirModalEditar('${c.id}')">✏️</button>
        ${c.ativa?`<button class="btn btn-danger btn-sm" onclick="revogar('${c.id}')">Revogar</button>`:`<button class="btn btn-success btn-sm" onclick="reativar('${c.id}')">Reativar</button>`}
        <button class="btn btn-warning btn-sm" onclick="resetarDevices('${c.id}','${esc(c.chave)}')">⟳ Reset</button>
        <button class="btn btn-ghost btn-sm" onclick="copiar('${c.chave}')">📋</button>
      </div></td>`;
    tbody.appendChild(tr);
    const trDev = document.createElement('tr');
    trDev.className = 'row-detail';
    trDev.style.display = expandidoId === c.id ? '' : 'none';
    trDev.innerHTML = `<td colspan="8">${renderDevices(c.devices, c.id)}</td>`;
    tbody.appendChild(trDev);
  });
}

function renderDevices(devices, chaveId) {
  if (!devices.length) return '<div style="padding:10px;color:var(--muted);font-size:12px">Nenhum dispositivo vinculado ainda.</div>';
  return '<div class="devices-wrap">' + devices.map(d => `
    <div class="device-item">
      <div class="device-icon">💻</div>
      <div class="device-info"><div class="device-nome">${esc(d.device_nome)}</div><div class="device-uuid">${d.device_uuid}</div></div>
      <div class="device-acesso"><div>Ativado: ${fmtData(d.ativado_em)}</div><div>Último acesso: ${fmtData(d.ultimo_acesso)}</div></div>
      <button class="btn btn-danger btn-sm" style="margin-left:10px" onclick="removerDevice('${d.id}','${chaveId}')">✕</button>
    </div>`).join('') + '</div>';
}

function toggleDevices(id) {
  expandidoId = expandidoId === id ? null : id;
  filtrar();
}

async function revogar(id) {
  if (!confirm('Revogar esta chave? O usuário será bloqueado.')) return;
  const res = await api(`/admin/revogar/${id}`, 'POST');
  toast(res.ok ? 'Chave revogada.' : res.msg, res.ok ? 'ok' : 'err');
  if (res.ok) carregar();
}

async function reativar(id) {
  const res = await api(`/admin/reativar/${id}`, 'POST');
  toast(res.ok ? 'Chave reativada.' : res.msg, res.ok ? 'ok' : 'err');
  if (res.ok) carregar();
}

async function resetarDevices(id, chave) {
  if (!confirm(`Resetar TODOS os devices da chave ${chave}?\nOs slots serão liberados.`)) return;
  const res = await api(`/admin/resetar_devices/${id}`, 'POST');
  toast(res.ok ? 'Devices resetados!' : res.msg, res.ok ? 'ok' : 'err');
  if (res.ok) { expandidoId = null; carregar(); }
}

async function removerDevice(deviceId, chaveId) {
  if (!confirm('Remover este dispositivo?')) return;
  const res = await api(`/admin/remover_device/${deviceId}`, 'DELETE');
  toast(res.ok ? 'Device removido.' : res.msg, res.ok ? 'ok' : 'err');
  if (res.ok) carregar();
}

function copiar(chave) { navigator.clipboard.writeText(chave).then(() => toast('Chave copiada!')); }

function abrirModalGerar() { document.getElementById('modal-gerar').classList.add('show'); }

async function gerarChave() {
  const res = await api('/admin/gerar', 'POST', {
    tipo: document.getElementById('g-tipo').value,
    max_devices: parseInt(document.getElementById('g-maxdev').value)||1,
    expira_em: document.getElementById('g-expira').value ? document.getElementById('g-expira').value+'T23:59:59Z' : null,
    quantidade: parseInt(document.getElementById('g-qtd').value)||1,
    observacao: document.getElementById('g-obs').value.trim()
  });
  if (res.ok) {
    fecharModal('modal-gerar');
    const txt = res.chaves.join('\n');
    navigator.clipboard.writeText(txt).catch(()=>{});
    toast(res.chaves.length===1 ? `Chave gerada: ${res.chaves[0]}` : `${res.chaves.length} chaves geradas!`);
    carregar();
  } else { toast(res.msg||'Erro ao gerar.','err'); }
}

function abrirModalEditar(id) {
  const c = todasChaves.find(x => x.id === id);
  if (!c) return;
  document.getElementById('e-id').value    = c.id;
  document.getElementById('e-obs').value   = c.observacao||'';
  document.getElementById('e-maxdev').value = c.max_devices||1;
  document.getElementById('e-expira').value = c.expira_em ? c.expira_em.slice(0,10) : '';
  document.getElementById('modal-editar').classList.add('show');
}

async function salvarEdicao() {
  const id = document.getElementById('e-id').value;
  const expira = document.getElementById('e-expira').value;
  const res = await api(`/admin/atualizar/${id}`, 'POST', {
    observacao: document.getElementById('e-obs').value.trim(),
    max_devices: parseInt(document.getElementById('e-maxdev').value)||1,
    expira_em: expira ? expira+'T23:59:59Z' : null
  });
  toast(res.ok ? 'Chave atualizada!' : res.msg, res.ok ? 'ok' : 'err');
  if (res.ok) { fecharModal('modal-editar'); carregar(); }
}

function fecharModal(id) { document.getElementById(id).classList.remove('show'); }
function esc(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function fmtData(iso) { if(!iso) return '—'; try { return new Date(iso).toLocaleString('pt-BR',{dateStyle:'short',timeStyle:'short'}); } catch(e){return iso;} }
function ultimoAcessoGeral(devices) {
  if(!devices||!devices.length) return '—';
  const datas = devices.map(d=>new Date(d.ultimo_acesso)).filter(d=>!isNaN(d));
  if(!datas.length) return '—';
  return fmtData(new Date(Math.max(...datas)).toISOString());
}

let toastTimer;
function toast(msg, tipo='ok') {
  const el = document.getElementById('toast');
  el.textContent = (tipo==='ok'?'✓ ':'✕ ')+msg;
  el.className = 'show '+tipo;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(()=>el.className='', 3500);
}

document.querySelectorAll('.modal-overlay').forEach(o => {
  o.addEventListener('click', e => { if(e.target===o) o.classList.remove('show'); });
});

document.getElementById('login-token').addEventListener('keydown', e => {
  if(e.key==='Enter') fazerLogin();
});

// Auto-login se tiver token salvo
window.addEventListener('load', () => {
  const saved = sessionStorage.getItem('il_token');
  if (saved) {
    document.getElementById('login-token').value = saved;
    fazerLogin();
  }
});
</script>
</body>
</html>"""

@app.route("/admin")
@app.route("/admin/")
def admin_painel():
    return ADMIN_HTML
