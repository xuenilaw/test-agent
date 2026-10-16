"""Deterministic, spreadsheet-safe audit rows from saved execution evidence."""
import csv
import os
from pathlib import Path

from test_agent.reporting import Report, borderline, human, read_json, readable_item, vision_text

COLUMNS = ('row_id run_id repeat_index case_id case_name case_status designed_outcome outcome_as_designed '
    'step row_type kind_or_action target status reason_code reason expected actual locator_source healed '
    'vision_provider vision_model min_confidence vision_min_selected_probability borderline faults duration_s '
    'screenshot results_json').split()


def cell(value, limit=500):
    text = ' '.join(human(value).split()) if value is not None else ''
    if len(text) > limit:
        text = text[:limit-1] + '…'
    # Normalize leading whitespace before checking; untrusted text can hide a formula.
    return "'" + text if text.startswith(('=', '+', '-', '@')) else text


def build_audit(folder: Path) -> Path:
    folder = folder.resolve()
    repeat = read_json(folder/'repeatability.json')
    summary = repeat.get('summary') if repeat else read_json(folder/'summary.json')
    if not isinstance(summary, dict) or not isinstance(summary.get('cases'), list):
        raise ValueError('No suite summary.json or repeatability.json with cases')
    runs = repeat['runs'] if repeat else [summary]
    report = Report(folder)
    rows = []

    def relative(path):
        asset = report.asset(path) if path else None
        return os.path.relpath(asset, folder) if asset else ''

    for repeat_index, run in enumerate(runs, 1):
        for entry in run['cases']:
            case_folder, result, _ = report.case_data(entry)
            source_folder = case_folder
            if source_folder is None and entry.get('translation_folder'):
                source_file = report.asset(Path(entry['translation_folder'])/'source.json')
                source_folder = source_file.parent if source_file else None
            source = read_json(source_folder/'source.json') if source_folder else {}
            case = source.get('case', {})
            run_id = Path(run.get('output_directory', folder)).name
            base = dict(run_id=run_id, repeat_index=repeat_index, case_id=entry.get('case_id'),
                case_name=case.get('name', case.get('case_name', entry.get('case_id'))),
                case_status=entry.get('status'), designed_outcome=entry.get('designed_outcome'),
                outcome_as_designed=entry.get('outcome_as_designed'),
                faults=entry.get('faults_injected', run.get('faults_injected', [])),
                results_json=relative(case_folder/'results.json') if case_folder else '')

            def emit(item, row_type, step=None, screenshot=None, details=None):
                actual = item.get('actual', {})
                actual = actual if isinstance(actual, dict) else {'value': actual}
                vision = actual if row_type == 'check' else item
                probabilities = [a.get('probabilities', {}).get(a.get('choice'))
                    for a in vision.get('answers', {}).values()]
                probabilities = [p for p in probabilities if type(p) in (int, float)]
                readable = readable_item(item)
                if row_type == 'check' and item.get('kind') == 'route_geometry':
                    expected = human(item.get('expected', {}).get('description') or
                        item.get('expected', {}).get('requirement') or 'required route')
                    observed = vision_text(actual)
                elif row_type == 'check':
                    expected, _, observed = readable.removeprefix('Expected: ').partition(' · Actual: ')
                elif row_type in {'action', 'cleanup'}:
                    expected = readable.removeprefix('Requested: ').partition(' · Outcome: ')[0]
                    observed = human(item.get('actual')) if item.get('actual') is not None else item.get('status')
                else:
                    expected = entry.get('designed_outcome')
                    observed = entry.get('status')
                row = dict(base, row_id=f'R{len(rows)+1:04d}', step=step, row_type=row_type,
                    kind_or_action=item.get('kind', item.get('action')), target=item.get('target'),
                    status=item.get('status'), reason_code=item.get('code') or actual.get('code') or (details or {}).get('code'),
                    reason=item.get('reason'), expected=expected, actual=observed,
                    locator_source=item.get('locator_source'), healed=item.get('healed', False),
                    vision_provider=vision.get('provider'), vision_model=vision.get('model'),
                    min_confidence=vision.get('min_confidence'),
                    vision_min_selected_probability=min(probabilities) if probabilities else None,
                    borderline=borderline(item) if row_type=='check' else False, screenshot=relative(screenshot),
                    duration_s=entry.get('execution_seconds', entry.get('duration_seconds')) if row_type == 'case' else None)
                rows.append({key: cell(row.get(key), 240 if key == 'reason' else 500) for key in COLUMNS})

            emit(dict(status=entry.get('status'), reason=entry.get('reason'), code=entry.get('code')), 'case')
            for step in result.get('steps', []):
                for row_type, key in [('action', 'actions'), ('check', 'checks')]:
                    for item in step.get(key, []):
                        emit(item, row_type, step.get('source_step'), step.get('screenshot'), step.get('details'))
            for item in result.get('cleanup', []):
                emit(item, 'cleanup')
    path = folder/'audit.csv'
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator='\r\n')
        writer.writeheader()
        writer.writerows(rows)
    return path
