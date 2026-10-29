"""One chat() for every model API.

Two clients, same return shape (the OpenAI chat-completion dict), so nothing
else in the benchmark cares which one is in use:

  litellm  default when installed. Any provider litellm knows -- Azure,
           OpenAI, Anthropic, Gemini, Bedrock, Ollama, vLLM, ... -- selected by
           the LLM_MODEL string (see config.py).
  raw      stdlib only, no dependencies. Azure OpenAI deployments or any
           OpenAI-compatible /v1 endpoint. LLM_CLIENT=raw forces it.

Retry policy is the one the reference runs used: a 429 is a token-per-minute
quota, so it waits for the window to roll over (at least a minute) instead of
burning its retries inside the same blocked minute; bad requests and auth
errors are not retried; everything else (server errors included) backs off and tries again.

The answer is the FIRST <answer>...</answer> of the visible reply (no shipped reply has more than one).
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request

from dgml_reasoning import config as C

THINK = re.compile(r'<think>(.*?)</think>', re.S | re.I)
ANSWER = re.compile(r'<answer>(.*?)</answer>', re.S | re.I)


def _pick_client():
    if C.CLIENT == 'raw':
        return 'raw'
    try:
        import litellm  # noqa: F401
        return 'litellm'
    except ImportError:
        if C.CLIENT == 'litellm':
            sys.exit('LLM_CLIENT=litellm but litellm is not installed: pip install litellm')
        return 'raw'


CLIENT = _pick_client()


def _payload(messages, kw):
    p = dict(messages=messages, max_tokens=kw.pop('max_tokens', C.MAX_TOKENS))
    t = kw.pop('temperature', C.TEMPERATURE)
    if t is not None:  # None: the backend leaves sampling at the model's default
        p['temperature'] = t
    top_p = kw.pop('top_p', C.TOP_P)
    if top_p is not None:
        p['top_p'] = top_p
    # Default from config rather than requiring every caller to pass it: a
    # caller that forgot once produced no-reasoning runs reported as reasoning
    # runs. An explicit kwarg still wins; an empty value is dropped below.
    kw.setdefault('reasoning_effort', C.REASONING_EFFORT)
    for k, v in list(kw.items()):
        if v in (None, ''):
            kw.pop(k)
    p.update(kw)
    return p


# --- litellm -----------------------------------------------------------------
def _chat_litellm(payload):
    import litellm
    # A provider that does not take a parameter (reasoning_effort on a
    # non-reasoning model, say) gets the call without it rather than an error.
    litellm.drop_params = True
    litellm.suppress_debug_info = True
    kw = dict(model=C.MODEL, timeout=C.REQUEST_TIMEOUT, **payload)
    if C.API_BASE:
        kw['api_base'] = C.API_BASE
    if C.API_KEY:
        kw['api_key'] = C.API_KEY
    resp = litellm.completion(**kw)
    return resp.model_dump() if hasattr(resp, 'model_dump') else json.loads(resp.json())


def _litellm_classify(e):
    """-> 'quota' | 'fatal' | 'retry' for a litellm exception."""
    import litellm
    if isinstance(e, litellm.RateLimitError):
        return 'quota'
    fatal = tuple(getattr(litellm, n) for n in
                  ('AuthenticationError', 'BadRequestError', 'NotFoundError',
                   'PermissionDeniedError', 'UnsupportedParamsError')
                  if hasattr(litellm, n))
    return 'fatal' if isinstance(e, fatal) else 'retry'


# --- raw (stdlib) ------------------------------------------------------------
def _chat_raw(payload):
    url, headers, send_model = C.raw_endpoint()
    if send_model:
        payload['model'] = C.RAW_MODEL
    if C.PROVIDER == 'azure' and C.AZURE_MAX_TOKENS_FIELD != 'max_tokens':
        payload[C.AZURE_MAX_TOKENS_FIELD] = payload.pop('max_tokens')
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=C.REQUEST_TIMEOUT) as r:
        return json.loads(r.read())


def _raw_classify(e):
    if not isinstance(e, urllib.error.HTTPError):
        return 'retry', None
    body = e.read().decode('utf-8', 'replace')[:400]
    if e.code == 429:
        try:
            wait = int(e.headers.get('Retry-After') or 0)
        except (TypeError, ValueError):
            wait = 0
        return 'quota', (wait, body)
    # Azure returns 500 rate_limiting_lookup_failed when its own rate-limit
    # service is unreachable -- transient infrastructure, fixes itself.
    if e.code == 500 and 'rate_limiting_lookup_failed' in body:
        return 'retry', body
    if e.code in (400, 401, 403, 404, 422):
        return 'fatal', body
    return 'retry', body


# --- public ------------------------------------------------------------------
def chat(messages, retries=3, **kw):
    """Chat completion as an OpenAI-shaped dict, plus `_elapsed_s`."""
    payload = _payload(messages, kw)
    last = None
    for a in range(retries):
        t0 = time.time()
        try:
            d = (_chat_litellm if CLIENT == 'litellm' else _chat_raw)(dict(payload))
            d['_elapsed_s'] = round(time.time() - t0, 2)
            return d
        except Exception as e:
            if CLIENT == 'litellm':
                kind, detail = _litellm_classify(e), ''
                wait = 0
            else:
                kind, detail = _raw_classify(e)
                wait = detail[0] if isinstance(detail, tuple) else 0
            last = f'{type(e).__name__}: {str(e)[:300]}'
            if kind == 'quota':
                time.sleep(max(wait, 60) + 5 * a)
                continue
            if kind == 'fatal':
                break
        if a < retries - 1:
            time.sleep(2 * (a + 1))
    raise RuntimeError(f'chat failed after {retries} attempts ({CLIENT}, {C.MODEL}): {last}')


def split_output(resp):
    """-> (answer, reasoning, raw_content). Handles servers that return the
    reasoning trace as a separate field and ones that inline <think> blocks."""
    msg = (resp.get('choices') or [{}])[0].get('message') or {}
    raw = msg.get('content') or ''
    reasoning = msg.get('reasoning_content') or msg.get('reasoning') or ''
    if not reasoning:
        m = THINK.search(raw)
        if m:
            reasoning = m.group(1).strip()
    visible = THINK.sub('', raw).strip()
    m = ANSWER.search(visible) or ANSWER.search(raw)
    answer = m.group(1).strip() if m else None
    return answer, reasoning.strip(), raw


def endpoint_label():
    """The endpoint the active client will call -- recorded in every answer
    file as provenance. Named by provider and deployment, never by host: the
    host of an Azure resource or a private server is not a reader's business."""
    if C.PROVIDER == 'azure':
        return f'Azure OpenAI deployment {C.RAW_MODEL}'
    if CLIENT == 'raw':
        return C.raw_endpoint()[0].split('/chat/completions')[0]
    return C.active_api_base()


def smoke_test():
    """One tiny call, so a misconfigured endpoint fails here and not 40 minutes in."""
    print(f'client   : {CLIENT}')
    print(f'model    : {C.MODEL}   -> answers in results/reference/{C.MODEL_SLUG}/')
    print(f'endpoint : {endpoint_label()}')
    print(f'reasoning: {C.REASONING_EFFORT or "(not sent)"}   max_tokens={C.MAX_TOKENS}'
          f'   temperature={C.TEMPERATURE}')
    r = chat([{'role': 'user', 'content': 'Reply with exactly: PONG'}], max_tokens=64)
    a, think, raw = split_output(r)
    print(f'reply    : {raw[:120]!r}  ({r.get("_elapsed_s")}s)')
    print(f'usage    : {r.get("usage")}')


if __name__ == '__main__':
    smoke_test()
