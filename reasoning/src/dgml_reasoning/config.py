"""Paths, renderings and model settings.

Everything lives under this folder (reasoning/ in dgml-compass). The model and its parameters come from the environment,
which `dgr run` sets from configs/experiments.json (no default model: an answer can never be
produced under an unrecorded setting):

  LLM_MODEL              provider/model, e.g. azure/DeepSeek-V4-Flash-0731 (the reference runs)
  LLM_CLIENT             raw (stdlib: Azure OpenAI or any OpenAI-compatible endpoint) | litellm
  LLM_API_BASE, LLM_API_KEY   an OpenAI-compatible endpoint; Azure reads AZURE_OPENAI_ENDPOINT /
                         AZURE_OPENAI_API_KEY (or AZURE_API_BASE / AZURE_API_KEY), see .env.example
  LLM_REASONING_EFFORT   '' (not sent) | low | medium | high
  LLM_TEMPERATURE        default 0.0; '' = not sent
  LLM_TOP_P              sent only when set
  LLM_MAX_TOKENS         completion budget per call (default 8192)
  LLM_MAX_PROMPT_TOKENS  a longer filing keeps its beginning (default 240000)
  LLM_TIMEOUT            seconds per request (default 1800)
  LLM_TOKENIZER          hf:<repo> (default for a DeepSeek model) | words (estimate)
  BENCH_CONDITION_SUFFIX answers go to <format>@<suffix>/ (e.g. "program")
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, 'data')
DOCS = os.path.join(DATA, 'docs')
RESULTS = os.path.join(ROOT, 'results', 'reference')
QUESTIONS = os.path.join(DATA, 'questions.json')
GOLD_COMPUTATIONS = os.path.join(DATA, 'gold_computations.json')
MANIFEST = os.path.join(DATA, 'manifest.json')

# --- renderings: one directory per rendering under data/docs/ -----------------------------
# dgml ships; scripts/build_renderings.sh builds the others from it and from data/pdf/.
FORMATS = {'dgml': dict(dir=os.path.join(DOCS, 'dgml'), ext='.dgml.xml', label='DGML')}
for _name in sorted(os.listdir(DOCS)) if os.path.isdir(DOCS) else []:
    if _name in FORMATS or _name.endswith('_outline') or not os.path.isdir(os.path.join(DOCS, _name)):
        continue
    if _name.startswith('dgml') and '_compact' in _name:
        FORMATS[_name] = dict(dir=os.path.join(DOCS, _name), ext='.dgml.txt', label='DGML compact')
    elif _name.startswith('dgml'):
        FORMATS[_name] = dict(dir=os.path.join(DOCS, _name), ext='.dgml.xml', label=f'DGML ({_name})')
    elif _name.startswith('markdown'):
        FORMATS[_name] = dict(dir=os.path.join(DOCS, _name), ext='.md', label=f'markdown ({_name})')


def load_questions(split=None, docs=''):
    """The questions of a split ("dev" or "test"; None or "all" = both), optionally
    only the filings whose key starts with one of the comma-separated prefixes in `docs`."""
    import json
    qs = json.load(open(QUESTIONS))['questions']
    if split and split != 'all':
        qs = [q for q in qs if q.get('split', 'dev') == split]
    if docs:
        pre = tuple(x.strip() for x in docs.split(',') if x.strip())
        qs = [q for q in qs if q['key'].startswith(pre)]
    return qs


def outline_dir(fmt='dgml'):
    """The element outline of a DGML rendering (what DGML navigation reads)."""
    return os.path.join(DOCS, fmt + '_outline')


def doc_path(fmt, key):
    f = FORMATS[fmt]
    return os.path.join(f['dir'], key + f['ext'])


# --- model -------------------------------------------------------------------------------
MODEL = os.environ.get('LLM_MODEL', '').strip()
CLIENT = os.environ.get('LLM_CLIENT', '').strip().lower()
API_BASE = os.environ.get('LLM_API_BASE', '').rstrip('/')
API_KEY = os.environ.get('LLM_API_KEY', '')
MAX_TOKENS = int(os.environ.get('LLM_MAX_TOKENS', 8192))
_T = os.environ.get('LLM_TEMPERATURE', '0.0').strip()
TEMPERATURE = float(_T) if _T else None
_P = os.environ.get('LLM_TOP_P', '').strip()
TOP_P = float(_P) if _P else None
REASONING_EFFORT = os.environ.get('LLM_REASONING_EFFORT', '')
REQUEST_TIMEOUT = int(os.environ.get('LLM_TIMEOUT', 1800))
MAX_PROMPT_TOKENS = int(os.environ.get('LLM_MAX_PROMPT_TOKENS', 240_000))
CONDITION_SUFFIX = os.environ.get('BENCH_CONDITION_SUFFIX', '').strip()

# Token counting: the model's own tokenizer (matches the API's prompt_tokens to within the chat
# template, 4 tokens on DeepSeek-V4-Flash-0731), or a word estimate when it cannot be loaded.
# The one used is recorded in every answer (tokenizer=...).
WORDS_PER_TOKEN = float(os.environ.get('WORDS_PER_TOKEN', 0.379))
# Margin under the prompt budget when cutting a filing (the prompt frame and the estimate's spread);
# kept with the exact tokenizer so the recorded 240k budget means the same.
SAFETY = float(os.environ.get('TOKEN_SAFETY', 0.93))
_TOKENIZER_SPEC = os.environ.get('LLM_TOKENIZER', '').strip() or (
    'hf:deepseek-ai/DeepSeek-V4-Flash-0731' if 'deepseek' in MODEL.lower() else 'words')
_tokenizer = None
TOKENIZER = f'words/{WORDS_PER_TOKEN}'


def _load_tokenizer():
    global _tokenizer, TOKENIZER
    if _tokenizer is not None or not _TOKENIZER_SPEC.startswith('hf:'):
        return _tokenizer
    repo = _TOKENIZER_SPEC[3:]
    try:
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer
        _tokenizer = Tokenizer.from_file(hf_hub_download(repo, 'tokenizer.json'))
        TOKENIZER = repo
    except Exception as e:  # missing package, offline: fall back, say so once
        print(f'[config] tokenizer {repo} unavailable ({type(e).__name__}); using the word estimate', file=sys.stderr)
        _tokenizer = False
    return _tokenizer


_load_tokenizer()   # eager, so TOKENIZER names what this run counts with from the first answer on


def tokens_from_text(text):
    tok = _load_tokenizer()
    if tok:
        return len(tok.encode(text, add_special_tokens=False).ids)
    return int(len(text.split()) / WORDS_PER_TOKEN)


# --- endpoints -----------------------------------------------------------------------------
PROVIDER, _sep, RAW_MODEL = MODEL.partition('/') if '/' in MODEL else ('openai', '', MODEL)
AZURE_API_BASE = (os.environ.get('AZURE_API_BASE') or os.environ.get('AZURE_OPENAI_ENDPOINT', '')).rstrip('/')
AZURE_API_KEY = os.environ.get('AZURE_API_KEY') or os.environ.get('AZURE_OPENAI_API_KEY', '')
AZURE_API_VERSION = os.environ.get('AZURE_API_VERSION') or '2024-10-21'
# Reasoning-era Azure deployments reject max_tokens and want max_completion_tokens.
AZURE_MAX_TOKENS_FIELD = os.environ.get('AZURE_MAX_TOKENS_FIELD', 'max_tokens')


def raw_endpoint():
    """(url, headers, send_model_in_body) for the stdlib client."""
    if PROVIDER == 'azure':
        url = f'{AZURE_API_BASE}/openai/deployments/{RAW_MODEL}/chat/completions?api-version={AZURE_API_VERSION}'
        return url, {'api-key': AZURE_API_KEY, 'Content-Type': 'application/json'}, False
    base = API_BASE or os.environ.get('OPENAI_API_BASE', '').rstrip('/') or 'http://localhost:11434/v1'
    key = API_KEY or os.environ.get('OPENAI_API_KEY', '')
    return base + '/chat/completions', {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}, True


def active_api_base():
    """What the litellm client records as its endpoint."""
    if PROVIDER == 'azure':
        return AZURE_API_BASE
    return API_BASE or os.environ.get('OPENAI_API_BASE', '') or f'({PROVIDER} via litellm)'


# --- results -------------------------------------------------------------------------------
def model_slug(name=None):
    """results/reference/<slug>/ for a model: answers are only comparable within one model."""
    n = (name or MODEL).strip().lower().replace('/', '-').replace(':', '-')
    return re.sub(r'[^a-z0-9._-]+', '-', n).strip('-') or 'unknown-model'


MODEL_SLUG = model_slug()


def answer_path(condition, qid, model=None):
    if CONDITION_SUFFIX and '@' not in condition:
        condition = f'{condition}@{CONDITION_SUFFIX}'
    return os.path.join(RESULTS, model_slug(model), condition, qid + '.json')


def result_models():
    """Model directories that hold results, most answers first."""
    out = []
    for d in sorted(os.listdir(RESULTS)) if os.path.isdir(RESULTS) else []:
        p = os.path.join(RESULTS, d)
        if os.path.isdir(p):
            out.append((sum(len(os.listdir(os.path.join(p, c))) for c in os.listdir(p)
                            if os.path.isdir(os.path.join(p, c))), d))
    return [d for n, d in sorted(out, reverse=True)]
