"""Client CRUD routes."""
from fastapi import APIRouter, Depends, HTTPException
from typing import List
import uuid
from datetime import datetime, timezone

from database import db
from models import ClientCreate, ClientResponse
from audit import AuditAction
from deps import get_current_user, audit_logger

router = APIRouter(prefix="/api", tags=["clients"])


@router.post("/clients", response_model=ClientResponse)
async def create_client(client: ClientCreate, current_user: dict = Depends(get_current_user)):
    api_key = f"noc_{uuid.uuid4().hex}"
    client_doc = {
        "id": str(uuid.uuid4()), "name": client.name,
        "description": client.description or "", "contact_email": client.contact_email or "",
        "api_key": api_key, "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.clients.insert_one(client_doc)
    await audit_logger.log(
        AuditAction.CREATE_CLIENT, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="client", resource_id=client_doc["id"], details={"name": client.name}
    )
    return ClientResponse(**client_doc)


@router.get("/clients", response_model=List[ClientResponse])
async def get_clients(current_user: dict = Depends(get_current_user)):
    clients = await db.clients.find({}, {"_id": 0}).to_list(1000)
    return [ClientResponse(**c) for c in clients]


@router.get("/clients/{client_id}", response_model=ClientResponse)
async def get_client(client_id: str, current_user: dict = Depends(get_current_user)):
    client = await db.clients.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return ClientResponse(**client)


@router.delete("/clients/{client_id}")
async def delete_client(client_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.clients.delete_one({"id": client_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Client not found")
    await audit_logger.log(
        AuditAction.DELETE_CLIENT, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="client", resource_id=client_id
    )
    return {"message": "Client deleted"}


@router.post("/clients/{client_id}/regenerate-key")
async def regenerate_client_api_key(client_id: str, current_user: dict = Depends(get_current_user)):
    new_key = f"noc_{uuid.uuid4().hex}"
    result = await db.clients.update_one({"id": client_id}, {"$set": {"api_key": new_key}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Client not found")
    return {"api_key": new_key}
