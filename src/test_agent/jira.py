"""Approval-gated Jira Cloud v3 client. Dry-run performs no HTTP requests."""
import base64
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import ZipFile

from test_agent.audit_validation import validate_finding
from test_agent.reporting import read_json, short_text
from test_agent.schemas.audit_analysis import Finding


class JiraError(ValueError):
    def __init__(self, code, status=None):
        super().__init__(code)
        self.code, self.status = code, status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Never forward credentials to another location.


class JiraClient:
    def __init__(self, site, project, email, token, *, opener=None):
        validate_config(site, project)
        if not email or not token:
            raise JiraError('JIRA_CONFIG')
        self.site, self.project = site.rstrip('/'), project
        self.authorization = 'Basic '+base64.b64encode((email+':'+token).encode()).decode()
        self.opener = opener or build_opener(NoRedirect()).open

    def request(self, method, path, body=None, *, multipart=None):
        headers = {'Authorization':self.authorization,'Accept':'application/json'}
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            headers['Content-Type'] = 'application/json'
        if multipart:
            data, boundary = multipart
            headers.update({'Content-Type':'multipart/form-data; boundary='+boundary,'X-Atlassian-Token':'no-check'})
        request = Request(self.site+'/rest/api/3/'+path, data=data, headers=headers, method=method)
        try:
            with self.opener(request, timeout=45) as response:
                raw = response.read()
            return json.loads(raw) if raw else {}
        except HTTPError as exc:
            code = 'JIRA_AUTH' if exc.code in {401,403} else 'JIRA_HTTP'
            status = exc.code
            exc.close()
            raise JiraError(code, status) from None
        except (TimeoutError, URLError) as exc:
            timeout = isinstance(exc, TimeoutError) or isinstance(getattr(exc,'reason',None), TimeoutError)
            raise JiraError('JIRA_TIMEOUT' if timeout else 'JIRA_HTTP') from None
        except Exception:
            raise JiraError('JIRA_HTTP') from None

    def issue_types(self):
        types, start = {}, 0
        for _ in range(10):
            data = self.request('GET',f'issue/createmeta/{self.project}/issuetypes?startAt={start}&maxResults=100')
            values = data.get('issueTypes', data.get('values', []))
            if not isinstance(values,list) or not values:
                raise JiraError('JIRA_CONFIG')
            for item in values:
                if not item.get('subtask') and isinstance(item.get('name'),str) and isinstance(item.get('id'),str):
                    types[item['name']] = item['id']
            start += len(values)
            if data.get('isLast', start >= data.get('total',start)):
                return types
        raise JiraError('JIRA_CONFIG')


def validate_config(site, project):
    if not re.fullmatch(r'https://[a-z0-9-]+\.atlassian\.net/?', site) or not re.fullmatch(r'[A-Z][A-Z0-9_]{1,30}', project):
        raise JiraError('JIRA_CONFIG')


def safe_url(value):
    parts = urlsplit(value or '')
    return value if parts.scheme in {'http','https'} and parts.netloc and not parts.username and not parts.password else ''


def adf(lines):
    return dict(type='doc',version=1,content=[dict(type='paragraph',content=[dict(type='text',text=str(line)[:12000] or '—')]) for line in lines])


def payload_for(finding, dossier, project, issue_type, build_url='', report_url=''):
    step = finding['step']
    actions = [s for s in dossier['test_case'].get('actions',[]) if step is None or s['number']==step]
    expected = [s for s in dossier['test_case'].get('expected',[]) if step is None or s['number']==step]
    source_action = '\n'.join(f"{s['number']}. {s['text']}" for s in actions)
    expected_text = '\n'.join(f"{s['number']}. {s['text']}" for s in expected)
    identity = json.dumps([finding['case_id'],step,source_action,expected_text,finding['ticket_type']],ensure_ascii=False)
    fingerprint = 'wbs-'+finding['case_id'].lower()+'-step'+str(step or 'case')+'-'+hashlib.sha256(identity.encode()).hexdigest()[:12]
    rows = [r for r in dossier['rows'] if r['row_id'] in finding['evidence_rows']]
    lines = [f"Case: {finding['case_id']} · Step: {step or 'case'}",'Source action: '+source_action,
        'Expected (Excel): '+expected_text,
        'Actual / reason: '+'; '.join(f"{r['row_id']}: {r['status']}; {r['actual']}; {r['reason_code']}; {r['reason']}" for r in rows),
        'Category: '+finding['likely_cause'], 'Evidence rows: '+', '.join(finding['evidence_rows']),
        'Designed outcome: '+str(dossier['designed_outcome']),
        'Jenkins build: '+(safe_url(build_url) or 'not available'), 'Test Report: '+(safe_url(report_url) or 'not available')]
    description = adf(lines)
    description['content'].append(dict(type='heading',attrs={'level':2},content=[dict(type='text',text='AI analysis (suggestion, verify)')]))
    description['content'].extend(adf(['Likely cause: '+finding['likely_cause']+' · confidence: '+finding['confidence'],
        finding['explanation'], 'Alternative causes: '+'; '.join(a['cause']+': '+a['why'] for a in finding['alternative_causes']),
        'Screenshot observation: '+finding['screenshot_observations'], 'Suggested next step: '+finding['suggested_next_step']])['content'])
    return dict(fields=dict(project={'key':project},issuetype={'name':issue_type},
        summary=short_text('[WBS] '+finding['case_id']+' '+finding['title'],255),description=description,
        labels=['wbs-test-agent',fingerprint,finding['case_id']])), fingerprint


def selected_findings(folder, approved):
    analysis = read_json(folder/'audit_analysis.json')
    selected = []
    for item in analysis.get('findings',[]):
        if item.get('finding_id') not in approved:
            continue
        finding = Finding.model_validate(item)
        dossier = analysis['cases'][finding.case_id]
        if not finding.recommend_ticket or validate_finding(finding,dossier,analysis.get('questions',[])):
            raise JiraError('JIRA_CONFIG')
        selected.append((finding.model_dump(),dossier))
    if {f['finding_id'] for f,_ in selected} != set(approved) or len(selected) != len(set(approved)):
        raise JiraError('JIRA_CONFIG')
    return analysis, selected


def attachments_for(finding, dossier, questions):
    ids = set(finding['evidence_screenshots'])
    ids.update(q['screenshot_id'] for q in questions if q['question_id'] in finding['evidence_questions'])
    paths = {r['screenshot'] for r in dossier['rows'] if r['row_id'] in finding['evidence_rows'] and r['screenshot']}
    paths.update(s['path'] for s in dossier['screenshots'] if s['screenshot_id'] in ids or s['step']==finding['step'])
    return sorted(paths)[:4]


def attach(client, folder, key, paths):
    with ZipFile(folder/'evidence.zip') as archive:
        for index,path in enumerate(paths,1):
            if Path(path).is_absolute() or '..' in Path(path).parts or archive.getinfo(path).file_size > 4*1024*1024:
                raise JiraError('JIRA_CONFIG')
            image = archive.read(path)
            if not image.startswith(b'\x89PNG\r\n\x1a\n'):
                raise JiraError('JIRA_CONFIG')
            boundary = 'wbs-'+uuid.uuid4().hex
            filename = f'evidence-{index}.png'
            body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                    'Content-Type: image/png\r\n\r\n').encode()+image+f'\r\n--{boundary}--\r\n'.encode()
            client.request('POST',f'issue/{key}/attachments',multipart=(body,boundary))


def create_tickets(folder, approved, *, send=False, client=None):
    folder = Path(folder).resolve()
    result = dict(dry_run=not send,issues=[],errors=[])
    payloads = []
    try:
        site, project = os.getenv('JIRA_SITE','https://lawxueni.atlassian.net').rstrip('/'), os.getenv('JIRA_PROJECT','WBSFP')
        validate_config(site,project)
        analysis, selected = selected_findings(folder,approved)
        digest = hashlib.sha256((folder/'audit_analysis.json').read_bytes()).hexdigest()
        decision = read_json(folder/'jira_decision.json')
        if send and decision and (decision.get('analysis_sha256') != digest or set(decision.get('approved',[])) != set(approved) or decision.get('status') != 'approved'):
            raise JiraError('JIRA_CONFIG')
        if not decision:
            decision = dict(status='approved' if approved else 'declined',approved=approved,approved_by='local-cli',
                            analysis_sha256=digest,dry_run=not send)
            (folder/'jira_decision.json').write_text(json.dumps(decision,indent=2))
        types = None
        if send and selected:
            client = client or JiraClient(site,project,os.getenv('JIRA_EMAIL',''),os.getenv('JIRA_API_TOKEN',''))
            types = client.issue_types()
        for finding,dossier in selected:
            issue_type = 'Bug' if finding['ticket_type']=='bug' and types and 'Bug' in types else 'Task'
            if types is not None and issue_type not in types:
                raise JiraError('JIRA_CONFIG')
            payload, fingerprint = payload_for(finding,dossier,project,issue_type,os.getenv('BUILD_URL',''),
                os.getenv('TEST_REPORT_URL') or (os.getenv('BUILD_URL','')+'Test_20Report/' if os.getenv('BUILD_URL') else ''))
            paths = attachments_for(finding,dossier,analysis.get('questions',[]))
            jql = f'project = "{project}" AND labels = "{fingerprint}" AND statusCategory != Done ORDER BY created ASC'
            entry = dict(finding_id=finding['finding_id'],issue_type=issue_type,
                type_resolution='discovered' if types is not None else 'offline Task fallback; rediscover on send',
                create_payload=payload,search_payload=dict(jql=jql,fields=['summary'],maxResults=1),attachments=paths)
            payloads.append(entry)
            if not send:
                continue
            try:
                existing = client.request('POST','search/jql',entry['search_payload'])
                issues = existing.get('issues')
                if not isinstance(issues,list):
                    raise JiraError('JIRA_HTTP')
                if issues:
                    key = issues[0]['key']
                    if not re.fullmatch(re.escape(project)+r'-\d+',key):
                        raise JiraError('JIRA_HTTP')
                    client.request('POST',f'issue/{key}/comment',{'body':adf([
                        'AI suggestion reviewed again; new build: '+(safe_url(os.getenv('BUILD_URL','')) or 'not available'),
                        'Test Report: '+(safe_url(os.getenv('TEST_REPORT_URL','')) or 'not available'),finding['explanation']])})
                    action = 'commented'
                else:
                    created = client.request('POST','issue',payload)
                    key = created.get('key','')
                    if not re.fullmatch(re.escape(project)+r'-\d+',key):
                        raise JiraError('JIRA_HTTP')
                    action = 'created'
                issue = dict(finding_id=finding['finding_id'],key=key,url=site+'/browse/'+key,action=action,issue_type=issue_type,
                             attachments=0)
                result['issues'].append(issue)  # Preserve created key even if attachment upload fails.
                attach(client,folder,key,paths)
                issue['attachments'] = len(paths)
            except Exception as exc:
                error = exc if isinstance(exc,JiraError) else JiraError('JIRA_HTTP')
                result['errors'].append(dict(finding_id=finding['finding_id'],code=error.code,status=error.status))
    except Exception as exc:
        error = exc if isinstance(exc,JiraError) else JiraError('JIRA_CONFIG')
        result['errors'].append(dict(code=error.code,status=error.status))
    (folder/'jira_payloads.json').write_text(json.dumps(payloads,ensure_ascii=False,indent=2))
    (folder/'jira_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result
