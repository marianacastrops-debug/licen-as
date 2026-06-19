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

import pathlib

@app.route("/admin")
@app.route("/admin/")
def admin_painel():
    html_path = pathlib.Path(__file__).parent / "admin.html"
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
