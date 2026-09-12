"""Mock controller Omada Open API per test locale (porta 8099).
Uso: python tests/mock_omada_server.py &  poi salva base_url=http://127.0.0.1:8099 nelle impostazioni Omada.
"""
from fastapi import FastAPI, Request, Header
import uvicorn

app = FastAPI()
TOKEN = "AT-mock-123"


@app.post("/openapi/authorize/token")
async def token(req: Request):
    body = await req.json()
    if body.get("client_id") != "cid-test" or body.get("client_secret") != "sec-test" or body.get("omadacId") != "omadac-test":
        return {"errorCode": -44106, "msg": "Invalid client"}
    return {"errorCode": 0, "msg": "Success.", "result": {"accessToken": TOKEN, "tokenType": "bearer", "expiresIn": 7200}}


def _auth(h):
    return h == f"AccessToken={TOKEN}"


@app.get("/openapi/v1/omadac-test/sites")
async def sites(authorization: str = Header(None)):
    if not _auth(authorization):
        return {"errorCode": -44112, "msg": "token expired"}
    return {"errorCode": 0, "result": {"totalRows": 2, "currentPage": 1, "currentSize": 2, "data": [
        {"siteId": "site-a", "name": "Bar Centrale", "region": "Italy", "timeZone": "Europe/Rome", "scenario": "Restaurant"},
        {"siteId": "site-b", "name": "Studio Rossi", "region": "Italy", "timeZone": "Europe/Rome", "scenario": "Office"}]}}


@app.get("/openapi/v1/omadac-test/sites/{sid}/devices")
async def devices(sid: str, authorization: str = Header(None)):
    if not _auth(authorization):
        return {"errorCode": -44112, "msg": "token expired"}
    data = {"site-a": [
        {"mac": "AA-11-22-33-44-01", "name": "ER605", "model": "ER605 v2.0", "type": "gateway", "ip": "192.168.0.1", "publicIp": "93.44.10.20", "status": 14, "firmwareVersion": "2.2.4", "clientNum": 12, "cpuUtil": 5, "memUtil": 40},
        {"mac": "AA-11-22-33-44-02", "name": "SG2008P", "model": "TL-SG2008P v3.0", "type": "switch", "ip": "192.168.0.2", "status": 14, "firmwareVersion": "3.0.5", "clientNum": 6},
        {"mac": "AA-11-22-33-44-03", "name": "EAP225-Sala", "model": "EAP225 v3.0", "type": "ap", "ip": "192.168.0.10", "status": 0, "firmwareVersion": "5.1.0", "clientNum": 0}],
        "site-b": [{"mac": "AA-11-22-33-44-11", "name": "ER7206", "model": "ER7206 v1.0", "type": "gateway", "ip": "10.0.0.1", "publicIp": "192.168.178.7", "status": 14, "clientNum": 3}]}.get(sid, [])
    return {"errorCode": 0, "result": {"totalRows": len(data), "currentPage": 1, "currentSize": len(data), "data": data}}


@app.get("/openapi/v1/omadac-test/sites/{sid}/switches/{mac}/ports")
async def ports(sid: str, mac: str, authorization: str = Header(None)):
    if not _auth(authorization):
        return {"errorCode": -44112, "msg": "token expired"}
    return {"errorCode": 0, "result": [
        {"port": 1, "name": "Uplink", "disable": False, "portStatus": {"linkStatus": 1, "linkSpeed": 3, "poe": False}},
        {"port": 2, "name": "Cassa", "disable": False, "portStatus": {"linkStatus": 1, "linkSpeed": 2, "poe": False}},
        {"port": 3, "name": "AP Sala", "disable": False, "portStatus": {"linkStatus": 0, "linkSpeed": 0, "poe": True, "poePower": 0.0}},
        {"port": 4, "name": "Telefono", "disable": False, "portStatus": {"linkStatus": 1, "linkSpeed": 2, "poe": True, "poePower": 4.3}},
        {"port": 8, "name": "", "disable": True, "portStatus": {"linkStatus": 0, "linkSpeed": 0}}]}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8099, log_level="warning")
