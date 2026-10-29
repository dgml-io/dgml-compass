"""dgr: the reasoning-and-provenance benchmark, DGML vs PDF markdown. Run it from reasoning/.

  offline, no key, no model call
    dgr reproduce [--tests]      build the renderings, then every table of the README, both splits
    dgr renderings [dgml|markdown]   build the renderings from data/ (scripts/build_renderings.sh)
    dgr report [--split S] [--markdown]   accuracy and tokens per row (report.py)
    dgr provenance [--split S]   traceable citations per row (provenance.py)
    dgr figure                   redraw figures/accuracy_traceable.svg (make_figure.py)

  paid: calls the model
    dgr run                      list the recorded experiments (configs/experiments.json)
    dgr run <experiment> --yes [args]   run one with exactly its recorded parameters
    dgr answer [args]            full read, under the parameters already in the environment (run.py)
    dgr navigate [args]          DGML navigation, likewise (navigate.py)

`dgr <command> -h` shows a command's own options.
"""
import importlib
import importlib.util
import json
import os
import shlex
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXPERIMENTS = os.path.join(ROOT, 'configs', 'experiments.json')

# command -> module of this package whose main() it runs, unchanged
MODULES = {
    'report': 'report',
    'provenance': 'provenance',
    'figure': 'make_figure',
    'answer': 'run',
    'navigate': 'navigate',
}


def _is_run_parameter(name):
    """What a recorded experiment sets: cleared first, so nothing left in the shell changes a run.
    The endpoint and the key (LLM_API_BASE, LLM_API_KEY, AZURE_*/OPENAI_*/... keys) are kept."""
    if name in ('LLM_API_BASE', 'LLM_API_KEY'):
        return False
    return name.startswith(('LLM_', 'BENCH_', 'TR_')) or name in (
        'TOKEN_SAFETY', 'WORDS_PER_TOKEN', 'AZURE_API_VERSION', 'AZURE_MAX_TOKENS_FIELD')


def _dotenv(path):
    """KEY=value lines of reasoning/.env; an empty value (a template placeholder) is skipped."""
    out = {}
    if not os.path.isfile(path):
        return out
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.removeprefix('export ').partition('=')
        value = value.split(' #', 1)[0].strip()
        if value.startswith('#'):
            value = ''
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '\'"':
            value = value[1:-1]
        if key.strip() and value:
            out[key.strip()] = value
    return out


def _module(command, args):
    """The module's own main(), as `python -m` would run it: its argv, and an exit message printed."""
    sys.argv = [f'dgr {command}', *args]
    try:
        importlib.import_module(f'dgml_reasoning.{MODULES[command]}').main()
    except SystemExit as e:
        if e.code is None or isinstance(e.code, int):
            return e.code or 0
        print(e.code, file=sys.stderr)
        return 1
    return 0


def run(args):
    cfg = json.load(open(EXPERIMENTS))
    if not args or args[0].startswith('-'):
        for name, e in cfg['experiments'].items():
            print(f'{name:40} {e.get("_desc", "")}')
        print('\nusage: dgr run <experiment> --yes [args]   (paid; extra args override the recorded ones)',
              file=sys.stderr)
        return 2
    name, rest = args[0], list(args[1:])
    if name not in cfg['experiments']:
        print(f'unknown experiment: {name}\nknown: {" ".join(cfg["experiments"])}', file=sys.stderr)
        return 3
    yes = '--yes' in rest
    rest = [a for a in rest if a != '--yes']
    e = cfg['experiments'][name]
    record = {k: v for k, v in cfg['backends'][e['backend']].items() if not k.startswith('_')}
    record.update({k: v for k, v in e.get('env', {}).items() if not k.startswith('_')})
    env = {**_dotenv(os.path.join(ROOT, '.env')), **os.environ}   # the shell beats .env
    env = {k: v for k, v in env.items() if not _is_run_parameter(k)}
    env.update({k: str(v) for k, v in record.items()})
    argv = [*e['args'], *rest]
    print(f'experiment {name}: dgr {e["command"]} {shlex.join(argv)} | model {env["LLM_MODEL"]} | client '
          f'{env["LLM_CLIENT"]} | effort {env.get("LLM_REASONING_EFFORT", "")!r} | temperature '
          f'{env["LLM_TEMPERATURE"]} | tokenizer {env.get("LLM_TOKENIZER", "default")}', file=sys.stderr)
    if not yes:
        print('paid: this calls the model; add --yes to run it', file=sys.stderr)
        return 1
    if env['LLM_CLIENT'] == 'litellm' and importlib.util.find_spec('litellm') is None:
        print('this backend uses litellm: uv sync --extra litellm', file=sys.stderr)
        return 1
    module = MODULES[e['command']]
    return subprocess.call([sys.executable, '-u', '-m', f'dgml_reasoning.{module}', *argv], env=env, cwd=ROOT)


def renderings(args):
    return subprocess.call(['bash', os.path.join(ROOT, 'scripts', 'build_renderings.sh'), *args], cwd=ROOT)


def reproduce(args):
    print('=== building the renderings from data/docs/dgml and data/pdf (first run: a few minutes)', flush=True)
    if code := renderings([]):
        return code
    for split in ('dev', 'test'):
        print(f'\n=== accuracy and tokens, {split} split', flush=True)
        if code := _module('report', ['--split', split]):
            return code
        print(f'\n=== traceable citations, {split} split', flush=True)
        if code := _module('provenance', ['--split', split]):
            return code
    if '--tests' in args:
        print('\n=== tests', flush=True)
        return subprocess.call([sys.executable, '-m', 'pytest', '-q', 'tests'], cwd=ROOT)
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0 if argv else 2
    command, args = argv[0], argv[1:]
    if command in MODULES:
        return _module(command, args)
    commands = {'run': run, 'renderings': renderings, 'reproduce': reproduce}
    if command not in commands:
        print(f'unknown command: {command}\n{__doc__}', file=sys.stderr)
        return 2
    return commands[command](args)


if __name__ == '__main__':
    sys.exit(main())
