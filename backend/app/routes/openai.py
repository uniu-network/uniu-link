from fastapi import APIRouter, Request, BackgroundTasks, Depends
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.model_config import ModelConfig
from app.services.gateway_handler import handle_gateway_request
from app.dependencies.api_key_auth import require_api_key

router = APIRouter()


@router.get("/v1/models")
async def list_openai_models(request: Request, _key_info: dict = Depends(require_api_key)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ModelConfig).where(ModelConfig.is_listed == True)
        )
        models = result.scalars().all()

    model_list = [
        {"id": m.name, "object": "model", "created": int(m.created_at.timestamp()),
         "owned_by": m.display_name or m.name}
        for m in models
    ]

    return {"object": "list", "data": model_list}


@router.post("/v1/chat/completions")
async def openai_chat_completions(request: Request, background_tasks: BackgroundTasks, _key_info: dict = Depends(require_api_key)):
    return await handle_gateway_request(request, background_tasks, "openai")


@router.post("/v1/responses")
async def openai_responses(request: Request, background_tasks: BackgroundTasks, _key_info: dict = Depends(require_api_key)):
    return await handle_gateway_request(request, background_tasks, "responses")
