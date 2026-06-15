import importlib
import importlib.util
import sys
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any, cast
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.plugin import Plugin as PluginModel

logger = get_logger(__name__)


class PluginHook:

    name: str = "base"
    version: str = "1.0.0"

    async def pre_route(self, request_body: dict, api_type: str, context: dict) -> dict:
        return request_body

    async def on_channel_select(self, channels: list, context: dict) -> list:
        return channels

    async def pre_request(self, request_body: dict, channel_info, api_type: str, context: dict) -> dict:
        return request_body

    async def post_response(self, response: dict, api_type: str, context: dict) -> dict:
        return response

    async def on_error(self, error, channel_info, context: dict) -> dict:
        return {"retry": True, "status_code": 500}

    async def post_send(self, context: dict):
        pass


class PluginEngine:

    def __init__(self):
        self._plugins: list[PluginHook] = []
        self._loaded = False

    async def load_plugins(self):
        if self._loaded:
            return

        self._load_builtin_plugins()

        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(PluginModel).where(PluginModel.enabled == True).order_by(PluginModel.priority.desc())
                )
                db_plugins = result.scalars().all()

                for plugin_record in db_plugins:
                    try:
                        plugin_instance = self._load_module_plugin(plugin_record.module_path)
                        if plugin_instance:
                            if plugin_record.config:
                                for key, value in plugin_record.config.items():
                                    if hasattr(plugin_instance, key):
                                        setattr(plugin_instance, key, value)
                            self._plugins.append(plugin_instance)
                            logger.info(f"Loaded plugin: {plugin_record.name}")
                    except Exception as e:
                        logger.error(f"Failed to load plugin {plugin_record.name}: {e}")
        except Exception as e:
            logger.warning(f"Failed to load plugins from database: {e}")

        self._loaded = True
        logger.info(f"Plugin engine loaded {len(self._plugins)} plugins")

    def _load_builtin_plugins(self):
        builtin_dir = Path(__file__).parent
        for file in builtin_dir.glob("builtin_*.py"):
            try:
                module_name = f"app.plugins.{file.stem}"
                if module_name in sys.modules:
                    module = sys.modules[module_name]
                else:
                    module = importlib.import_module(module_name)

                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, PluginHook)
                        and attr is not PluginHook
                    ):
                        self._plugins.append(attr())
                        logger.info(f"Loaded builtin plugin: {attr_name}")
            except Exception as e:
                logger.error(f"Failed to load builtin plugin {file.name}: {e}")

    def _load_module_plugin(self, module_path: str) -> PluginHook | None:
        try:
            parts = module_path.rsplit(".", 1)
            if len(parts) == 2:
                module = importlib.import_module(parts[0])
                return getattr(module, parts[1])()
            else:
                module = importlib.import_module(module_path)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and issubclass(attr, PluginHook) and attr is not PluginHook:
                        return attr()
        except Exception as e:
            logger.error(f"Failed to load module plugin {module_path}: {e}")
        return None

    async def execute_hook(self, hook_name: str, *args: Any, **kwargs: Any) -> Any:
        for plugin in self._plugins:
            try:
                hook = getattr(plugin, hook_name, None)
                if hook and callable(hook):
                    hook_call = cast(Callable[..., Awaitable[Any]], hook)
                    if hook_name in ("pre_route", "pre_request", "post_response", "on_error"):
                        result = await hook_call(*args, **kwargs)
                        if hook_name == "pre_route":
                            kwargs["request_body"] = result
                        elif hook_name == "pre_request":
                            kwargs["request_body"] = result
                        elif hook_name == "post_response":
                            kwargs["response"] = result
                        elif hook_name == "on_error":
                            return result
                    elif hook_name == "on_channel_select":
                        channels = await hook_call(*args, **kwargs)
                        kwargs["channels"] = channels
                    else:
                        await hook_call(*args, **kwargs)
            except Exception as e:
                logger.error(f"Plugin {plugin.name} hook {hook_name} error: {e}")

        if hook_name == "pre_route":
            return kwargs.get("request_body", args[0] if args else {})
        elif hook_name == "on_channel_select":
            return kwargs.get("channels", args[0] if args else [])
        elif hook_name == "pre_request":
            return kwargs.get("request_body", args[0] if args else {})
        elif hook_name == "post_response":
            return kwargs.get("response", args[0] if args else {})
        elif hook_name == "on_error":
            return {"retry": True, "status_code": 500}
        return None


plugin_engine = PluginEngine()
