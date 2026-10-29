"""configs/experiments.json is the protocol: every run names a recorded parameter set, every shipped
condition has the experiment that produced it, and the scripts refuse to run under no model at all."""
import json
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
REF = os.path.join(ROOT, 'results', 'reference', 'azure-deepseek-v4-flash-0731')
CFG = json.load(open(os.path.join(ROOT, 'configs', 'experiments.json')))


def test_every_experiment_is_complete():
    for name, e in CFG['experiments'].items():
        assert e['backend'] in CFG['backends'], name
        assert e['command'] in ('answer', 'navigate'), (name, e['command'])
        b = CFG['backends'][e['backend']]
        for k in ('LLM_MODEL', 'LLM_CLIENT', 'LLM_REASONING_EFFORT', 'LLM_TEMPERATURE', 'LLM_MAX_TOKENS'):
            assert k in b, (name, k)


def _condition(e):
    env = e.get('env', {})
    if env.get('BENCH_CONDITION'):
        return env['BENCH_CONDITION']
    fmt = e['args'][e['args'].index('--format') + 1]
    return fmt + (f"@{env['BENCH_CONDITION_SUFFIX']}" if env.get('BENCH_CONDITION_SUFFIX') else '')


def test_every_shipped_condition_has_its_experiment():
    made = {(_condition(e), e['args'][e['args'].index('--split') + 1]) for e in CFG['experiments'].values()}
    q = {x['id']: x.get('split', 'dev') for x in json.load(open(os.path.join(ROOT, 'data', 'questions.json')))['questions']}
    for cond in os.listdir(REF):
        for split in {q[f[:-5]] for f in os.listdir(os.path.join(REF, cond))}:
            assert (cond, split) in made, (cond, split)


def test_backend_matches_the_shipped_answers():
    b = CFG['backends']['deepseek-azure']
    d = os.path.join(REF, 'dgml')
    j = json.load(open(os.path.join(d, sorted(os.listdir(d))[0])))
    assert b['LLM_MODEL'].endswith(j['model'])
    assert b['LLM_REASONING_EFFORT'] == j['reasoning_effort']
    assert float(b['LLM_TEMPERATURE']) == float(j['temperature'])


def test_run_refuses_without_a_model():
    env = {k: v for k, v in os.environ.items() if not k.startswith('LLM_')}
    r = subprocess.run([sys.executable, '-m', 'dgml_reasoning.run', '--limit', '1'],
                       capture_output=True, text=True, env=env, cwd=ROOT)
    assert r.returncode != 0 and 'dgr run' in (r.stdout + r.stderr)


def test_launcher_refuses_an_unknown_experiment():
    r = subprocess.run([sys.executable, '-m', 'dgml_reasoning.cli', 'run', 'no_such_experiment'], capture_output=True,
                       text=True, cwd=ROOT)
    assert r.returncode != 0 and 'unknown experiment: no_such_experiment' in r.stderr


def test_every_backend_pins_its_tokenizer():
    for name, b in CFG['backends'].items():
        assert b.get('LLM_TOKENIZER', '').startswith('hf:'), name


def test_dgr_prints_why_a_command_stops():
    env = {k: v for k, v in os.environ.items() if not k.startswith('LLM_')}
    r = subprocess.run([sys.executable, '-m', 'dgml_reasoning.cli', 'answer', '--limit', '1'],
                       capture_output=True, text=True, env=env, cwd=ROOT)
    assert r.returncode == 1 and 'no model' in r.stderr


def test_dgr_run_takes_the_experiment_first():
    r = subprocess.run([sys.executable, '-m', 'dgml_reasoning.cli', 'run', '--limit', '3', 'dev_dgml', '--yes'],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 2 and 'usage: dgr run <experiment>' in r.stderr and 'experiment dev_dgml' not in r.stderr
