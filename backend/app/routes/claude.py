from fastapi import APIRouter, Request, BackgroundTasks, Depends
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.model_config import ModelConfig
from app.services.gateway_handler import handle_gateway_request
from app.dependencies.api_key_auth import require_api_key

router = APIRouter()


@router.get("/v1/messages/models")
async def list_claude_models(request: Request, _key_info: dict = Depends(require_api_key)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ModelConfig).where(ModelConfig.is_listed == True)
        )
        models = result.scalars().all()

    model_data = [
        {
            "id": m.name,
            "display_name": m.display_name or m.name,
            "type": "model",
            "created_at": m.created_at.isoformat(),
        }
        for m in models
    ]

    return {"data": model_data}


@router.post("/v1/messages")
async def claude_messages(request: Request, background_tasks: BackgroundTasks, _key_info: dict = Depends(require_api_key)):
    return await handle_gateway_request(request, background_tasks, "claude")
