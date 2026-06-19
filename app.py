"""
InfinityLive - Backend de Licencas v1.2
Flask + Supabase REST API (sem biblioteca supabase)
"""
import os, json, random, string, requests
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, jsonify

app = Flask(__name__)

SUPABASE_URL  = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY  = os.environ.get("SUPABASE_KEY", "")
ADMIN_TOKEN   = os.environ.get("ADMIN_TOKEN", "cal61490")

def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": "Bearer " + SUPABASE_KEY,
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

def sb_get(tabela, filtros=None):
    url = SUPABASE_URL + "/rest/v1/" + tabela
    params = filtros or {}
    params["select"] = "*"
    r = requests.get(url, headers=sb_headers(), params=params, timeout=10)
    r.raise_for_status()
    return r.json()

def sb_post(tabela, dados):
    url = SUPABASE_URL + "/rest/v1/" + tabela
    r = requests.post(url, headers=sb_headers(), json=dados, timeout=10)
    r.raise_for_status()
    return r.json()

def sb_patch(tabela, filtros, dados):
    url = SUPABASE_URL + "/rest/v1/" + tabela
    r = requests.patch(url, headers=sb_headers(), params=filtros, json=dados, timeout=10)
    r.raise_for_status()
    return r.json()

def sb_delete(tabela, filtros):
    url = SUPABASE_URL + "/rest/v1/" + tabela
    r = requests.delete(url, headers=sb_headers(), params=filtros, timeout=10)
    r.raise_for_status()
    return r.json()

def agora():
    return datetime.now(timezone.utc).isoformat()

def gerar_chave():
    chars = string.ascii_uppercase + string.digits
    bloco = ''.join(random.choices(chars, k=4))
    return "IL-" + bloco

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("X-Admin-Token", "")
        if token != ADMIN_TOKEN:
            return jsonify({"ok": False, "msg": "Nao autorizado."}), 401
        return f(*args, **kwargs)
    return decorated

@app.after_request
def after(response):
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Admin-Token"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, DELETE"
    return response

@app.route("/", methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def options(path=""):
    return jsonify({"ok": True})

@app.route("/")
def index():
    return jsonify({"ok": True, "msg": "InfinityLive Licencas v1.2"})


# ══════════════════════════════════════════════════════════════════════════════
#  ROTAS PUBLICAS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/ativar", methods=["POST"])
def ativar():
    body        = request.get_json(silent=True) or {}
    chave       = (body.get("chave") or "").strip().upper()
    device_uuid = (body.get("device_uuid") or "").strip()
    device_nome = (body.get("device_nome") or "Desconhecido").strip()[:60]

    if not chave or not device_uuid:
        return jsonify({"ok": False, "msg": "Dados incompletos."})

    try:
        lics = sb_get("licencas", {"chave": "eq." + chave})
    except Exception as e:
        return jsonify({"ok": False, "msg": "Erro ao consultar banco: " + str(e)})

    if not lics:
        return jsonify({"ok": False, "msg": "Chave nao encontrada."})

    lic = lics[0]

    if not lic["ativa"]:
        return jsonify({"ok": False, "msg": "Chave inativa ou revogada."})

    if lic["expira_em"]:
        expira = datetime.fromisoformat(lic["expira_em"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expira:
            return jsonify({"ok": False, "msg": "Chave expirada."})

    try:
        devices = sb_get("licenca_devices", {"licenca_id": "eq." + lic["id"]})
    except Exception as e:
        return jsonify({"ok": False, "msg": "Erro ao consultar devices: " + str(e)})

    device_existente = next((d for d in devices if d["device_uuid"] == device_uuid), None)
    if device_existente:
        try:
            sb_patch("licenca_devices", {"id": "eq." + device_existente["id"]}, {"ultimo_acesso": agora()})
        except:
            pass
        return jsonify({"ok": True, "msg": "Dispositivo ja autorizado."})

    max_dev = lic.get("max_devices", 1)
    if len(devices) >= max_dev:
        return jsonify({"ok": False, "msg": "Limite de dispositivos atingido (" + str(max_dev) + "/" + str(max_dev) + "). Contate a Mariana."})

    try:
        sb_post("licenca_devices", {
            "licenca_id":    lic["id"],
            "device_uuid":   device_uuid,
            "device_nome":   device_nome,
            "ativado_em":    agora(),
            "ultimo_acesso": agora()
        })
    except Exception as e:
        return jsonify({"ok": False, "msg": "Erro ao registrar device: " + str(e)})

    if not lic.get("ativada_em"):
        try:
            sb_patch("licencas", {"id": "eq." + lic["id"]}, {"ativada_em": agora()})
        except:
            pass

    return jsonify({"ok": True, "msg": "Dispositivo autorizado com sucesso!"})


@app.route("/validar", methods=["POST"])
def validar():
    body        = request.get_json(silent=True) or {}
    chave       = (body.get("chave") or "").strip().upper()
    device_uuid = (body.get("device_uuid") or "").strip()

    if not chave or not device_uuid:
        return jsonify({"ok": False, "msg": "Dados incompletos."})

    try:
        lics = sb_get("licencas", {"chave": "eq." + chave})
    except Exception as e:
        return jsonify({"ok": True, "msg": "Offline - acesso mantido."})

    if not lics:
        return jsonify({"ok": False, "msg": "Chave nao encontrada."})

    lic = lics[0]

    if not lic["ativa"]:
        return jsonify({"ok": False, "msg": "Chave revogada."})

    if lic["expira_em"]:
        expira = datetime.fromisoformat(lic["expira_em"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expira:
            return jsonify({"ok": False, "msg": "Chave expirada."})

    try:
        devs = sb_get("licenca_devices", {"licenca_id": "eq." + lic["id"], "device_uuid": "eq." + device_uuid})
    except:
        return jsonify({"ok": True, "msg": "Offline - acesso mantido."})

    if not devs:
        return jsonify({"ok": False, "msg": "Dispositivo nao autorizado."})

    try:
        sb_patch("licenca_devices", {"id": "eq." + devs[0]["id"]}, {"ultimo_acesso": agora()})
    except:
        pass

    return jsonify({"ok": True, "msg": "Acesso valido."})


# ══════════════════════════════════════════════════════════════════════════════
#  ROTAS ADMIN
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/admin/chaves", methods=["GET"])
@admin_required
def admin_listar_chaves():
    try:
        chaves = sb_get("licencas", {"order": "criada_em.desc"})
        for c in chaves:
            devs = sb_get("licenca_devices", {"licenca_id": "eq." + c["id"], "order": "ativado_em.asc"})
            c["devices"]      = devs
            c["slots_usados"] = len(devs)
        return jsonify({"ok": True, "chaves": chaves})
    except Exception as e:
        return jsonify({"ok": False, "msg": "Erro: " + str(e)})


@app.route("/admin/gerar", methods=["POST"])
@admin_required
def admin_gerar():
    body        = request.get_json(silent=True) or {}
    tipo        = body.get("tipo", "mensal")
    max_devices = int(body.get("max_devices", 1))
    expira_em   = body.get("expira_em", None)
    quantidade  = min(int(body.get("quantidade", 1)), 50)
    observacao  = (body.get("observacao") or "")[:200]

    geradas = []
    for _ in range(quantidade):
        chave = gerar_chave()
        try:
            sb_post("licencas", {
                "chave":       chave,
                "tipo":        tipo,
                "max_devices": max_devices,
                "ativa":       True,
                "expira_em":   expira_em,
                "criada_em":   agora(),
                "observacao":  observacao,
            })
            geradas.append(chave)
        except Exception as e:
            return jsonify({"ok": False, "msg": "Erro ao gerar: " + str(e)})

    return jsonify({"ok": True, "chaves": geradas})


@app.route("/admin/revogar/<chave_id>", methods=["POST"])
@admin_required
def admin_revogar(chave_id):
    try:
        sb_patch("licencas", {"id": "eq." + chave_id}, {"ativa": False})
        return jsonify({"ok": True, "msg": "Chave revogada."})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


@app.route("/admin/reativar/<chave_id>", methods=["POST"])
@admin_required
def admin_reativar(chave_id):
    try:
        sb_patch("licencas", {"id": "eq." + chave_id}, {"ativa": True})
        return jsonify({"ok": True, "msg": "Chave reativada."})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


@app.route("/admin/resetar_devices/<chave_id>", methods=["POST"])
@admin_required
def admin_resetar_devices(chave_id):
    try:
        sb_delete("licenca_devices", {"licenca_id": "eq." + chave_id})
        return jsonify({"ok": True, "msg": "Devices resetados."})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


@app.route("/admin/remover_device/<device_id>", methods=["DELETE"])
@admin_required
def admin_remover_device(device_id):
    try:
        sb_delete("licenca_devices", {"id": "eq." + device_id})
        return jsonify({"ok": True, "msg": "Device removido."})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


@app.route("/admin/atualizar/<chave_id>", methods=["POST"])
@admin_required
def admin_atualizar(chave_id):
    body   = request.get_json(silent=True) or {}
    update = {}
    if "max_devices" in body: update["max_devices"] = int(body["max_devices"])
    if "expira_em"   in body: update["expira_em"]   = body["expira_em"]
    if "observacao"  in body: update["observacao"]  = body["observacao"][:200]
    if update:
        try:
            sb_patch("licencas", {"id": "eq." + chave_id}, update)
        except Exception as e:
            return jsonify({"ok": False, "msg": str(e)})
    return jsonify({"ok": True, "msg": "Chave atualizada."})


# ── PAINEL ADMIN ──────────────────────────────────────────────────────────────
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
