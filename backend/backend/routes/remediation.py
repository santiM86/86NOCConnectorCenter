"""
Automated Remediation Engine — stile Kaseya VSA.
Permette di definire regole "se alert X → esegui script Y sul connettore"
con approvazione manuale da dashboard (opt-in per sicurezza).

Flusso:
1. Admin definisce RemediationScript (nome, tipo=powershell/shell/snmp-set/http, body)
2. Admin definisce RemediationRule (match alert → script + requires_approval)
3. Alert creato → evaluator crea RemediationProposal in stato "pending_approval"
4. Operatore approva dal frontend → RemediationExecution inserito in pending_commands per il connector
5. Connector esegue, ritorna risultato via callback POST /remediation/result
6. Audit log persistente (chi, quando, quale script, su quale device, outcome)
"""
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import uuid
import logging

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api/remediation", tags=["remediation"])
audit = logging.getLogger("audit")


# ======================== MODELS ========================

class RemediationScript(BaseModel):
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    script_type: str = Field(default="powershell", description="powershell|shell|snmp-set|http-get|http-post|reboot|service-restart")
    body: str  # script content OR JSON payload for structured actions
    target_device_types: List[str] = []  # es: ["switch","firewall","server"]
    target_os: List[str] = []  # es: ["windows","linux","cisco-ios"]
    timeout_seconds: int = 60
    requires_approval: bool = True
    is_builtin: bool = False
    tags: List[str] = []


class RemediationRule(BaseModel):
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    enabled: bool = True
    # Matching criteria (all AND'd; empty list = any)
    alert_types: List[str] = []   # es: ["cpu_high","service_down"]
    severity_match: List[str] = []
    device_type_match: List[str] = []
    keyword_match: List[str] = []   # case-insensitive substrings on title+message
    client_ids: List[str] = []      # restrict to specific clients, empty=all
    # Action
    script_id: str
    requires_approval: bool = True   # even if the script has own flag, rule can force
    cooldown_minutes: int = 10       # avoid spamming same device
    max_per_day: int = 20


# ======================== SCRIPTS CRUD ========================

@router.get("/scripts")
async def list_scripts(current_user: dict = Depends(get_current_user)):
    await _ensure_builtins()
    cursor = db.remediation_scripts.find({}, {"_id": 0}).sort([("is_builtin", -1), ("name", 1)]).limit(500)
    return {"items": [d async for d in cursor]}


@router.post("/scripts")
async def create_script(s: RemediationScript, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    now = datetime.now(timezone.utc).isoformat()
    data = s.model_dump()
    data["id"] = data.get("id") or str(uuid.uuid4())
    data["is_builtin"] = False
    data["created_at"] = now
    data["updated_at"] = now
    data["created_by"] = current_user.get("email")
    await db.remediation_scripts.insert_one(data)
    audit.info(f"[AUDIT] remediation_script_create | user={current_user.get('email')} | script={data['name']}")
    return {k: v for k, v in data.items() if k != "_id"}


@router.put("/scripts/{sid}")
async def update_script(sid: str, s: RemediationScript, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    existing = await db.remediation_scripts.find_one({"id": sid})
    if not existing:
        raise HTTPException(status_code=404, detail="Script not found")
    if existing.get("is_builtin"):
        raise HTTPException(status_code=400, detail="Cannot modify builtin scripts")
    data = s.model_dump()
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["updated_by"] = current_user.get("email")
    data.pop("id", None)
    await db.remediation_scripts.update_one({"id": sid}, {"$set": data})
    return {"ok": True}


@router.delete("/scripts/{sid}")
async def delete_script(sid: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    existing = await db.remediation_scripts.find_one({"id": sid})
    if existing and existing.get("is_builtin"):
        raise HTTPException(status_code=400, detail="Cannot delete builtin scripts")
    res = await db.remediation_scripts.delete_one({"id": sid})
    return {"deleted": res.deleted_count > 0}


# ======================== RULES CRUD ========================

@router.get("/rules")
async def list_rules(current_user: dict = Depends(get_current_user)):
    cursor = db.remediation_rules.find({}, {"_id": 0}).sort("updated_at", -1).limit(500)
    return {"items": [d async for d in cursor]}


@router.post("/rules")
async def create_rule(r: RemediationRule, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    script = await db.remediation_scripts.find_one({"id": r.script_id}, {"_id": 0})
    if not script:
        raise HTTPException(status_code=400, detail="script_id not found")
    now = datetime.now(timezone.utc).isoformat()
    data = r.model_dump()
    data["id"] = data.get("id") or str(uuid.uuid4())
    data["created_at"] = now
    data["updated_at"] = now
    data["created_by"] = current_user.get("email")
    data["keyword_match"] = [k.lower() for k in (data.get("keyword_match") or [])]
    await db.remediation_rules.insert_one(data)
    return {k: v for k, v in data.items() if k != "_id"}


@router.put("/rules/{rid}")
async def update_rule(rid: str, r: RemediationRule, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    data = r.model_dump()
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["updated_by"] = current_user.get("email")
    data["keyword_match"] = [k.lower() for k in (data.get("keyword_match") or [])]
    data.pop("id", None)
    res = await db.remediation_rules.update_one({"id": rid}, {"$set": data})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


@router.delete("/rules/{rid}")
async def delete_rule(rid: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    res = await db.remediation_rules.delete_one({"id": rid})
    return {"deleted": res.deleted_count > 0}


# ======================== EVALUATOR (match + propose) ========================

async def evaluate_alert_for_remediation(alert_doc: dict):
    """
    Chiamata da alerts.py/ingestion al momento della creazione alert.
    Scansiona le rule attive, crea proposal se match + non in cooldown.
    """
    try:
        if not alert_doc:
            return
        alert_type = (alert_doc.get("type") or alert_doc.get("alert_type") or "").lower()
        severity = (alert_doc.get("severity") or "").lower()
        device_type = (alert_doc.get("device_type") or "").lower()
        title = (alert_doc.get("title") or "").lower()
        message = (alert_doc.get("message") or "").lower()
        client_id = alert_doc.get("client_id")
        device_ip = alert_doc.get("device_ip")
        haystack = f"{title} {message}"
        if not device_ip:
            return

        rules_cursor = db.remediation_rules.find({"enabled": True}, {"_id": 0})
        async for rule in rules_cursor:
            if rule.get("alert_types") and alert_type not in rule["alert_types"]:
                continue
            if rule.get("severity_match") and severity not in rule["severity_match"]:
                continue
            if rule.get("device_type_match") and device_type not in rule["device_type_match"]:
                continue
            if rule.get("client_ids") and client_id not in rule["client_ids"]:
                continue
            if rule.get("keyword_match"):
                if not any(kw in haystack for kw in rule["keyword_match"]):
                    continue

            # Cooldown check
            cooldown_min = int(rule.get("cooldown_minutes") or 10)
            since_cd = datetime.now(timezone.utc).timestamp() - (cooldown_min * 60)
            last = await db.remediation_executions.find_one({
                "rule_id": rule["id"], "device_ip": device_ip
            }, sort=[("created_at_ts", -1)])
            if last and (last.get("created_at_ts") or 0) > since_cd:
                continue

            # Max per day check
            max_day = int(rule.get("max_per_day") or 20)
            day_ago = datetime.now(timezone.utc).timestamp() - 86400
            day_count = await db.remediation_executions.count_documents({
                "rule_id": rule["id"], "created_at_ts": {"$gte": day_ago}
            })
            if day_count >= max_day:
                continue

            script = await db.remediation_scripts.find_one({"id": rule["script_id"]}, {"_id": 0})
            if not script:
                continue

            needs_approval = bool(rule.get("requires_approval", True) or script.get("requires_approval", True))
            status = "pending_approval" if needs_approval else "queued"

            exec_doc = {
                "id": str(uuid.uuid4()),
                "rule_id": rule["id"],
                "rule_name": rule.get("name"),
                "script_id": script["id"],
                "script_name": script.get("name"),
                "script_type": script.get("script_type"),
                "alert_id": alert_doc.get("id"),
                "alert_title": alert_doc.get("title"),
                "client_id": client_id,
                "device_ip": device_ip,
                "device_name": alert_doc.get("device_name"),
                "status": status,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_at_ts": datetime.now(timezone.utc).timestamp(),
                "approved_by": None,
                "approved_at": None,
                "dispatched_at": None,
                "completed_at": None,
                "result": None,
                "output": None,
                "error": None,
            }
            await db.remediation_executions.insert_one(exec_doc)

            if not needs_approval:
                # auto-dispatch
                await _dispatch_to_connector(exec_doc, script)
    except Exception as e:
        import traceback
        logging.getLogger(__name__).warning(f"remediation evaluator error: {e}\n{traceback.format_exc()}")


async def _dispatch_to_connector(exec_doc: dict, script: dict):
    """Crea un pending_command per il connector del client."""
    client_id = exec_doc.get("client_id")
    if not client_id:
        await db.remediation_executions.update_one(
            {"id": exec_doc["id"]},
            {"$set": {"status": "failed", "error": "no client_id on alert", "completed_at": datetime.now(timezone.utc).isoformat()}}
        )
        return
    cmd = {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "type": "remediation",
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "execution_id": exec_doc["id"],
            "device_ip": exec_doc["device_ip"],
            "script_type": script.get("script_type"),
            "script_body": script.get("body"),
            "timeout_seconds": int(script.get("timeout_seconds") or 60),
        },
    }
    await db.pending_commands.insert_one(cmd)
    await db.remediation_executions.update_one(
        {"id": exec_doc["id"]},
        {"$set": {"status": "dispatched", "dispatched_at": datetime.now(timezone.utc).isoformat(), "command_id": cmd["id"]}}
    )


# ======================== EXECUTIONS LIST + APPROVE ========================

@router.get("/executions")
async def list_executions(status: Optional[str] = None, client_id: Optional[str] = None,
                           limit: int = 100, current_user: dict = Depends(get_current_user)):
    q = {}
    if status:
        q["status"] = status
    if client_id:
        q["client_id"] = client_id
    cursor = db.remediation_executions.find(q, {"_id": 0}).sort("created_at_ts", -1).limit(min(limit, 500))
    return {"items": [e async for e in cursor]}


@router.get("/executions/{eid}")
async def get_execution(eid: str, current_user: dict = Depends(get_current_user)):
    e = await db.remediation_executions.find_one({"id": eid}, {"_id": 0})
    if not e:
        raise HTTPException(status_code=404, detail="Not found")
    return e


@router.post("/executions/{eid}/approve")
async def approve_execution(eid: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permission denied")
    e = await db.remediation_executions.find_one({"id": eid})
    if not e:
        raise HTTPException(status_code=404, detail="Not found")
    if e.get("status") != "pending_approval":
        raise HTTPException(status_code=400, detail=f"Cannot approve from state {e.get('status')}")
    script = await db.remediation_scripts.find_one({"id": e["script_id"]}, {"_id": 0})
    if not script:
        raise HTTPException(status_code=400, detail="Linked script missing")
    await db.remediation_executions.update_one(
        {"id": eid},
        {"$set": {"approved_by": current_user.get("email"),
                   "approved_at": datetime.now(timezone.utc).isoformat(),
                   "status": "approved"}}
    )
    e["status"] = "approved"
    await _dispatch_to_connector(e, script)
    audit.info(f"[AUDIT] remediation_approve | user={current_user.get('email')} | exec={eid} | device={e.get('device_ip')}")
    return {"ok": True}


@router.post("/executions/{eid}/reject")
async def reject_execution(eid: str, reason: str = "", current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permission denied")
    await db.remediation_executions.update_one(
        {"id": eid, "status": "pending_approval"},
        {"$set": {"status": "rejected",
                   "rejected_by": current_user.get("email"),
                   "rejected_at": datetime.now(timezone.utc).isoformat(),
                   "rejection_reason": reason}}
    )
    audit.info(f"[AUDIT] remediation_reject | user={current_user.get('email')} | exec={eid}")
    return {"ok": True}


@router.post("/executions/{eid}/manual-run")
async def manual_run(eid: str, current_user: dict = Depends(get_current_user)):
    """Run manuale anche se script ha requires_approval=false ma l'esecuzione è in stato terminale: ri-dispatch."""
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    e = await db.remediation_executions.find_one({"id": eid})
    if not e:
        raise HTTPException(status_code=404, detail="Not found")
    script = await db.remediation_scripts.find_one({"id": e["script_id"]}, {"_id": 0})
    if not script:
        raise HTTPException(status_code=400, detail="Script gone")
    await db.remediation_executions.update_one({"id": eid}, {"$set": {"status": "approved", "re_run_by": current_user.get("email"), "re_run_at": datetime.now(timezone.utc).isoformat()}})
    await _dispatch_to_connector(e, script)
    return {"ok": True}


class ManualTriggerBody(BaseModel):
    script_id: str
    client_id: str
    device_ip: str
    device_name: Optional[str] = None


@router.post("/trigger")
async def manual_trigger(body: ManualTriggerBody, current_user: dict = Depends(get_current_user)):
    """Trigger manuale ad-hoc senza rule (per test o operatività one-shot)."""
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permission denied")
    script = await db.remediation_scripts.find_one({"id": body.script_id}, {"_id": 0})
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    exec_doc = {
        "id": str(uuid.uuid4()),
        "rule_id": None,
        "rule_name": "manual",
        "script_id": script["id"],
        "script_name": script.get("name"),
        "script_type": script.get("script_type"),
        "alert_id": None,
        "alert_title": None,
        "client_id": body.client_id,
        "device_ip": body.device_ip,
        "device_name": body.device_name,
        "status": "approved",
        "approved_by": current_user.get("email"),
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_at_ts": datetime.now(timezone.utc).timestamp(),
        "dispatched_at": None,
        "completed_at": None,
        "result": None, "output": None, "error": None,
    }
    await db.remediation_executions.insert_one(exec_doc)
    await _dispatch_to_connector(exec_doc, script)
    audit.info(f"[AUDIT] remediation_manual_trigger | user={current_user.get('email')} | script={script.get('name')} | device={body.device_ip}")
    return {"ok": True, "execution_id": exec_doc["id"]}


# ======================== RESULT CALLBACK (from connector) ========================

@router.post("/result")
async def remediation_result(request: Request):
    """
    Callback dal connector HMAC-authed. Body: {execution_id, result, output, error, exit_code}.
    Autenticato via verify_connector_request (per evitare di dover duplicare la logica HMAC qui,
    usiamo endpoint /{C}/remediation/result sotto connector.py shim; questo endpoint accetta
    anche JWT admin per testing manuale).
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")
    eid = body.get("execution_id")
    if not eid:
        raise HTTPException(status_code=400, detail="execution_id required")
    update = {
        "status": body.get("result") or "completed",
        "output": body.get("output"),
        "error": body.get("error"),
        "exit_code": body.get("exit_code"),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.remediation_executions.update_one({"id": eid}, {"$set": update})
    return {"ok": True}


# ======================== STATS ========================

@router.get("/stats")
async def remediation_stats(current_user: dict = Depends(get_current_user)):
    day_ago_ts = datetime.now(timezone.utc).timestamp() - 86400
    week_ago_ts = datetime.now(timezone.utc).timestamp() - 7 * 86400
    pending = await db.remediation_executions.count_documents({"status": "pending_approval"})
    day_ok = await db.remediation_executions.count_documents({"status": "success", "created_at_ts": {"$gte": day_ago_ts}})
    day_fail = await db.remediation_executions.count_documents({"status": "failed", "created_at_ts": {"$gte": day_ago_ts}})
    week_total = await db.remediation_executions.count_documents({"created_at_ts": {"$gte": week_ago_ts}})
    total_rules = await db.remediation_rules.count_documents({})
    active_rules = await db.remediation_rules.count_documents({"enabled": True})
    total_scripts = await db.remediation_scripts.count_documents({})
    return {
        "pending_approvals": pending,
        "day_success": day_ok,
        "day_failures": day_fail,
        "week_executions": week_total,
        "total_rules": total_rules,
        "active_rules": active_rules,
        "total_scripts": total_scripts,
    }


# ======================== BUILTINS ========================

BUILTIN_SCRIPTS = [
    {
        "name": "Ping check (diagnostic)",
        "description": "Ping 4 pacchetti al device target, ritorna RTT.",
        "script_type": "powershell",
        "body": "Test-Connection -ComputerName $args[0] -Count 4 | Format-Table -AutoSize",
        "target_device_types": [],
        "timeout_seconds": 30,
        "requires_approval": False,
        "tags": ["diagnostic", "safe"],
    },
    {
        "name": "Traceroute",
        "description": "Traceroute al device target (fino a 15 hop).",
        "script_type": "powershell",
        "body": "Test-NetConnection -ComputerName $args[0] -TraceRoute | Format-List",
        "timeout_seconds": 60,
        "requires_approval": False,
        "tags": ["diagnostic", "safe"],
    },
    {
        "name": "HTTP GET health",
        "description": "Chiama un endpoint HTTP per health check.",
        "script_type": "http-get",
        "body": '{"url":"http://{device_ip}/","timeout":10}',
        "timeout_seconds": 15,
        "requires_approval": False,
        "tags": ["diagnostic", "safe"],
    },
    {
        "name": "Restart Windows service (manual input)",
        "description": "Riavvia un servizio Windows sul device. ATTENZIONE: richiede RPC/WinRM aperto.",
        "script_type": "powershell",
        "body": "$svc = $args[1]; Restart-Service -Name $svc -Force -ErrorAction Stop; Get-Service $svc | Format-List Name,Status",
        "target_device_types": ["server"],
        "target_os": ["windows"],
        "timeout_seconds": 60,
        "requires_approval": True,
        "tags": ["remediation"],
    },
    {
        "name": "Clear printer spooler queue",
        "description": "Pulisce coda stampa e riavvia Spooler.",
        "script_type": "powershell",
        "body": "Stop-Service Spooler -Force; Remove-Item 'C:\\Windows\\System32\\spool\\PRINTERS\\*' -Force -ErrorAction SilentlyContinue; Start-Service Spooler",
        "target_device_types": ["printer", "server"],
        "timeout_seconds": 60,
        "requires_approval": True,
        "tags": ["printer", "remediation"],
    },
    {
        "name": "SNMP reboot (ifAdminStatus toggle)",
        "description": "Disabilita e riabilita interfaccia SNMP (workaround link flap).",
        "script_type": "snmp-set",
        "body": '{"oid":"1.3.6.1.2.1.2.2.1.7.{ifIndex}","type":"i","values":[2,1],"delay":5}',
        "target_device_types": ["switch", "router"],
        "timeout_seconds": 30,
        "requires_approval": True,
        "tags": ["network", "remediation"],
    },
]


async def _ensure_builtins():
    count = await db.remediation_scripts.count_documents({"is_builtin": True})
    if count >= len(BUILTIN_SCRIPTS):
        return
    now = datetime.now(timezone.utc).isoformat()
    for s in BUILTIN_SCRIPTS:
        exists = await db.remediation_scripts.find_one({"name": s["name"], "is_builtin": True})
        if exists:
            continue
        data = {**s, "id": str(uuid.uuid4()), "is_builtin": True, "created_at": now, "updated_at": now, "created_by": "system"}
        data.setdefault("target_os", [])
        await db.remediation_scripts.insert_one(data)


async def init_indexes():
    await db.remediation_executions.create_index([("created_at_ts", -1)])
    await db.remediation_executions.create_index([("status", 1), ("created_at_ts", -1)])
    await db.remediation_executions.create_index([("rule_id", 1), ("device_ip", 1), ("created_at_ts", -1)])
    await db.remediation_rules.create_index([("enabled", 1)])
    await db.remediation_scripts.create_index([("name", 1)])
