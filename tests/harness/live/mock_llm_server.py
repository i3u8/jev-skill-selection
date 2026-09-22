#!/usr/bin/env python3
"""Local mock LLM HTTP server for live harness e2e (no real API spend).

Supports:
  - Anthropic Messages API: ``POST /v1/messages`` (+ optional ``/v1/messages/count_tokens``)
  - OpenAI Chat Completions: ``POST /v1/chat/completions``
  - OpenAI Responses API: ``POST /v1/responses`` (JSON or SSE when ``stream=true``)
  - ``GET /v1/models`` / ``GET /health``

Every request body is appended as one JSONL line to ``--log`` (default
``mock_llm_requests.jsonl``) for ordering / soft-inject assertions.

Point hosts at this server with (examples)::

  # Claude Code
  export ANTHROPIC_BASE_URL=http://127.0.0.1:8765
  export ANTHROPIC_API_KEY=sk-mock

  # Codex (Responses API — chat wire_api is retired)
  # in ~/.codex/config.toml:
  #   openai_base_url = "http://127.0.0.1:8765/v1"
  #   OR custom model_provider with base_url + wire_api = "responses"
  export OPENAI_API_KEY=sk-mock

  # Hermes (custom / openai-api provider)
  export OPENAI_BASE_URL=http://127.0.0.1:8765/v1
  export OPENAI_API_KEY=sk-mock
  # and/or config.yaml: model.provider=custom, model.base_url=...

  # OpenCode — prefer opencode.json custom provider with options.baseURL
  # pointing at http://127.0.0.1:8765/v1 (OPENAI_BASE_URL alone is unreliable).

Usage::

  python tests/harness/live/mock_llm_server.py --port 8765 --log /tmp/mock.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ASSISTANT_REPLY = (
    "Mock LLM reply: I saw skills context in the request "
    "(jev-skill-selection keep/drop) if the host injected it. "
    "This is a fixed short answer — no real model was called."
)


def _now() -> float:
    return time.time()


def _extract_roles(body: dict[str, Any]) -> dict[str, Any]:
    """Pull system/developer/user text for logging (best-effort across APIs)."""
    system_parts: list[str] = []
    developer_parts: list[str] = []
    user_parts: list[str] = []

    # Anthropic: system may be str or list of blocks; messages[] with roles
    sys_field = body.get("system")
    if isinstance(sys_field, str):
        system_parts.append(sys_field)
    elif isinstance(sys_field, list):
        for block in sys_field:
            if isinstance(block, dict) and block.get("type") == "text":
                system_parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                system_parts.append(block)

    def _content_to_text(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            bits: list[str] = []
            for part in content:
                if isinstance(part, str):
                    bits.append(part)
                elif isinstance(part, dict):
                    if part.get("type") in ("text", "input_text", "output_text"):
                        bits.append(str(part.get("text", "")))
                    elif "text" in part:
                        bits.append(str(part.get("text", "")))
            return "\n".join(bits)
        if isinstance(content, dict):
            return str(content.get("text", content))
        return str(content)

    for msg in body.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).lower()
        text = _content_to_text(msg.get("content"))
        if role == "system":
            system_parts.append(text)
        elif role in ("developer", "tool"):
            developer_parts.append(text)
        elif role == "user":
            user_parts.append(text)

    # Responses API: instructions + input (str or list of items)
    if isinstance(body.get("instructions"), str):
        system_parts.append(body["instructions"])
    inp = body.get("input")
    if isinstance(inp, str):
        user_parts.append(inp)
    elif isinstance(inp, list):
        for item in inp:
            if isinstance(item, str):
                user_parts.append(item)
            elif isinstance(item, dict):
                role = str(item.get("role", "")).lower()
                text = _content_to_text(item.get("content") or item.get("text"))
                if role in ("system", "developer"):
                    (system_parts if role == "system" else developer_parts).append(text)
                elif role == "user" or item.get("type") in ("message", "input_text"):
                    user_parts.append(text)

    blob = "\n".join(system_parts + developer_parts + user_parts)
    return {
        "system": system_parts,
        "developer": developer_parts,
        "user": user_parts,
        "saw_skills_context": (
            "jev-skill-selection" in blob
            or "KEPT:" in blob
            or "git-ops" in blob
            or "additionalContext" in blob
        ),
        "saw_git_ops": "git-ops" in blob,
        "saw_dropped_pptx": "pptx-author" in blob,
    }


class MockHandler(BaseHTTPRequestHandler):
    server_version = "JevMockLLM/1.0"
    log_path: Path
    lock: threading.Lock

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter
        sys.stderr.write("[mock-llm] " + (fmt % args) + "\n")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            data = {"_raw": raw.decode("utf-8", errors="replace")}
        if not isinstance(data, dict):
            data = {"_non_object": data}
        return data

    def _append_log(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self.lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(line)

    def _send(self, code: int, body: Any, *, content_type: str = "application/json") -> None:
        raw = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def _send_sse(self, events: list[tuple[str, dict[str, Any]]]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        for event, data in events:
            payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
            self.wfile.write(payload.encode("utf-8"))
            self.wfile.flush()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in ("/health", "/v1/health"):
            self._send(200, {"ok": True, "service": "jev-mock-llm"})
            return
        if path in ("/v1/models", "/models"):
            self._send(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": "mock-model", "object": "model", "owned_by": "jev-mock"},
                        {"id": "gpt-4.1-mini", "object": "model", "owned_by": "jev-mock"},
                        {"id": "claude-haiku-4-5-20251001", "object": "model", "owned_by": "jev-mock"},
                    ],
                },
            )
            return
        self._send(404, {"error": {"message": f"unknown path {path}", "type": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        body = self._read_json()
        roles = _extract_roles(body)
        record = {
            "ts": _now(),
            "method": "POST",
            "path": path,
            "model": body.get("model"),
            "stream": bool(body.get("stream")),
            "roles": roles,
            "body": body,
        }
        self._append_log(record)

        if path.endswith("/messages/count_tokens") or path.endswith("/count_tokens"):
            self._send(200, {"input_tokens": 42})
            return

        if path.endswith("/messages"):
            self._handle_anthropic(body)
            return

        if path.endswith("/chat/completions"):
            self._handle_chat(body)
            return

        if path.endswith("/responses"):
            self._handle_responses(body)
            return

        # Some SDKs hit bare /v1
        if path in ("/v1", ""):
            self._send(200, {"ok": True})
            return

        self._send(404, {"error": {"message": f"unknown path {path}", "type": "not_found"}})

    def _handle_anthropic(self, body: dict[str, Any]) -> None:
        model = body.get("model") or "claude-mock"
        reply = ASSISTANT_REPLY
        if body.get("stream"):
            events = [
                (
                    "message_start",
                    {
                        "type": "message_start",
                        "message": {
                            "id": "msg_mock",
                            "type": "message",
                            "role": "assistant",
                            "content": [],
                            "model": model,
                            "stop_reason": None,
                            "usage": {"input_tokens": 10, "output_tokens": 0},
                        },
                    },
                ),
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": ""},
                    },
                ),
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": reply},
                    },
                ),
                (
                    "content_block_stop",
                    {"type": "content_block_stop", "index": 0},
                ),
                (
                    "message_delta",
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": "end_turn"},
                        "usage": {"output_tokens": 20},
                    },
                ),
                ("message_stop", {"type": "message_stop"}),
            ]
            # Anthropic uses data-only SSE without always requiring event: lines;
            # emit both for compatibility.
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for _name, data in events:
                self.wfile.write(f"event: {data['type']}\ndata: {json.dumps(data)}\n\n".encode())
            self.wfile.flush()
            return

        self._send(
            200,
            {
                "id": "msg_mock",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": reply}],
                "model": model,
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 20},
            },
        )

    def _handle_chat(self, body: dict[str, Any]) -> None:
        model = body.get("model") or "mock-model"
        reply = ASSISTANT_REPLY
        if body.get("stream"):
            chunk = {
                "id": "chatcmpl-mock",
                "object": "chat.completion.chunk",
                "created": int(_now()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": reply},
                        "finish_reason": None,
                    }
                ],
            }
            done = {
                "id": "chatcmpl-mock",
                "object": "chat.completion.chunk",
                "created": int(_now()),
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(f"data: {json.dumps(done)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        self._send(
            200,
            {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": int(_now()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": reply},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            },
        )

    def _handle_responses(self, body: dict[str, Any]) -> None:
        model = body.get("model") or "mock-model"
        reply = ASSISTANT_REPLY
        resp_id = "resp_mock"
        msg_id = "msg_mock"
        completed = {
            "id": resp_id,
            "object": "response",
            "created_at": int(_now()),
            "status": "completed",
            "model": model,
            "output": [
                {
                    "type": "message",
                    "id": msg_id,
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": reply}],
                }
            ],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30,
            },
        }
        if body.get("stream"):
            events = [
                (
                    "response.created",
                    {
                        "type": "response.created",
                        "response": {**completed, "status": "in_progress", "output": []},
                    },
                ),
                (
                    "response.output_item.added",
                    {
                        "type": "response.output_item.added",
                        "output_index": 0,
                        "item": {
                            "type": "message",
                            "id": msg_id,
                            "status": "in_progress",
                            "role": "assistant",
                            "content": [],
                        },
                    },
                ),
                (
                    "response.content_part.added",
                    {
                        "type": "response.content_part.added",
                        "item_id": msg_id,
                        "output_index": 0,
                        "content_index": 0,
                        "part": {"type": "output_text", "text": ""},
                    },
                ),
                (
                    "response.output_text.delta",
                    {
                        "type": "response.output_text.delta",
                        "item_id": msg_id,
                        "output_index": 0,
                        "content_index": 0,
                        "delta": reply,
                    },
                ),
                (
                    "response.output_text.done",
                    {
                        "type": "response.output_text.done",
                        "item_id": msg_id,
                        "output_index": 0,
                        "content_index": 0,
                        "text": reply,
                    },
                ),
                (
                    "response.output_item.done",
                    {
                        "type": "response.output_item.done",
                        "output_index": 0,
                        "item": completed["output"][0],
                    },
                ),
                ("response.completed", {"type": "response.completed", "response": completed}),
            ]
            self._send_sse(events)
            return
        self._send(200, completed)


def serve(host: str, port: int, log_path: Path) -> None:
    handler = type(
        "BoundHandler",
        (MockHandler,),
        {"log_path": log_path, "lock": threading.Lock()},
    )
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"jev-mock-llm listening on http://{host}:{port}  log={log_path}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("shutting down", flush=True)
    finally:
        httpd.server_close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default=os.environ.get("JEV_MOCK_LLM_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("JEV_MOCK_LLM_PORT", "8765")))
    p.add_argument(
        "--log",
        default=os.environ.get("JEV_MOCK_LLM_LOG", "mock_llm_requests.jsonl"),
        help="JSONL path for incoming request logs",
    )
    args = p.parse_args(argv)
    log_path = Path(args.log).expanduser().resolve()
    # Truncate previous run
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")
    serve(args.host, args.port, log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
