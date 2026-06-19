"""
InfinityLive - Backend de Licenças v1.0
Flask + Supabase
"""
import os, json, random, string
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, jsonify
from supabase import create_client, Client

app = Flask(__name__)

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL  = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY  = os.environ.get("SUPABASE_KEY", "")  # service_role key
ADMIN_TOKEN   = os.environ.get("ADMIN_TOKEN", "TROQUE_ESTE_TOKEN")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Helpers ───────────────────────────────────────────────────────────────────
def agora():
    return datetime.now(timezone.utc).isoformat()

def gerar_chave():
    """Gera chave no formato INFT-XXXX-XXXX-XXXX"""
    chars = string.ascii_uppercase + string.digits
    blocos = [''.join(random.choices(chars, k=4)) for _ in range(3)]
    return "INFT-" + "-".join(blocos)

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

# ── CORS preflight ─────────────────────────────────────────────────────────────
@app.after_request
def after(response):
    return cors(response)

@app.route("/", methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def options(path=""):
    return jsonify({"ok": True})

# ══════════════════════════════════════════════════════════════════════════════
#  ROTAS PÚBLICAS (extensão)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/ativar", methods=["POST"])
def ativar():
    """
    Ativa uma chave num device.
    Body: { chave, device_uuid, device_nome }
    """
    body = request.get_json(silent=True) or {}
    chave       = (body.get("chave") or "").strip().upper()
    device_uuid = (body.get("device_uuid") or "").strip()
    device_nome = (body.get("device_nome") or "Desconhecido").strip()[:60]

    if not chave or not device_uuid:
        return jsonify({"ok": False, "msg": "Dados incompletos."})

    # 1. Busca a licença
    res = supabase.table("licencas").select("*").eq("chave", chave).execute()
    if not res.data:
        return jsonify({"ok": False, "msg": "Chave não encontrada."})

    lic = res.data[0]

    if not lic["ativa"]:
        return jsonify({"ok": False, "msg": "Chave inativa ou revogada."})

    # 2. Verifica expiração
    if lic["expira_em"]:
        expira = datetime.fromisoformat(lic["expira_em"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expira:
            return jsonify({"ok": False, "msg": "Chave expirada."})

    # 3. Busca devices já vinculados a esta chave
    devs_res = supabase.table("licenca_devices") \
        .select("*").eq("licenca_id", lic["id"]).execute()
    devices = devs_res.data or []

    # 4. Verifica se este device já está registrado
    device_existente = next((d for d in devices if d["device_uuid"] == device_uuid), None)

    if device_existente:
        # Já registrado — só atualiza último acesso
        supabase.table("licenca_devices").update({"ultimo_acesso": agora()}) \
            .eq("id", device_existente["id"]).execute()
        return jsonify({"ok": True, "msg": "Dispositivo já autorizado."})

    # 5. Verifica se ainda há slots disponíveis
    max_dev = lic.get("max_devices", 1)
    if len(devices) >= max_dev:
        return jsonify({
            "ok": False,
            "msg": f"Limite de dispositivos atingido ({max_dev}/{max_dev}). "
                   "Contate a Mariana para liberar um slot."
        })

    # 6. Registra o novo device
    supabase.table("licenca_devices").insert({
        "licenca_id":   lic["id"],
        "device_uuid":  device_uuid,
        "device_nome":  device_nome,
        "ativado_em":   agora(),
        "ultimo_acesso": agora()
    }).execute()

    # 7. Marca licença como ativada (se for a primeira vez)
    if not lic.get("ativada_em"):
        supabase.table("licencas").update({"ativada_em": agora()}) \
            .eq("id", lic["id"]).execute()

    return jsonify({"ok": True, "msg": "Dispositivo autorizado com sucesso!"})


@app.route("/validar", methods=["POST"])
def validar():
    """
    Valida se chave+device ainda têm acesso.
    Body: { chave, device_uuid }
    Chamado a cada 30min pelo background.js
    """
    body = request.get_json(silent=True) or {}
    chave       = (body.get("chave") or "").strip().upper()
    device_uuid = (body.get("device_uuid") or "").strip()

    if not chave or not device_uuid:
        return jsonify({"ok": False, "msg": "Dados incompletos."})

    # Busca licença
    res = supabase.table("licencas").select("*").eq("chave", chave).execute()
    if not res.data:
        return jsonify({"ok": False, "msg": "Chave não encontrada."})

    lic = res.data[0]

    if not lic["ativa"]:
        return jsonify({"ok": False, "msg": "Chave revogada."})

    # Verifica expiração
    if lic["expira_em"]:
        expira = datetime.fromisoformat(lic["expira_em"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expira:
            return jsonify({"ok": False, "msg": "Chave expirada."})

    # Verifica se device está registrado
    devs_res = supabase.table("licenca_devices") \
        .select("*").eq("licenca_id", lic["id"]).eq("device_uuid", device_uuid).execute()

    if not devs_res.data:
        return jsonify({"ok": False, "msg": "Dispositivo não autorizado para esta chave."})

    # Atualiza último acesso
    supabase.table("licenca_devices").update({"ultimo_acesso": agora()}) \
        .eq("id", devs_res.data[0]["id"]).execute()

    return jsonify({"ok": True, "msg": "Acesso válido."})


# ══════════════════════════════════════════════════════════════════════════════
#  ROTAS ADMIN (painel)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/admin/chaves", methods=["GET"])
@admin_required
def admin_listar_chaves():
    """Lista todas as chaves com seus devices."""
    res = supabase.table("licencas").select("*").order("criada_em", desc=True).execute()
    chaves = res.data or []

    # Para cada chave, busca os devices
    for c in chaves:
        devs = supabase.table("licenca_devices") \
            .select("*").eq("licenca_id", c["id"]).order("ativado_em").execute()
        c["devices"] = devs.data or []
        c["slots_usados"] = len(c["devices"])

    return jsonify({"ok": True, "chaves": chaves})


@app.route("/admin/gerar", methods=["POST"])
@admin_required
def admin_gerar():
    """
    Gera uma ou mais chaves.
    Body: { tipo, max_devices, expira_em (opcional), quantidade, observacao }
    """
    body        = request.get_json(silent=True) or {}
    tipo        = body.get("tipo", "mensal")
    max_devices = int(body.get("max_devices", 1))
    expira_em   = body.get("expira_em", None)   # ISO string ou null
    quantidade  = min(int(body.get("quantidade", 1)), 50)  # máx 50 por vez
    observacao  = (body.get("observacao") or "")[:200]

    geradas = []
    for _ in range(quantidade):
        chave = gerar_chave()
        row = {
            "chave":       chave,
            "tipo":        tipo,
            "max_devices": max_devices,
            "ativa":       True,
            "expira_em":   expira_em,
            "criada_em":   agora(),
            "observacao":  observacao,
        }
        supabase.table("licencas").insert(row).execute()
        geradas.append(chave)

    return jsonify({"ok": True, "chaves": geradas})


@app.route("/admin/revogar/<chave_id>", methods=["POST"])
@admin_required
def admin_revogar(chave_id):
    """Revoga uma chave (ativa = false)."""
    supabase.table("licencas").update({"ativa": False}).eq("id", chave_id).execute()
    return jsonify({"ok": True, "msg": "Chave revogada."})


@app.route("/admin/reativar/<chave_id>", methods=["POST"])
@admin_required
def admin_reativar(chave_id):
    """Reativa uma chave revogada."""
    supabase.table("licencas").update({"ativa": True}).eq("id", chave_id).execute()
    return jsonify({"ok": True, "msg": "Chave reativada."})


@app.route("/admin/resetar_devices/<chave_id>", methods=["POST"])
@admin_required
def admin_resetar_devices(chave_id):
    """Remove todos os devices vinculados — libera todos os slots."""
    supabase.table("licenca_devices").delete().eq("licenca_id", chave_id).execute()
    return jsonify({"ok": True, "msg": "Devices resetados. Slots liberados."})


@app.route("/admin/remover_device/<device_id>", methods=["DELETE"])
@admin_required
def admin_remover_device(device_id):
    """Remove um device específico (libera 1 slot)."""
    supabase.table("licenca_devices").delete().eq("id", device_id).execute()
    return jsonify({"ok": True, "msg": "Device removido."})


@app.route("/admin/atualizar/<chave_id>", methods=["POST"])
@admin_required
def admin_atualizar(chave_id):
    """
    Atualiza dados de uma chave.
    Body: { max_devices, expira_em, observacao }
    """
    body = request.get_json(silent=True) or {}
    update = {}
    if "max_devices"  in body: update["max_devices"]  = int(body["max_devices"])
    if "expira_em"    in body: update["expira_em"]    = body["expira_em"]
    if "observacao"   in body: update["observacao"]   = body["observacao"][:200]
    if update:
        supabase.table("licencas").update(update).eq("id", chave_id).execute()
    return jsonify({"ok": True, "msg": "Chave atualizada."})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
