"""Both model clients, exercised against mocks -- no key, no network.

config.py and llm.py read the environment at import time, so each test sets
its variables and reloads the two modules.
"""
import importlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

REPLY = {"choices": [{"message": {"content": "thinking...<answer>PONG</answer>",
                                  "reasoning_content": "r"}, "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}}

LLM_VARS = ('LLM_CLIENT', 'LLM_MODEL', 'LLM_API_BASE', 'LLM_API_KEY', 'LLM_REASONING_EFFORT',
            'AZURE_API_BASE', 'AZURE_API_KEY', 'AZURE_MAX_TOKENS_FIELD', 'OPENAI_API_KEY', 'OPENAI_API_BASE')


@pytest.fixture
def server():
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            seen.append(dict(path=self.path, headers={k.lower(): v for k, v in self.headers.items()}, body=body))
            out = json.dumps(REPLY).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1], seen
    srv.shutdown()


def _load(monkeypatch, **env):
    for v in LLM_VARS:
        monkeypatch.delenv(v, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from dgml_reasoning import config
    importlib.reload(config)
    from dgml_reasoning import llm
    return importlib.reload(llm), config


def test_raw_openai_compatible(monkeypatch, server):
    port, seen = server
    llm, C = _load(monkeypatch, LLM_CLIENT='raw', LLM_MODEL='openai/test-model',
                   LLM_API_BASE=f'http://127.0.0.1:{port}/v1', LLM_API_KEY='k', LLM_REASONING_EFFORT='low')
    assert llm.CLIENT == 'raw' and C.MODEL_SLUG == 'openai-test-model'
    d = llm.chat([{'role': 'user', 'content': 'ping'}], max_tokens=64)
    assert llm.split_output(d)[0] == 'PONG' and d['_elapsed_s'] >= 0
    req = seen[-1]
    assert req['path'] == '/v1/chat/completions'
    assert req['body']['model'] == 'test-model' and req['body']['reasoning_effort'] == 'low'
    assert req['headers']['authorization'] == 'Bearer k'
    assert llm.endpoint_label() == f'http://127.0.0.1:{port}/v1'


def test_raw_azure_deployment(monkeypatch, server):
    port, seen = server
    llm, C = _load(monkeypatch, LLM_CLIENT='raw', LLM_MODEL='azure/my-deployment',
                   AZURE_API_BASE=f'http://127.0.0.1:{port}', AZURE_API_KEY='azkey',
                   AZURE_MAX_TOKENS_FIELD='max_completion_tokens')
    assert C.MODEL_SLUG == 'azure-my-deployment'
    d = llm.chat([{'role': 'user', 'content': 'ping'}])
    assert llm.split_output(d)[0] == 'PONG'
    req = seen[-1]
    assert req['path'].startswith('/openai/deployments/my-deployment/chat/completions?api-version=')
    assert req['headers']['api-key'] == 'azkey'
    assert 'max_completion_tokens' in req['body'] and 'max_tokens' not in req['body']
    assert 'model' not in req['body']          # Azure names the deployment in the URL


def test_empty_reasoning_effort_is_not_sent(monkeypatch, server):
    port, seen = server
    llm, _ = _load(monkeypatch, LLM_CLIENT='raw', LLM_MODEL='ollama/llama3.1',
                   LLM_API_BASE=f'http://127.0.0.1:{port}/v1')
    llm.chat([{'role': 'user', 'content': 'ping'}])
    assert 'reasoning_effort' not in seen[-1]['body']


def test_split_output_handles_inline_think_blocks():
    from dgml_reasoning import llm
    resp = {'choices': [{'message': {'content': '<think>hmm</think> so <answer>42</answer>'}}]}
    assert llm.split_output(resp) == ('42', 'hmm', '<think>hmm</think> so <answer>42</answer>')
    assert llm.split_output({'choices': [{'message': {'content': 'no tag'}}]})[0] is None


def test_litellm_client(monkeypatch):
    litellm = pytest.importorskip('litellm')
    import functools
    llm, C = _load(monkeypatch, LLM_MODEL='openai/gpt-4o', LLM_API_KEY='sk-test', LLM_REASONING_EFFORT='low')
    assert llm.CLIENT == 'litellm' and C.MODEL_SLUG == 'openai-gpt-4o'
    monkeypatch.setattr(litellm, 'completion',
                        functools.partial(litellm.completion, mock_response='<answer>PONG</answer>'))
    d = llm.chat([{'role': 'user', 'content': 'ping'}])
    assert llm.split_output(d)[0] == 'PONG'
    assert d['usage']['prompt_tokens'] > 0 and '_elapsed_s' in d
