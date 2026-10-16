"""Called after the suite command, including when it exits with a test failure."""
from pathlib import Path
from test_agent.artifacts import package_reports

if __name__ == '__main__':
    folders = list(Path('artifacts').glob('suite-*'))
    if len(folders) != 1:
        raise ValueError('Expected exactly one current suite folder')
    package_reports(folders[0], Path('reports'))
