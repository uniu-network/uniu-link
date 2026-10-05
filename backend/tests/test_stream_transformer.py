import json
import unittest

import httpx
from anthropic import Anthropic
from openai import OpenAI

from app.services.request_transformer import transform_request_body, transform_response_body
from app.services.stream_transformer import StreamState, StreamProtocolError, is_stream_done_chunk, sse, sse_payload


def chat(delta=None, finish=None, usage=None):
    payload = {"id": "chatcmpl-source", "object": "chat.completion.chunk", "created": 1, "model": "upstream",
               "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}]}
    if usage is not None:
        payload["choices"] = []
        payload["usage"] = usage
    return sse(payload, named=False)


def source_events(source):
    if source == "openai":
        return [chat({"role": "assistant"}), chat({"content": "你好"}),
                chat({"tool_calls": [{"index": 0, "id": "call-1", "type": "function", "function": {"name": "weather", "arguments": '{"city":'}}]}),
                chat({"tool_calls": [{"index": 0, "function": {"arguments": '"上海"}'}}]}),
                chat(finish="tool_calls"), chat(usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}),
                "data: [DONE]\n\n"]
    if source == "claude":
        return [sse({"type": "message_start", "message": {"id": "msg-source", "type": "message", "role": "assistant", "content": [], "model": "upstream", "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 11, "output_tokens": 0}}}),
                sse({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
                sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "你好"}}),
                sse({"type": "content_block_stop", "index": 0}),
                sse({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "call-1", "name": "weather", "input": {}}}),
                sse({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"city":"上海"}'}}),
                sse({"type": "content_block_stop", "index": 1}),
                sse({"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None}, "usage": {"output_tokens": 7}}),
                sse({"type": "message_stop"})]
    return [sse({"type": "response.created", "response": {"id": "resp-source", "model": "upstream"}}),
            sse({"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "delta": "你好"}),
            sse({"type": "response.output_item.done", "output_index": 0}),
            sse({"type": "response.output_item.added", "output_index": 1, "item": {"type": "function_call", "call_id": "call-1", "name": "weather", "arguments": ""}}),
            sse({"type": "response.function_call_arguments.delta", "output_index": 1, "delta": '{"city":"上海"}'}),
            sse({"type": "response.output_item.done", "output_index": 1}),
            sse({"type": "response.completed", "response": {"id": "resp-source", "status": "completed", "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}}})]


def converted_stream(source, target, events=None):
    state = StreamState(source, target)
    wire = "".join(state.feed(frame) or "" for frame in (events or source_events(source)))
    assert state.finished
    return wire


def http_client(wire):
    return httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, content=wire.encode(),
    )))


def claude_message(wire):
    with Anthropic(api_key="test", http_client=http_client(wire)) as client:
        with client.messages.stream(model="public", max_tokens=100, messages=[]) as stream:
            return stream.get_final_message()


class StreamTransformerTests(unittest.TestCase):
    def assert_thinking_signatures(self, wire):
        events = [sse_payload(frame) for frame in wire.strip().split("\n\n")]
        thinking = {e["index"] for e in events if e["type"] == "content_block_start" and e["content_block"]["type"] == "thinking"}
        signatures = []
        for index in thinking:
            block_events = [e for e in events if e.get("index") == index]
            self.assertEqual(block_events[-1]["type"], "content_block_stop")
            self.assertEqual(block_events[-2]["delta"]["type"], "signature_delta")
            signature_events = [e for e in block_events if e.get("delta", {}).get("type") == "signature_delta"]
            self.assertEqual(len(signature_events), 1)
            signature = signature_events[0]["delta"]["signature"]
            self.assertTrue(signature)
            signatures.append(signature)
            self.assertTrue(all(e.get("delta", {}).get("type") != "text_delta" for e in block_events))
        self.assertEqual(len(signatures), len(set(signatures)))

    def test_all_cross_protocol_paths_with_real_sdk_aggregation(self):
        for source in ("openai", "claude", "responses"):
            for target in ("openai", "claude", "responses"):
                if source == target:
                    continue
                with self.subTest(source=source, target=target):
                    wire = converted_stream(source, target)
                    if target == "responses":
                        with OpenAI(api_key="test", http_client=http_client(wire)) as client:
                            with client.responses.stream(model="public", input="hi") as stream:
                                events = list(stream)
                                result = stream.get_final_response()
                        self.assertEqual(result.output_text, "你好")
                        self.assertEqual(len(result.output[0].content), 1)
                        self.assertEqual([e.snapshot for e in events if e.type == "response.output_text.delta"], ["你好"])
                        self.assertEqual(result.output[1].call_id, "call-1")
                        self.assertEqual(json.loads(result.output[1].arguments), {"city": "上海"})
                        self.assertEqual(result.usage.total_tokens, 18)
                        numbers = [e.sequence_number for e in events if hasattr(e, "sequence_number")]
                        self.assertEqual(numbers, sorted(set(numbers)))
                    elif target == "claude":
                        with Anthropic(api_key="test", http_client=http_client(wire)) as client:
                            with client.messages.stream(model="public", max_tokens=100, messages=[{"role": "user", "content": "hi"}]) as stream:
                                result = stream.get_final_message()
                        self.assertEqual(result.content[0].text, "你好")
                        self.assertEqual(result.content[1].id, "call-1")
                        self.assertEqual(result.content[1].input, {"city": "上海"})
                        self.assertEqual(result.stop_reason, "tool_use")
                        self.assertEqual((result.usage.input_tokens, result.usage.output_tokens), (11, 7))
                    else:
                        with OpenAI(api_key="test", http_client=http_client(wire)) as client:
                            chunks = list(client.chat.completions.create(model="public", messages=[], stream=True))
                        self.assertEqual(len({c.id for c in chunks}), 1)
                        self.assertEqual(len({c.model for c in chunks}), 1)
                        self.assertEqual("".join(c.choices[0].delta.content or "" for c in chunks if c.choices), "你好")
                        calls = [t for c in chunks if c.choices for t in c.choices[0].delta.tool_calls or []]
                        self.assertEqual(calls[0].id, "call-1")
                        self.assertEqual(json.loads("".join(t.function.arguments or "" for t in calls)), {"city": "上海"})
                        self.assertEqual(chunks[-2].choices[0].finish_reason, "tool_calls")
                        self.assertEqual(chunks[-1].usage.total_tokens, 18)

    def test_passthrough_keeps_claude_signature_exactly(self):
        frames = source_events("claude")[:1] + [
            sse({"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}}),
            sse({"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "opaque-authentic-signature"}}),
            sse({"type": "content_block_stop", "index": 0}), sse({"type": "message_stop"}),
        ]
        self.assertEqual(converted_stream("claude", "claude", frames), "".join(frames))

    def test_multiline_data_and_literal_done_in_text(self):
        frame = 'data: {"choices": [\ndata: {"delta": {"content": "data: [DONE]"}, "index": 0}]}\n\n'
        self.assertFalse(is_stream_done_chunk(frame))
        state = StreamState("openai", "responses")
        converted = state.feed(frame)
        self.assertIn('"delta": "data: [DONE]"', converted)
        self.assertFalse(state.finished)
        self.assertTrue(is_stream_done_chunk('data:[DONE]\n\n'))

    def test_error_events_never_finish_successfully(self):
        for source, payload in (("claude", {"type": "error", "error": {"message": "busy"}}),
                                ("responses", {"type": "response.failed", "response": {"error": {"message": "failed"}}}),
                                ("openai", {"error": {"message": "failed"}})):
            for target in ("openai", "responses", "claude"):
                with self.subTest(source=source, target=target):
                    state = StreamState(source, target)
                    with self.assertRaises(StreamProtocolError):
                        state.feed(sse(payload, named=False))
                    self.assertFalse(state.finished)

    def test_flat_responses_error_retains_message(self):
        state = StreamState("responses", "openai")
        with self.assertRaisesRegex(StreamProtocolError, "rate limit"):
            state.feed(sse({"type": "error", "code": "rate_limit_exceeded", "message": "rate limit"}))

    def test_length_maps_to_target_stop_and_final_usage(self):
        frames = [chat({"content": "cut"}), chat(finish="length"),
                  chat(usage={"prompt_tokens": 4, "completion_tokens": 9}), "data: [DONE]\n\n"]
        wire = converted_stream("openai", "claude", frames)
        self.assertIn('"stop_reason": "max_tokens"', wire)
        self.assertIn('"input_tokens": 4, "output_tokens": 9', wire)
        wire = converted_stream("openai", "responses", frames)
        self.assertIn('"type": "response.incomplete"', wire)
        self.assertNotIn('"type": "response.completed"', wire)

    def test_parallel_tool_argument_streams(self):
        frames = [chat({"tool_calls": [
            {"index": 0, "id": "a", "type": "function", "function": {"name": "one", "arguments": '{"a":'}},
            {"index": 1, "id": "b", "type": "function", "function": {"name": "two", "arguments": '{"b":'}},
        ]}), chat({"tool_calls": [{"index": 1, "function": {"arguments": '2}'}}, {"index": 0, "function": {"arguments": '1}'}}]}),
                  chat(finish="tool_calls"), "data: [DONE]\n\n"]
        wire = converted_stream("openai", "claude", frames)
        with Anthropic(api_key="test", http_client=http_client(wire)) as client:
            with client.messages.stream(model="public", max_tokens=100, messages=[]) as stream:
                result = stream.get_final_message()
        self.assertEqual([b.input for b in result.content], [{"a": 1}, {"b": 2}])

    def test_claude_preserves_order_after_buffered_tool(self):
        frames = [chat({"tool_calls": [{"index": 0, "id": "a", "type": "function", "function": {"name": "one", "arguments": '{}'}}]}),
                  chat({"content": "after tool"}), chat(finish="tool_calls"), "data: [DONE]\n\n"]
        wire = converted_stream("openai", "claude", frames)
        with Anthropic(api_key="test", http_client=http_client(wire)) as client:
            with client.messages.stream(model="public", max_tokens=100, messages=[]) as stream:
                result = stream.get_final_message()
        self.assertEqual([b.type for b in result.content], ["tool_use", "text"])
        self.assertEqual(result.content[1].text, "after tool")

    def test_claude_cross_provider_reasoning_uses_thinking_blocks_with_compat_signatures(self):
        frames = [chat({"reasoning_content": "first"}), chat({"content": "answer"}),
                  chat({"reasoning_content": "second"}), chat(finish="stop"), "data: [DONE]\n\n"]
        wire = converted_stream("openai", "claude", frames)
        result = claude_message(wire)
        self.assertEqual([b.type for b in result.content], ["thinking", "text", "thinking"])
        self.assertEqual([result.content[0].thinking, result.content[1].text, result.content[2].thinking], ["first", "answer", "second"])
        self.assert_thinking_signatures(wire)

    def test_responses_summary_and_reasoning_text_become_thinking(self):
        for kind in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
            with self.subTest(kind=kind):
                frames = [source_events("responses")[0],
                          sse({"type": kind, "output_index": 0, "delta": "先思考"}),
                          sse({"type": kind, "output_index": 0, "delta": "再确认"}),
                          sse({"type": "response.output_item.done", "output_index": 0}),
                          sse({"type": "response.output_text.delta", "output_index": 1, "delta": "答案"}),
                          source_events("responses")[-1]]
                wire = converted_stream("responses", "claude", frames)
                result = claude_message(wire)
                self.assertEqual([b.type for b in result.content], ["thinking", "text"])
                self.assertEqual(result.content[0].thinking, "先思考再确认")
                self.assertEqual(result.content[1].text, "答案")
                self.assertEqual((result.usage.input_tokens, result.usage.output_tokens), (11, 7))
                self.assert_thinking_signatures(wire)

    def test_chat_reasoning_alias_streams_before_terminal_event(self):
        state = StreamState("openai", "claude")
        partial = state.feed(chat({"reasoning": "live reasoning"}))
        self.assertIn('"type": "thinking_delta"', partial)
        self.assertNotIn('"type": "text_delta"', partial)
        self.assertNotIn('"type": "signature_delta"', partial)
        wire = partial + state.feed("data: [DONE]\n\n")
        result = claude_message(wire)
        self.assertEqual(result.content[0].thinking, "live reasoning")
        self.assert_thinking_signatures(wire)

    def test_thinking_around_buffered_tool_keeps_block_order(self):
        frames = [chat({"reasoning_content": "before"}),
                  chat({"tool_calls": [{"index": 0, "id": "a", "type": "function", "function": {"name": "one", "arguments": '{}'}}]}),
                  chat({"reasoning_content": "after"}), chat({"content": "answer"}),
                  chat({"reasoning_content": "last"}), chat(finish="tool_calls"), "data: [DONE]\n\n"]
        wire = converted_stream("openai", "claude", frames)
        result = claude_message(wire)
        self.assertEqual([b.type for b in result.content], ["thinking", "tool_use", "thinking", "text", "thinking"])
        self.assertEqual([b.thinking for b in result.content if b.type == "thinking"], ["before", "after", "last"])
        self.assertEqual(result.content[1].input, {})
        self.assertEqual(result.content[3].text, "answer")
        self.assert_thinking_signatures(wire)

    def test_claude_passthrough_adds_only_missing_signatures(self):
        for signature in ({}, {"signature": ""}, {"signature": None}):
            with self.subTest(signature=signature):
                frames = source_events("claude")[:1] + [
                    sse({"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "", **signature}}),
                    sse({"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "兼容上游思考"}}),
                    sse({"type": "content_block_stop", "index": 0}), sse({"type": "message_stop"}),
                ]
                wire = converted_stream("claude", "claude", frames)
                result = claude_message(wire)
                self.assertEqual(result.content[0].thinking, "兼容上游思考")
                self.assertTrue(result.content[0].signature)
                self.assert_thinking_signatures(wire)

    def test_claude_signature_in_start_is_preserved(self):
        frames = source_events("claude")[:1] + [
            sse({"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "think", "signature": "original"}}),
            sse({"type": "content_block_stop", "index": 0}), sse({"type": "message_stop"}),
        ]
        self.assertEqual(converted_stream("claude", "claude", frames), "".join(frames))

    def test_failure_during_thinking_does_not_synthesize_completion(self):
        state = StreamState("openai", "claude")
        partial = state.feed(chat({"reasoning_content": "partial"}))
        with self.assertRaises(StreamProtocolError):
            state.feed(sse({"error": {"message": "failed"}}, named=False))
        self.assertFalse(state.finished)
        self.assertNotIn('"type": "signature_delta"', partial)
        self.assertNotIn('"type": "message_stop"', partial)


class ToolConversionTests(unittest.TestCase):
    def setUp(self):
        self.body = {"model": "public", "tools": [{"type": "function", "function": {
            "name": "weather", "description": "weather", "parameters": {"type": "object"}}}],
            "tool_choice": {"type": "function", "function": {"name": "weather"}},
            "messages": [{"role": "user", "content": "hi"},
                         {"role": "assistant", "content": None, "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "weather", "arguments": '{"city":"上海"}'}}]},
                         {"role": "tool", "tool_call_id": "call-1", "content": "sunny"}]}

    def test_tool_definitions_and_history_round_trip_all_protocols(self):
        for protocol in ("claude", "responses"):
            with self.subTest(protocol=protocol):
                request = transform_request_body(self.body, "openai", protocol)
                if protocol == "claude":
                    self.assertIn("input_schema", request["tools"][0])
                    self.assertEqual(request["messages"][-1]["content"][0]["tool_use_id"], "call-1")
                else:
                    self.assertEqual(request["tools"][0]["name"], "weather")
                    self.assertEqual(request["input"][-1]["type"], "function_call_output")
                restored = transform_request_body(request, protocol, "openai")
                self.assertEqual(restored["tools"], self.body["tools"])
                self.assertEqual(restored["tool_choice"], self.body["tool_choice"])
                self.assertEqual(restored["messages"][-1], self.body["messages"][-1])
                call = restored["messages"][-2]["tool_calls"][0]
                self.assertEqual(call["id"], "call-1")
                self.assertEqual(json.loads(call["function"]["arguments"]), {"city": "上海"})

    def test_non_streaming_tools_and_stop_reason_round_trip(self):
        source = {"id": "answer", "model": "public", "choices": [{"message": self.body["messages"][1], "finish_reason": "tool_calls"}],
                  "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}}
        for protocol in ("claude", "responses"):
            with self.subTest(protocol=protocol):
                converted = transform_response_body(source, "openai", protocol, {})
                restored = transform_response_body(converted, protocol, "openai", {})
                self.assertEqual(restored["choices"][0]["finish_reason"], "tool_calls")
                self.assertEqual(restored["choices"][0]["message"]["tool_calls"][0]["id"], "call-1")
                self.assertEqual(restored["usage"]["total_tokens"], 18)

    def test_unrepresentable_native_tools_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Provider-native"):
            transform_request_body({"model": "m", "input": "hi", "tools": [{"type": "web_search"}]}, "responses", "claude")

    def test_nonstream_claude_responses_content_order(self):
        source = {"id": "answer", "model": "public", "stop_reason": "tool_use", "content": [
            {"type": "thinking", "thinking": "think", "signature": "opaque"},
            {"type": "tool_use", "id": "a", "name": "one", "input": {"n": 1}},
            {"type": "text", "text": "after tool"},
        ]}
        response = transform_response_body(source, "claude", "responses", {})
        self.assertEqual([item["type"] for item in response["output"]], ["reasoning", "function_call", "message"])
        restored = transform_response_body(response, "responses", "claude", {})
        self.assertEqual([item["type"] for item in restored["content"]], ["thinking", "tool_use", "text"])
        self.assertEqual(restored["content"][0]["thinking"], "think")
        self.assertTrue(restored["content"][0]["signature"])
        self.assertEqual(restored["content"][1]["input"], {"n": 1})
        self.assertEqual(restored["content"][2]["text"], "after tool")

    def test_claude_responses_direct_tool_history_conversion(self):
        for source, target in (("claude", "responses"), ("responses", "claude")):
            with self.subTest(source=source, target=target):
                body = transform_request_body(self.body, "openai", source)
                converted = transform_request_body(body, source, target)
                restored = transform_request_body(converted, target, "openai")
                self.assertEqual(restored["tools"], self.body["tools"])
                self.assertEqual(restored["messages"][-1], self.body["messages"][-1])
                self.assertEqual(restored["messages"][-2]["tool_calls"][0]["id"], "call-1")

    def test_nonstream_reasoning_is_separate_from_answer(self):
        cases = [("openai", {"choices": [{"message": {field: "思考", "content": "答案"}}]})
                 for field in ("reasoning_content", "reasoning")]
        for field, kind in (("summary", "summary_text"), ("content", "reasoning_text")):
            cases.append(("responses", {"output": [
                {"type": "reasoning", field: [{"type": kind, "text": "思考"}]},
                {"type": "message", "content": [{"type": "output_text", "text": "答案"}]},
            ]}))
        for source, body in cases:
            with self.subTest(source=source, body=body):
                result = transform_response_body(body, source, "claude", {})
                with Anthropic(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, json=result),
                ))) as client:
                    message = client.messages.create(model="public", max_tokens=100, messages=[])
                self.assertEqual([b.type for b in message.content], ["thinking", "text"])
                self.assertEqual(message.content[0].thinking, "思考")
                self.assertTrue(message.content[0].signature)
                self.assertEqual(message.content[1].text, "答案")

    def test_nonstream_claude_preserves_existing_and_fills_missing_signatures(self):
        body = {"content": [
            {"type": "thinking", "thinking": "first", "signature": "original"},
            {"type": "thinking", "thinking": "second"},
            {"type": "text", "text": "answer"},
            {"type": "redacted_thinking", "data": "opaque"},
        ]}
        original = json.dumps(body)
        result = transform_response_body(body, "claude", "claude", {})
        self.assertEqual(result["content"][0], body["content"][0])
        self.assertTrue(result["content"][1]["signature"])
        self.assertEqual(result["content"][2:], body["content"][2:])
        self.assertEqual(json.dumps(body), original)
