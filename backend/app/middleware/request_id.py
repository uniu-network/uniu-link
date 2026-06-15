import uuid
from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="")


def get_trace_id() -> str:
    return trace_id_ctx.get()


class RequestIDMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("x-request-id", "")
        if not trace_id:
            trace_id = str(uuid.uuid4())

        trace_id_ctx.set(trace_id)
        request.state.trace_id = trace_id

        response: Response = await call_next(request)

        response.headers["x-request-id"] = trace_id
        response.headers["x-trace-id"] = trace_id

        return response
