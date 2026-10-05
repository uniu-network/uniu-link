import unittest
from unittest.mock import AsyncMock, MagicMock

from pydantic import ValidationError

from app.admin import ModelCreate, ModelUpdate, create_model, get_model, list_models, update_model
from app.models.model_config import ModelConfig


class ModelIconTests(unittest.IsolatedAsyncioTestCase):
    def test_icon_contract_and_partial_update(self):
        self.assertEqual(ModelCreate(name="alias").icon, "auto")
        self.assertNotIn("icon", ModelUpdate(display_name="Renamed").model_dump(exclude_unset=True))
        self.assertEqual(ModelUpdate(icon="auto").model_dump(exclude_unset=True), {"icon": "auto"})
        for invalid in (None, "", "https://example.com/icon.svg", "<svg/>", "unsupported"):
            with self.subTest(icon=invalid), self.assertRaises(ValidationError):
                ModelUpdate(icon=invalid)

    async def test_create_stores_manual_icon(self):
        db = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()
        await create_model(ModelCreate(name="my-alias", icon="deepseek"), db)
        model = db.add.call_args.args[0]
        self.assertEqual(model.icon, "deepseek")
        self.assertEqual(model.name, "my-alias")
        db.commit.assert_awaited_once()

    async def test_update_readback_and_reset_preserve_routing(self):
        model = ModelConfig(id="model-1", name="alias", icon="auto", routing_strategy="weighted")
        db = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = model
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()
        await update_model(model.id, ModelUpdate(icon="claude"), db)
        await update_model(model.id, ModelUpdate(display_name="New title"), db)
        response = await get_model(model.id, db)
        self.assertEqual(response["data"]["detail_result"]["icon"], "claude")
        self.assertEqual(model.routing_strategy, "weighted")
        models_result, refs_result = MagicMock(), MagicMock()
        models_result.scalars.return_value.all.return_value = [model]
        refs_result.scalars.return_value.all.return_value = []
        db.execute.side_effect = [models_result, refs_result]
        response = await list_models(db)
        self.assertEqual(response["data"]["detail_result"]["data"][0]["icon"], "claude")
        db.execute.side_effect = None
        await update_model(model.id, ModelUpdate(icon="auto"), db)
        self.assertEqual(model.icon, "auto")
