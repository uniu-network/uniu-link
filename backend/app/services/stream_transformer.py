"""Request-scoped SSE parsing and protocol conversion.

Transport EOF is deliberately not a protocol completion. Existing Claude
thinking signatures are preserved; missing signatures use compatibility values.
"""
import base64
import json
import time
import uuid
from typing import Any


class StreamProtocolError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def make_compat_thinking_signature() -> str:
    """Non-empty compatibility value, not an authentic provider signature."""
    return base64.b64encode(b"uniulink:" + uuid.uuid4().bytes).decode("ascii")


def sse_data(frame: str) -> str:
    lines = []
    for line in frame.splitlines():
        if line == "data":
            lines.append("")
        elif line.startswith("data:"):
            value = line[5:]
            lines.append(value[1:] if value.startswith(" ") else value)
    return "\n".join(lines)


def sse_payload(frame: str) -> dict[str, Any] | None:
    data = sse_data(frame)
    if not data or data.strip() == "[DONE]":
        return None
    try:
        payload = json.loads(data)
    except (ValueError, TypeError) as exc:
        raise StreamProtocolError("Invalid JSON in upstream SSE event") from exc
    if not isinstance(payload, dict):
        raise StreamProtocolError("Upstream SSE data must be a JSON object")
    return payload


def is_stream_done_chunk(frame: str) -> bool:
    if sse_data(frame).strip() == "[DONE]":
        return True
    payload = sse_payload(frame)
    return bool(payload and payload.get("type") in {
        "message_stop", "response.completed", "response.incomplete",
    })


def sse(event: dict[str, Any], named: bool = True) -> str:
    prefix = f"event: {event['type']}\n" if named else ""
    return prefix + "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


def stop_reason(reason: str | None, target: str, has_tools: bool = False) -> str:
    reason = reason or ("tool_calls" if has_tools else "stop")
    if target == "claude":
        return {"stop": "end_turn", "length": "max_tokens", "max_output_tokens": "max_tokens",
                "tool_calls": "tool_use", "function_call": "tool_use", "content_filter": "refusal"}.get(reason, reason)
    return {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
            "max_output_tokens": "length", "tool_use": "tool_calls", "refusal": "content_filter"}.get(reason, reason)


class StreamState:
    def __init__(self, source: str, target: str, model: str = ""):
        self.source = source
        self.target = target
        self.id = "resp_" + uuid.uuid4().hex
        self.model = model
        self.created = int(time.time())
        self.started = False
        self.seen_event = False
        # ``visible_output_seen`` marks output the caller can act on: text, a
        # tool call, or (on the Claude target) a thinking block. Reasoning on the
        # chat and Responses targets does not count, because it leaves their
        # visible text field empty. A terminal event that closes a turn without
        # this flag is treated as a silent refusal rather than a success.
        self.visible_output_seen = False
        self.finished = False
        self.reason: str | None = None
        self.sequence = 0
        self.blocks: list[dict[str, Any]] = []
        self.by_key: dict[Any, dict[str, Any]] = {}
        self.usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        self._out: list[str] = []
        self._claude_index = 0
        self._active_claude_block: dict[str, Any] | None = None
        self._claude_signatures: dict[int, bool] = {}
        self._finishing = False

    def _event(self, kind: str, **fields: Any) -> None:
        payload = {"type": kind, **fields}
        if self.target == "responses":
            payload["sequence_number"] = self.sequence
            self.sequence += 1
        self._out.append(sse(payload))

    def _chat(self, delta: dict[str, Any], finish: str | None = None, usage: bool = False) -> None:
        payload: dict[str, Any] = {
            "id": self.id, "object": "chat.completion.chunk", "created": self.created,
            "model": self.model,
            "choices": [] if usage else [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        if usage:
            payload["usage"] = {"prompt_tokens": self.usage["input_tokens"],
                                "completion_tokens": self.usage["output_tokens"],
                                "total_tokens": self.usage["total_tokens"]}
        self._out.append(sse(payload, named=False))

    def _response(self, status: str) -> dict[str, Any]:
        return {
            "id": self.id, "object": "response", "created_at": self.created,
            "model": self.model, "status": status, "error": None,
            "incomplete_details": {"reason": "max_output_tokens" if stop_reason(self.reason, "openai") == "length" else "content_filter"} if status == "incomplete" else None,
            "output": [self._item(b, status) for b in self.blocks],
            "usage": dict(self.usage), "parallel_tool_calls": True, "tool_choice": "auto",
            "tools": [], "temperature": None, "top_p": None,
        }

    def _item(self, block: dict[str, Any], status: str = "in_progress") -> dict[str, Any]:
        item_status = "completed" if block["closed"] else status
        if block["kind"] == "tool":
            return {"id": block["id"], "type": "function_call", "call_id": block["call_id"],
                    "name": block["name"], "arguments": block["text"], "status": item_status}
        if block["kind"] == "thinking":
            return {"id": block["id"], "type": "reasoning", "status": item_status,
                    "summary": [{"type": "summary_text", "text": block["text"]}]}
        return {"id": block["id"], "type": "message", "role": "assistant", "status": item_status,
                "content": [{"type": "output_text", "text": block["text"], "annotations": []}]}

    def _start(self) -> None:
        if self.started:
            return
        self.started = True
        if self.target == "openai":
            self._chat({"role": "assistant", "content": ""})
        elif self.target == "responses":
            self._event("response.created", response=self._response("in_progress"))
            self._event("response.in_progress", response=self._response("in_progress"))
        else:
            self._event("message_start", message={
                "id": self.id, "type": "message", "role": "assistant", "model": self.model,
                "content": [], "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": self.usage["input_tokens"], "output_tokens": 0},
            })

    def _block(self, key: Any, kind: str, call_id: str = "", name: str = "") -> dict[str, Any]:
        if key in self.by_key and not (isinstance(key, str) and (
            self.by_key[key]["closed"] or
            (self.target == "claude" and self.blocks[-1] is not self.by_key[key])
        )):
            block = self.by_key[key]
            if call_id:
                block["call_id"] = call_id
            if name:
                block["name"] = name
            return block
        self._start()
        deferred = self.target == "claude" and (kind == "tool" or any(b["deferred"] for b in self.blocks))
        if deferred and self._active_claude_block:
            self._close_block(self._active_claude_block)
        block = {"kind": kind, "index": len(self.blocks), "id": "item_" + uuid.uuid4().hex,
                 "call_id": call_id or "call_" + uuid.uuid4().hex, "name": name,
                 "text": "", "closed": False, "emitted": False, "deferred": deferred}
        self.blocks.append(block)
        self.by_key[key] = block
        if kind == "tool":
            block["tool_index"] = sum(b["kind"] == "tool" for b in self.blocks) - 1
            # A tool call is actionable output even when its arguments stream
            # later or never arrive at all.
            self._mark_output("tool")
        # Chat can interleave parallel tools. Buffer them for Claude, whose
        # content blocks must be emitted sequentially.
        if not deferred:
            self._open_block(block)
        return block

    def _open_block(self, block: dict[str, Any]) -> None:
        if block["emitted"]:
            return
        block["emitted"] = True
        kind = block["kind"]
        if self.target == "responses":
            item = self._item(block)
            if kind != "tool":
                item["summary" if kind == "thinking" else "content"] = []
            self._event("response.output_item.added", output_index=block["index"], item=item)
            if kind == "text":
                self._event("response.content_part.added", item_id=block["id"], output_index=block["index"],
                            content_index=0, part={"type": "output_text", "text": "", "annotations": []})
            elif kind == "thinking":
                self._event("response.reasoning_summary_part.added", item_id=block["id"],
                            output_index=block["index"], summary_index=0, part={"type": "summary_text", "text": ""})
        elif self.target == "openai":
            if kind == "tool":
                self._chat({"tool_calls": [{"index": block["tool_index"], "id": block["call_id"],
                                            "type": "function", "function": {"name": block["name"], "arguments": ""}}]})
        else:
            if self._active_claude_block:
                self._close_block(self._active_claude_block)
            block["claude_index"] = self._claude_index
            self._claude_index += 1
            self._active_claude_block = block
            if kind == "tool":
                content = {"type": "tool_use", "id": block["call_id"], "name": block["name"], "input": {}}
            elif kind == "thinking":
                content = {"type": "thinking", "thinking": "", "signature": ""}
            else:
                content = {"type": "text", "text": ""}
            self._event("content_block_start", index=block["claude_index"], content_block=content)

    def _mark_output(self, kind: str) -> None:
        """Record that the turn produced something the caller can act on.

        Claude thinking counts, because it is a first-class content block there.
        Chat and Responses reasoning does not: their visible text field stays
        empty, which is exactly what makes a reasoning-only turn read as "no
        content" on those clients.
        """
        if kind != "thinking" or self.target == "claude":
            self.visible_output_seen = True

    def _append(self, block: dict[str, Any], text: str) -> None:
        if not text:
            return
        if block["closed"]:
            raise StreamProtocolError("Upstream emitted a delta after its content block ended")
        kind = block["kind"]
        self._mark_output(kind)
        if self.target == "responses" or block["deferred"]:
            block["text"] += text
        if self.target == "responses":
            fields = {"item_id": block["id"], "output_index": block["index"], "delta": text}
            if kind == "tool":
                self._event("response.function_call_arguments.delta", **fields)
            elif kind == "thinking":
                self._event("response.reasoning_summary_text.delta", summary_index=0, **fields)
            else:
                self._event("response.output_text.delta", content_index=0, logprobs=[], **fields)
        elif self.target == "openai":
            if kind == "tool":
                self._chat({"tool_calls": [{"index": block["tool_index"], "function": {"arguments": text}}]})
            else:
                self._chat({"reasoning_content" if kind == "thinking" else "content": text})
        elif not block["deferred"]:
            delta = {"type": "thinking_delta", "thinking": text} if kind == "thinking" else {"type": "text_delta", "text": text}
            self._event("content_block_delta", index=block["claude_index"], delta=delta)

    def _close_block(self, block: dict[str, Any]) -> None:
        if block["closed"]:
            return
        kind = block["kind"]
        if block["deferred"] and not self._finishing:
            return
        if self.target == "claude" and block["deferred"]:
            self._open_block(block)
            if kind == "tool":
                delta = {"type": "input_json_delta", "partial_json": block["text"] or "{}"}
            elif kind == "thinking":
                delta = {"type": "thinking_delta", "thinking": block["text"]}
            else:
                delta = {"type": "text_delta", "text": block["text"]}
            self._event("content_block_delta", index=block["claude_index"],
                        delta=delta)
        block["closed"] = True
        if self.target == "responses":
            fields = {"item_id": block["id"], "output_index": block["index"]}
            if kind == "tool":
                self._event("response.function_call_arguments.done", arguments=block["text"], name=block["name"], **fields)
            elif kind == "thinking":
                self._event("response.reasoning_summary_text.done", summary_index=0, text=block["text"], **fields)
                self._event("response.reasoning_summary_part.done", summary_index=0,
                            part={"type": "summary_text", "text": block["text"]}, **fields)
            else:
                self._event("response.output_text.done", content_index=0, text=block["text"], logprobs=[], **fields)
                self._event("response.content_part.done", content_index=0,
                            part={"type": "output_text", "text": block["text"], "annotations": []}, **fields)
            self._event("response.output_item.done", output_index=block["index"], item=self._item(block))
        elif self.target == "claude":
            if kind == "thinking":
                self._event("content_block_delta", index=block["claude_index"], delta={
                    "type": "signature_delta", "signature": make_compat_thinking_signature(),
                })
            self._event("content_block_stop", index=block["claude_index"])
            if self._active_claude_block is block:
                self._active_claude_block = None

    def _usage(self, payload: dict[str, Any]) -> None:
        for obj in (payload, payload.get("message"), payload.get("response")):
            if not isinstance(obj, dict) or not isinstance(obj.get("usage"), dict):
                continue
            usage = obj["usage"]
            for target, keys in (("input_tokens", ("input_tokens", "prompt_tokens")),
                                 ("output_tokens", ("output_tokens", "completion_tokens")),
                                 ("total_tokens", ("total_tokens",))):
                for key in keys:
                    if usage.get(key) is not None:
                        self.usage[target] = max(self.usage[target], int(usage[key]))
            self.usage["total_tokens"] = max(self.usage["total_tokens"], self.usage["input_tokens"] + self.usage["output_tokens"])

    def _finish(self) -> None:
        self._start()
        self._finishing = True
        for block in self.blocks:
            self._close_block(block)
        tools = any(b["kind"] == "tool" for b in self.blocks)
        reason = stop_reason(self.reason, self.target, tools)
        if self.target == "openai":
            self._chat({}, reason)
            self._chat({}, usage=True)
            self._out.append("data: [DONE]\n\n")
        elif self.target == "claude":
            self._event("message_delta", delta={"stop_reason": reason, "stop_sequence": None},
                        usage={"input_tokens": self.usage["input_tokens"], "output_tokens": self.usage["output_tokens"]})
            self._event("message_stop")
        else:
            status = "incomplete" if reason in ("length", "content_filter") else "completed"
            self._event("response." + status, response=self._response(status))

    # Finish reasons that legitimately close a turn with no visible text. The
    # set covers both chat and Responses vocabularies.
    _LEGIT_EMPTY_REASONS = frozenset({
        "length", "max_tokens", "max_output_tokens",
        "content_filter", "refusal",
        "tool_calls", "function_call", "tool_use",
    })

    def _observe_frame_content(self, payload: dict[str, Any] | None, event_type: str) -> None:
        """Track real output for same-protocol pass-through frames.

        Cross-protocol readers already set the flags from parsed blocks; a
        pass-through stream never reaches them, so the raw event is inspected
        here. Lifecycle frames (``response.created`` / ``in_progress``, a
        role-only or usage-only ``choices`` entry) deliberately do not count,
        otherwise a stream that only ever emitted them would look valid.

        The finish reason is recorded as well, because the readers that normally
        do that are skipped on this path.
        """
        if not payload:
            return
        if self.target == "openai":
            for choice in payload.get("choices") or []:
                delta = choice.get("delta") or {}
                if choice.get("finish_reason"):
                    self.reason = choice["finish_reason"]
                if delta.get("content"):
                    self._mark_output("text")
                for tool in delta.get("tool_calls") or []:
                    fn = tool.get("function") or {}
                    if tool.get("id") or fn.get("name"):
                        self._mark_output("tool")
            return
        if self.target == "claude":
            kind = payload.get("type")
            if kind == "message_delta":
                stop_reason = (payload.get("delta") or {}).get("stop_reason")
                if stop_reason:
                    self.reason = stop_reason
            elif kind == "content_block_start":
                content = payload.get("content_block") or {}
                if content.get("type") == "tool_use":
                    self._mark_output("tool")
                elif content.get("text") or content.get("thinking"):
                    self._mark_output("thinking" if content.get("type") == "thinking" else "text")
            elif kind == "content_block_delta":
                delta = payload.get("delta") or {}
                if delta.get("text"):
                    self._mark_output("text")
                elif delta.get("partial_json"):
                    self._mark_output("tool")
                elif delta.get("thinking"):
                    self._mark_output("thinking")
            return
        if event_type == "response.output_text.delta":
            if payload.get("delta"):
                self._mark_output("text")
        elif event_type == "response.function_call_arguments.delta":
            self._mark_output("tool")
        elif event_type in ("response.content_part.added", "response.content_part.done"):
            if (payload.get("part") or {}).get("text"):
                self._mark_output("text")
        elif event_type in ("response.output_item.added", "response.output_item.done"):
            item = payload.get("item") or {}
            item_type = item.get("type")
            if item_type == "function_call":
                self._mark_output("tool")
            elif item_type == "message":
                for part in item.get("content") or []:
                    if isinstance(part, dict) and part.get("text"):
                        self._mark_output("text")
                        break
        elif event_type in ("response.completed", "response.incomplete"):
            # An upstream may stream no deltas and deliver the whole output
            # only on the terminal event, which then passes through verbatim;
            # those items are content the client can still read, so scan them
            # like ``output_item.done``. Reasoning items stay excluded,
            # keeping the reasoning-only rejection intact.
            response = payload.get("response")
            if isinstance(response, dict):
                for item in response.get("output") or []:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") == "function_call":
                        self._mark_output("tool")
                    elif item.get("type") == "message":
                        for part in item.get("content") or []:
                            if isinstance(part, dict) and part.get("text"):
                                self._mark_output("text")
                                break

    def _is_empty_terminal(self, payload: dict[str, Any] | None, event_type: str) -> bool:
        """Report a terminal event that closes a turn with nothing actionable.

        Mirrors the silent-refusal guard other aggregators apply to
        ``response.completed``, but the criterion is "no visible text and no
        tool call" rather than "no usage": UniuLink forces
        ``stream_options.include_usage``, so a usage-only chunk with
        ``choices: []`` would otherwise mask an empty turn. Reasoning alone does
        not count, except on the Claude target where thinking is a first-class
        content block (see ``_mark_output``).
        """
        if self.visible_output_seen:
            return False
        if (self.reason or "").strip().lower() in self._LEGIT_EMPTY_REASONS:
            return False
        # A truncation is a legitimate terminal, not a silent refusal. Only
        # completed terminals are judged, matching the other aggregators.
        if self.source == "responses":
            if event_type == "response.incomplete":
                return False
            response = payload.get("response") if payload else None
            if isinstance(response, dict) and response.get("status") == "incomplete":
                return False
        if payload is not None:
            error = payload.get("error") or (payload.get("response") or {}).get("error")
            if error:
                return False
        return True

    def feed(self, frame: str) -> str | None:
        if self.finished:
            return None
        self._out = []
        payload = sse_payload(frame)
        data = sse_data(frame).strip()
        if payload is None and data != "[DONE]":
            return frame if self.source == self.target and self.seen_event else None
        if payload is not None:
            event_type = payload.get("type", "")
            error = payload.get("error") or (payload.get("response") or {}).get("error")
            if error or event_type in ("error", "response.failed", "response.cancelled"):
                if not error and event_type == "error":
                    error = payload
                message = error.get("message", "Upstream stream failed") if isinstance(error, dict) else str(error or "Upstream stream failed")
                code = 529 if isinstance(error, dict) and error.get("type") == "overloaded_error" else 502
                raise StreamProtocolError(message, code)
            self._usage(payload)
        else:
            event_type = ""
        terminal = ((self.source == "openai" and data == "[DONE]") or
                    (self.source == "claude" and event_type == "message_stop") or
                    (self.source == "responses" and event_type in ("response.completed", "response.incomplete")))
        if self.source == self.target:
            if self.target == "responses" and payload and isinstance(payload.get("sequence_number"), int):
                self.sequence = max(self.sequence, payload["sequence_number"] + 1)
            if payload and ("choices" in payload or event_type in ("message_start", "response.created", "response.completed", "response.incomplete")):
                self.seen_event = True
            self._observe_frame_content(payload, event_type)
            if terminal:
                if not self.seen_event:
                    raise StreamProtocolError("Upstream stream ended without a response")
                if self._is_empty_terminal(payload, event_type):
                    raise StreamProtocolError(
                        "Upstream returned an empty stream with no visible content", 502,
                    )
                self.finished = True
            if self.target == "claude" and payload:
                return self._passthrough_claude(frame, payload)
            return frame if frame.endswith("\n\n") else frame + "\n\n"
        if payload:
            meta = payload.get("message") or payload.get("response") or payload
            if not self.started:
                self.id = meta.get("id") or self.id
                self.model = meta.get("model") or self.model
            if self.source == "openai":
                self._read_chat(payload)
            elif self.source == "claude":
                self._read_claude(payload)
            else:
                self._read_responses(payload)
        if terminal:
            if not self.seen_event:
                raise StreamProtocolError("Upstream stream ended without a response")
            if self._is_empty_terminal(payload, event_type):
                raise StreamProtocolError(
                    "Upstream returned an empty stream with no visible content", 502,
                )
            self._finish()
            self.finished = True
        return "".join(self._out) or None

    def _passthrough_claude(self, frame: str, payload: dict[str, Any]) -> str:
        kind = payload.get("type")
        index = payload.get("index", 0)
        if kind == "content_block_start":
            content = payload.get("content_block") or {}
            if content.get("type") == "thinking":
                self._claude_signatures[index] = bool(content.get("signature"))
                if content.get("signature") is None:
                    frame = sse({**payload, "content_block": {**content, "signature": ""}})
        elif kind == "content_block_delta" and index in self._claude_signatures:
            delta = payload.get("delta") or {}
            if delta.get("type") == "signature_delta" and delta.get("signature"):
                self._claude_signatures[index] = True
        elif kind == "content_block_stop" and index in self._claude_signatures:
            if not self._claude_signatures.pop(index):
                frame = sse({"type": "content_block_delta", "index": index, "delta": {
                    "type": "signature_delta", "signature": make_compat_thinking_signature(),
                }}) + frame
        return frame if frame.endswith("\n\n") else frame + "\n\n"

    def _read_chat(self, payload: dict[str, Any]) -> None:
        if "choices" not in payload:
            return
        self.seen_event = True
        for choice in payload.get("choices", []):
            if choice.get("index", 0) != 0:
                raise StreamProtocolError("Multiple choices cannot be converted to this protocol")
            delta = choice.get("delta") or {}
            if delta.get("role"):
                self._start()
            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            if reasoning:
                self._append(self._block("thinking", "thinking"), reasoning)
            if delta.get("content"):
                self._append(self._block("text", "text"), delta["content"])
            for tool in delta.get("tool_calls") or []:
                fn = tool.get("function") or {}
                block = self._block(("tool", tool.get("index", 0)), "tool", tool.get("id", ""), fn.get("name", ""))
                self._append(block, fn.get("arguments", ""))
            if choice.get("finish_reason"):
                self.reason = choice["finish_reason"]

    def _read_claude(self, payload: dict[str, Any]) -> None:
        kind = payload.get("type")
        key = ("claude", payload.get("index", 0))
        if kind == "message_start":
            self.seen_event = True
            self._start()
        elif kind == "content_block_start":
            content = payload.get("content_block") or {}
            block_type = content.get("type")
            if block_type in ("text", "thinking", "tool_use"):
                block = self._block(key, "tool" if block_type == "tool_use" else block_type,
                                    content.get("id", ""), content.get("name", ""))
                text = content.get("text") or content.get("thinking") or ""
                if block_type == "tool_use" and content.get("input"):
                    text = json.dumps(content["input"], ensure_ascii=False)
                self._append(block, text)
        elif kind == "content_block_delta":
            delta = payload.get("delta") or {}
            if delta.get("type") == "signature_delta":
                return
            block = self.by_key.get(key)
            if block:
                self._append(block, delta.get("text") or delta.get("thinking") or delta.get("partial_json") or "")
        elif kind == "content_block_stop":
            block = self.by_key.get(key)
            if block:
                self._close_block(block)
        elif kind == "message_delta":
            self.reason = (payload.get("delta") or {}).get("stop_reason") or self.reason

    def _read_responses(self, payload: dict[str, Any]) -> None:
        kind = payload.get("type", "")
        index = payload.get("output_index", 0)
        key = ("responses", index)
        if kind == "response.created":
            self.seen_event = True
            self._start()
        elif kind == "response.output_item.added":
            item = payload.get("item") or {}
            if item.get("type") == "function_call":
                block = self._block(key, "tool", item.get("call_id", ""), item.get("name", ""))
                self._append(block, item.get("arguments", ""))
        elif kind in ("response.output_text.delta", "response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
            thinking = kind != "response.output_text.delta"
            part_key = (key, kind, payload.get("summary_index" if kind == "response.reasoning_summary_text.delta" else "content_index", 0))
            self._append(self._block(part_key, "thinking" if thinking else "text"), payload.get("delta", ""))
        elif kind == "response.function_call_arguments.delta":
            block = self.by_key.get(key)
            if block is None:
                raise StreamProtocolError("Tool arguments arrived before the tool definition")
            self._append(block, payload.get("delta", ""))
        elif kind == "response.output_item.done":
            for block_key, block in self.by_key.items():
                if block_key == key or (isinstance(block_key, tuple) and block_key[0] == key):
                    self._close_block(block)
        elif kind in ("response.completed", "response.incomplete"):
            self.seen_event = True
            response = payload.get("response") or {}
            self.reason = (response.get("incomplete_details") or {}).get("reason")
