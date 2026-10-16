"""Map a suite exit to a build result; a Python crash can also exit with 1."""
import json
from pathlib import Path


def build_result(code, root=Path('artifacts')):
    if code not in (0, 1):
        return 'FAILURE'
    folders = list(root.glob('suite-*'))
    if len(folders) != 1:
        return 'FAILURE'  # Setup cleans the workspace: exactly one current suite is expected.
    folder = folders[0]
    try:
        summary = json.loads((folder/'summary.json').read_text())
        statuses = [entry['status'] for entry in summary['cases']]
        if not statuses or any(s not in {'PASSED', 'FAILED', 'BLOCKED'} for s in statuses):
            return 'FAILURE'
        expected = 'FAILED' if 'FAILED' in statuses else 'BLOCKED' if 'BLOCKED' in statuses else 'PASSED'
        if summary.get('reason') or summary['status'] != expected or 'duration_seconds' not in summary:
            return 'FAILURE'
        if not all((folder/name).is_file() for name in ['report.html', 'audit.csv']):
            return 'FAILURE'
        if code == 0 and expected == 'PASSED':
            return 'SUCCESS'
        if code == 1 and expected in {'FAILED', 'BLOCKED'}:
            return 'UNSTABLE'
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return 'FAILURE'


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('exit_code', type=int)
    args = parser.parse_args()
    print(build_result(args.exit_code))
