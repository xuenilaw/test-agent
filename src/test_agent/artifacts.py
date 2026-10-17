"""Named CI downloads and deliberately narrow, opt-in local retention."""
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile, ZIP_DEFLATED

from test_agent.audit import build_audit
from test_agent.junit import build_junit
from test_agent.reporting import build_report, read_json

DOWNLOADS = ('report.html', 'audit.csv', 'junit.xml', 'summary.json', 'evidence.zip')
EXTRA_DOWNLOADS = ('guardrail.json','audit_analysis.json','audit_analysis.md','audit_review.json',
                   'jira_decision.json','jira_payloads.json','jira_results.json')


class EvidenceLinks(HTMLParser):
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            href = dict(attrs).get('href', '')
            if href and not href.startswith('#'):
                path = unquote(href)
                if Path(path).is_absolute() or '..' in Path(path).parts:
                    raise ValueError('Report evidence is outside the suite folder; cannot package portable links')


def package_reports(folder: Path, output: Path) -> Path:
    folder, output = folder.resolve(), output.resolve()
    if output == folder or output.is_relative_to(folder) or folder.is_relative_to(output):
        raise ValueError('Reports destination must be separate from the evidence folder')
    if output.exists() and any(p.name not in DOWNLOADS+EXTRA_DOWNLOADS or not p.is_file() or p.is_symlink() for p in output.iterdir()):
        raise ValueError('Reports destination contains unexpected files; choose a dedicated folder')
    build_report(folder)
    build_audit(folder)
    build_junit(folder)
    EvidenceLinks().feed((folder/'report.html').read_text())
    output.mkdir(parents=True, exist_ok=True)
    for name in DOWNLOADS[:3]:
        shutil.copyfile(folder/name, output/name)
    for name in EXTRA_DOWNLOADS:
        if (folder/name).is_file():
            shutil.copyfile(folder/name,output/name)
        elif (output/name).exists():
            (output/name).unlink()  # Don't keep an older suite's analysis/approval in a new package.
    repeat = read_json(folder/'repeatability.json')
    if repeat:
        import json
        (output/'summary.json').write_text(json.dumps(repeat['summary'], ensure_ascii=False, indent=2))
    else:
        shutil.copyfile(folder/'summary.json', output/'summary.json')
    with ZipFile(output/'evidence.zip', 'w', compression=ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob('*')):
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(folder):
                relative = path.relative_to(folder)
                if str(relative) not in DOWNLOADS+EXTRA_DOWNLOADS:
                    archive.write(path, relative.as_posix())
    return output


def prune(root: Path, *, keep=10, yes=False) -> list[Path]:
    if type(keep) is not int or keep < 0:
        raise ValueError('keep must be a non-negative integer')
    if root.is_symlink() or root.name != 'artifacts':
        raise ValueError('Prune requires the real project artifacts directory')
    if not root.exists():
        return []
    candidates = [p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and
                  p.name.startswith(('suite-', 'repeat-', 'run-', 'translation-'))]
    victims = sorted(candidates, key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)[keep:]
    if yes:
        for path in victims:
            shutil.rmtree(path)
    return victims
