"""Step-level JUnit XML from saved evidence, without models or browsers."""
import os
import xml.etree.ElementTree as ET
from pathlib import Path

from test_agent.reporting import Report, borderline, human, read_json, readable_item, short_text


def xml_text(value):
    return ''.join(c for c in str(value) if c in '\t\n\r' or
                   0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or
                   0x10000 <= ord(c) <= 0x10FFFF)


def build_junit(folder: Path) -> Path:
    folder = folder.resolve()
    repeat = read_json(folder/'repeatability.json')
    summary = repeat.get('summary') if repeat else read_json(folder/'summary.json')
    if not isinstance(summary, dict) or not isinstance(summary.get('cases'), list):
        raise ValueError('No suite summary.json or repeatability.json with cases')
    report, root = Report(folder), ET.Element('testsuites')
    for run_index, run in enumerate(repeat['runs'] if repeat else [summary], 1):
        for entry in run['cases']:
            case_folder, result, plan = report.case_data(entry)
            source_file = report.asset(Path(entry['translation_folder'])/'source.json') if entry.get('translation_folder') else None
            source = read_json(case_folder/'source.json') if case_folder else read_json(source_file) if source_file else {}
            case_id = entry['case_id']
            name = source.get('case', {}).get('name', case_id)
            label = f'Run {run_index} – ' if repeat else ''
            suite = ET.SubElement(root, 'testsuite', name=label+case_id+' – '+name,
                                  time=str(entry.get('execution_seconds', entry.get('duration_seconds', 0))))
            props = ET.SubElement(suite, 'properties')
            for key in ['designed_outcome', 'outcome_as_designed']:
                ET.SubElement(props, 'property', name=key, value=human(entry.get(key)))

            def relative(value):
                asset = report.asset(value, case_folder) if value else None
                return os.path.relpath(asset, folder) if asset else 'unavailable'

            def testcase(name, status, reason, lines):
                node = ET.SubElement(suite, 'testcase', classname=case_id, name=label+name)
                tag = {'FAILED': 'failure', 'BLOCKED': 'error', 'NOT_RUN': 'skipped'}.get(status)
                if status not in {'PASSED', 'FAILED', 'BLOCKED', 'NOT_RUN'}:
                    tag, reason = 'error', 'Missing or unknown execution status'
                if tag:
                    ET.SubElement(node, tag, message=short_text(reason or status, 240)).text = str(reason or status)
                ET.SubElement(node, 'system-out').text = '\n'.join(lines)

            if not case_folder or not result.get('steps'):
                translation = entry.get('code') == 'TRANSLATION_REJECTED'
                testcase('Translation' if translation else 'Execution', 'BLOCKED',
                         entry.get('reason') or 'Execution evidence unavailable',
                         ['reason_code: '+str(entry.get('code') or 'EVIDENCE_MISSING')])
            else:
                originals = {s['source_step']: s for s in plan.get('steps', [])}
                for step in result['steps']:
                    number = step['source_step']
                    lines = ['Source expected: '+str(originals.get(number, {}).get('source_expected', ''))]
                    for item in [*step.get('actions', []), *step.get('checks', [])]:
                        actual = item.get('actual') or {}
                        actual = actual if isinstance(actual, dict) else {}
                        lines.append(readable_item(item)+(' (borderline)' if item.get('kind') and borderline(item) else ''))
                        lines.append('locator_source: '+human(item.get('locator_source'))+
                                     '; reason_code: '+human(item.get('code') or actual.get('code') or step.get('details', {}).get('code'))+
                                     '; reason: '+human(item.get('reason')))
                    lines.extend(['screenshot: '+relative(step.get('screenshot')),
                                  'results.json: '+relative(case_folder/'results.json')])
                    testcase(f'Step {number} – '+short_text(originals.get(number, {}).get('source_action', ''), 160),
                             step.get('status'), step.get('reason'), lines)
                cleanup = result.get('cleanup', [])
                status = next((s for s in ['FAILED', 'BLOCKED', 'NOT_RUN'] if any(i.get('status') == s for i in cleanup)),
                              'PASSED' if cleanup else 'NOT_RUN')
                testcase('Cleanup', status, '; '.join(i['reason'] for i in cleanup if i.get('reason')),
                         [readable_item(i)+'; locator_source: '+human(i.get('locator_source')) for i in cleanup]+
                         ['results.json: '+relative(case_folder/'results.json')])
            nodes = suite.findall('testcase')
            suite.set('tests', str(len(nodes)))
            for attribute, tag in [('failures', 'failure'), ('errors', 'error'), ('skipped', 'skipped')]:
                suite.set(attribute, str(sum(n.find(tag) is not None for n in nodes)))
    for node in root.iter():
        node.attrib.update({key: xml_text(value) for key, value in node.attrib.items()})
        if node.text is not None:
            node.text = xml_text(node.text)
    ET.indent(root)
    path = folder/'junit.xml'
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)
    return path
