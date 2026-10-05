"""Runner provenance/persistence tests; no historical market dataset is read."""

import json
import subprocess
from dataclasses import asdict
from pathlib import Path
import sys

import pytest

from agi_style_forex_bot_mt5.backtesting.backtester import CostModel
from agi_style_forex_bot_mt5.core.instruments import InstrumentSpec
from agi_style_forex_bot_mt5.core.workspace import workspace_paths
from agi_style_forex_bot_mt5.research.experiment_plan import ExperimentPlan, ResearchManagement
from agi_style_forex_bot_mt5.research import predeclared_runner as runner

from test_shared_strategy_features import _bars


@pytest.fixture
def research_inputs(tmp_path):
    bars = _bars(320)
    bars.to_csv(tmp_path/'bars.csv', index=False)
    spec = InstrumentSpec('EURUSD', 'EURUSD', 'EURUSD.synthetic', 5, .00001, .00001,
        1., 100000., .01, 100., .01, 10, 5, 'EUR', 'USD', 'synthetic fixture')
    payload = {'data_role': 'SYNTHETIC_FIXTURE', 'denomination_currency': 'USD',
        'lot': .1, 'initial_balance': 10000., 'random_seed': 1729,
        'management': asdict(ResearchManagement(max_holding_bars=5)),
        'datasets': {'EURUSD': {'path': 'bars.csv', 'provider': 'synthetic test generator',
            'quality_report': {'source_authenticity': 'SYNTHETIC'},
            'tick_value_currency': 'USD', 'tick_value_status': 'ASSUMED',
            'instrument': asdict(spec), 'cost_model': asdict(CostModel(spread_points=5.,
                slippage_points=.25, commission_per_lot_round_turn=3.)),
            'cost_provenance': {'source': 'synthetic explicit fixture', 'assumptions': ['not broker observations'],
                'commission_currency': 'USD', 'swap_mode': 'NOT_MODELED', 'status': 'ASSUMED'}}}}
    path = tmp_path/'study.json'
    path.write_text(json.dumps(payload, allow_nan=False), encoding='utf-8')
    return path


def prepared(path):
    plan, loaded = runner.prepare_study_plan(path)
    return plan, loaded['datasets'], loaded['dataset_paths']


def execute(path, output):
    plan, frames, paths = prepared(path)
    return runner.run_predeclared_research(plan, frames, dataset_paths=paths, output_dir=output)


def test_persists_before_real_evaluation_and_records_every_cell(research_inputs, tmp_path, monkeypatch):
    output = tmp_path/'run'
    original = runner.evaluate_trend_pullback
    seen = []
    def observe(plan, frame, **kwargs):
        assert (output/'plan.json').read_text(encoding='utf-8') == plan.canonical_json
        assert runner.strict_json_loads((output/'manifest.json').read_text())['status'] == 'PREDECLARED'
        assert (output/'inputs.json').is_file()
        journal = [json.loads(line) for line in (output/'journal.jsonl').read_text().splitlines()]
        assert journal[-1]['event_type'] == 'EVALUATION_STARTED'
        value = original(plan, frame, **kwargs)
        seen.append((kwargs, value.to_dict()))
        return value
    monkeypatch.setattr(runner, 'evaluate_trend_pullback', observe)
    result = execute(research_inputs, output).to_dict()
    assert result['status'] == 'COMPLETED'
    assert len(seen) == result['cell_count'] == 9
    assert len({cell['cell_id'] for cell in result['cells']}) == 9
    for cell, (identity, actual) in zip(result['cells'], seen):
        assert cell['split'] == identity['split']
        assert cell['hypothesis_id'] == identity['hypothesis_id']
        assert cell['metrics'] == actual['metrics']
        assert cell['evaluation_id'] == actual['evaluation_id']
        assert (output/cell['decisions_path']).is_file()
        assert (output/cell['trades_path']).is_file()
    assert result['raw_source_hash_verified'] is True
    assert result['selected_hypothesis_id'] is None
    assert result['selection_policy'] == 'NONE_COMPARE_ALL'
    assert result['final_holdout'] == 'NOT_AVAILABLE'
    assert result['baselines'] == result['walk_forward'] == 'NOT_EVALUATED'
    assert result['promotion_eligible'] is result['execution_authorized'] is False
    # This fixture has no eligible train signal but real completed trades in
    # development_test; equal metrics copied from train cannot pass.
    assert all(cell['metrics']['trades_total'] == 0 for cell in result['cells'] if cell['split'] == 'train')
    assert any(cell['metrics']['trades_total'] > 0 for cell in result['cells'] if cell['split'] == 'development_test')


def test_identical_runs_are_reproducible_and_never_overwrite(research_inputs, tmp_path):
    one = execute(research_inputs, tmp_path/'one').to_dict()
    two = execute(research_inputs, tmp_path/'two').to_dict()
    assert one == two
    assert (tmp_path/'one/manifest.json').read_bytes() == (tmp_path/'two/manifest.json').read_bytes()
    before = (tmp_path/'one/summary.json').read_bytes()
    with pytest.raises(FileExistsError):
        execute(research_inputs, tmp_path/'one')
    assert (tmp_path/'one/summary.json').read_bytes() == before


@pytest.mark.parametrize('change', ['source', 'frame', 'raw_file'])
def test_changed_binding_rejects_before_evaluation_or_output(research_inputs, tmp_path, monkeypatch, change):
    plan, frames, paths = prepared(research_inputs)
    if change == 'source':
        payload = plan.to_dict()
        payload['source_sha256'] = 'a'*64
        plan = ExperimentPlan.from_json(json.dumps(payload))
    elif change == 'frame':
        frames['EURUSD'].loc[0, 'volume'] += 1
    else:
        paths['EURUSD'].write_text(paths['EURUSD'].read_text()+'\n')
    monkeypatch.setattr(runner, 'evaluate_trend_pullback', lambda *args, **kwargs: pytest.fail('unbound evaluator ran'))
    with pytest.raises(runner.ResearchBindingError):
        runner.run_predeclared_research(plan, frames, dataset_paths=paths, output_dir=tmp_path/'rejected')
    assert not (tmp_path/'rejected').exists()


def test_programmatic_frames_do_not_claim_raw_source_verification(research_inputs, tmp_path):
    plan, frames, _ = prepared(research_inputs)
    result = runner.run_predeclared_research(plan, frames, output_dir=tmp_path/'run').to_dict()
    assert result['raw_source_hash_verified'] is False
    inputs = json.loads((tmp_path/'run/inputs.json').read_text())
    assert inputs['raw_source_verification'] == 'NOT_AVAILABLE'


def test_failure_is_recorded_per_cell_without_copying_training_metrics(research_inputs, tmp_path, monkeypatch):
    original = runner.evaluate_trend_pullback
    def fail_validation(plan, frame, **kwargs):
        if kwargs['split'] == 'validation':
            raise RuntimeError('synthetic evaluation failure')
        return original(plan, frame, **kwargs)
    monkeypatch.setattr(runner, 'evaluate_trend_pullback', fail_validation)
    result = execute(research_inputs, tmp_path/'run').to_dict()
    assert result['status'] == 'INCOMPLETE'
    for cell in result['cells']:
        if cell['split'] == 'validation':
            assert cell['status'] == 'FAILED' and cell['metrics'] is None
        else:
            assert cell['status'] != 'FAILED' and cell['metrics'] is not None


def test_input_mutation_after_first_evaluation_stops_remaining_cells(research_inputs, tmp_path, monkeypatch):
    plan, frames, paths = prepared(research_inputs)
    original = runner.evaluate_trend_pullback
    calls = []
    def mutate(plan, frame, **kwargs):
        calls.append(kwargs)
        result = original(plan, frame, **kwargs)
        frames['EURUSD'].loc[0, 'volume'] += 1
        return result
    monkeypatch.setattr(runner, 'evaluate_trend_pullback', mutate)
    result = runner.run_predeclared_research(plan, frames, dataset_paths=paths, output_dir=tmp_path/'run').to_dict()
    assert len(calls) == 1
    assert result['cells'][0]['status'] == 'FAILED'
    assert all(cell['status'] == 'NOT_EVALUATED' for cell in result['cells'][1:])
    assert all(cell['metrics'] is None for cell in result['cells'])


def test_last_evaluation_cannot_replace_the_persisted_plan(research_inputs, tmp_path, monkeypatch):
    original = runner.evaluate_trend_pullback
    calls = []
    def mutate_last(plan, frame, **kwargs):
        value = original(plan, frame, **kwargs)
        calls.append(kwargs)
        if len(calls) == 9:
            (tmp_path/'run/plan.json').write_text('{}', encoding='utf-8')
        return value
    monkeypatch.setattr(runner, 'evaluate_trend_pullback', mutate_last)
    result = execute(research_inputs, tmp_path/'run').to_dict()
    assert result['status'] == 'INCOMPLETE'
    assert result['cells'][-1]['reject_code'] == 'PERSISTED_PLAN_CHANGED'
    journal = [json.loads(row) for row in (tmp_path/'run/journal.jsonl').read_text().splitlines()]
    assert sum(item['event_type'] == 'EVALUATION_COMPLETED' for item in journal) == 8


def test_cell_write_failure_never_records_completion(research_inputs, tmp_path, monkeypatch):
    original = runner._write_json_new
    def fail_cell(path, payload):
        if path.parent.name == 'cells':
            raise OSError('synthetic result persistence failure')
        return original(path, payload)
    monkeypatch.setattr(runner, '_write_json_new', fail_cell)
    with pytest.raises(OSError):
        execute(research_inputs, tmp_path/'run')
    assert not (tmp_path/'run/summary.json').exists()
    journal = [json.loads(row) for row in (tmp_path/'run/journal.jsonl').read_text().splitlines()]
    assert journal[-1]['event_type'] == 'EVALUATION_STARTED'
    assert all(item['event_type'] != 'EVALUATION_COMPLETED' for item in journal)


@pytest.mark.parametrize('text', ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '{"a":1e999}'])
def test_strict_json_rejects_ambiguous_and_nonfinite_inputs(text):
    with pytest.raises(ValueError):
        runner.strict_json_loads(text)


def test_cli_plan_and_run_are_offline_and_cwd_independent(research_inputs, tmp_path):
    project = workspace_paths().project_root
    script = project/'scripts/run_predeclared_research.py'
    prefix = [sys.executable, '-B', str(script), '--source-root', str(project)]
    plan_path = tmp_path/'frozen-plan.json'
    first = subprocess.run(prefix+['plan', '--inputs', str(research_inputs), '--output', str(plan_path)],
        cwd=tmp_path, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stdout+first.stderr
    assert json.loads(first.stdout)['evaluations_performed'] == 0
    second = subprocess.run(prefix+['run', '--inputs', str(research_inputs), '--plan', str(plan_path),
        '--output', str(tmp_path/'cli-run')], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert second.returncode == 0, second.stdout+second.stderr
    assert json.loads(second.stdout)['cell_count'] == 9
    assert json.loads(second.stdout)['execution_authorized'] is False
