"""Super-admin endpoints. Authorization: platform super-admin flag, checked on the
server for every request (not just hidden in the UI). Every change is audit-logged."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter

from agentfirm.core.deps import DbSession, SuperAdmin

from . import service
from .service import CredentialIn, ImportResult, ModelIn, ModelOut, ModelPatch, OrgSummary, ProviderOut, ProviderPatch, RouteIn, RouteOut

router = APIRouter(prefix="/admin", tags=["admin"])

Capability = Literal["reasoning", "text", "code", "summarize", "classify", "creative", "vision", "long_context", "embeddings"]


@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(admin: SuperAdmin, session: DbSession) -> list[ProviderOut]:
    return await service.list_providers(session)


@router.patch("/providers/{provider_id}", response_model=ProviderOut)
async def patch_provider(provider_id: UUID, body: ProviderPatch, admin: SuperAdmin, session: DbSession) -> ProviderOut:
    return await service.patch_provider(session, admin, provider_id, body)


@router.put("/providers/{provider_id}/credential", response_model=ProviderOut)
async def set_credential(provider_id: UUID, body: CredentialIn, admin: SuperAdmin, session: DbSession) -> ProviderOut:
    return await service.set_credential(session, admin, provider_id, body)


@router.get("/models", response_model=list[ModelOut])
async def list_models(admin: SuperAdmin, session: DbSession) -> list[ModelOut]:
    return await service.list_models(session)


@router.post("/models", response_model=ModelOut, status_code=201)
async def create_model(body: ModelIn, admin: SuperAdmin, session: DbSession) -> ModelOut:
    return await service.create_model(session, admin, body)


@router.post("/providers/{provider_id}/import-models", response_model=ImportResult)
async def import_models(provider_id: UUID, admin: SuperAdmin, session: DbSession) -> ImportResult:
    """Pull the provider's model list (new models are created disabled for review)."""
    return await service.import_models(session, admin, provider_id)


@router.patch("/models/{model_id}", response_model=ModelOut)
async def patch_model(model_id: UUID, body: ModelPatch, admin: SuperAdmin, session: DbSession) -> ModelOut:
    return await service.patch_model(session, admin, model_id, body)


@router.get("/routes", response_model=list[RouteOut])
async def list_routes(admin: SuperAdmin, session: DbSession) -> list[RouteOut]:
    return await service.list_routes(session)


@router.put("/routes/{capability}", response_model=RouteOut)
async def set_route(capability: Capability, body: RouteIn, admin: SuperAdmin, session: DbSession) -> RouteOut:
    return await service.set_route(session, admin, capability, body)


@router.get("/routes/{capability}/resolve", response_model=list[ModelOut])
async def resolve(capability: Capability, admin: SuperAdmin, session: DbSession) -> list[ModelOut]:
    """Preview what the Gateway would try, in order, for this capability."""
    return await service.resolve_route(session, capability)


@router.get("/organizations", response_model=list[OrgSummary])
async def list_orgs(admin: SuperAdmin, session: DbSession) -> list[OrgSummary]:
    return await service.list_organizations(session)
