"""Super-admin web-search settings. Platform administrators only; every change is audit-logged."""

from __future__ import annotations

from fastapi import APIRouter

from agentfirm.core.deps import DbSession, SuperAdmin

from . import service
from .service import BraveKeyIn, SearchSettingsIn, SearchSettingsOut, SearchTestIn, SearchTestOut

router = APIRouter(prefix="/admin/search", tags=["admin"])


@router.get("", response_model=SearchSettingsOut)
async def get_search(admin: SuperAdmin, session: DbSession) -> SearchSettingsOut:
    return await service.get_settings_out(session)


@router.put("", response_model=SearchSettingsOut)
async def put_search(body: SearchSettingsIn, admin: SuperAdmin, session: DbSession) -> SearchSettingsOut:
    return await service.update_settings(session, admin, body)


@router.put("/brave-key", response_model=SearchSettingsOut)
async def put_brave_key(body: BraveKeyIn, admin: SuperAdmin, session: DbSession) -> SearchSettingsOut:
    return await service.set_brave_key(session, admin, body)


@router.delete("/brave-key", response_model=SearchSettingsOut)
async def delete_brave_key(admin: SuperAdmin, session: DbSession) -> SearchSettingsOut:
    return await service.clear_brave_key(session, admin)


@router.post("/test", response_model=SearchTestOut)
async def test_search(body: SearchTestIn, admin: SuperAdmin, session: DbSession) -> SearchTestOut:
    return await service.run_test(session, admin, body)
