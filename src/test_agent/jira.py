"""Approval-gated Jira Cloud v3 client. Dry-run performs no HTTP requests."""
import base64
import hashlib
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import ZipFile

from test_agent.audit_validation import validate_finding, ticket_type_for, evidence_steps, display_step
from test_agent.reporting import read_json, short_text
from test_agent.schemas.audit_analysis import Finding


PATH_TEMPLATES = dict(auth='myself', project='project/{project}',
    issue_types='issue/createmeta/{project}/issuetypes', search='search/jql', create='issue',
    comment='issue/{issue}/comment', label='issue/{issue}', attach='issue/{issue}/attachments')


class JiraError(ValueError):
    def __init__(self, code, status=None, *, phase=None):
        super().__init__(code)
        self.code, self.status, self.phase = code, status, phase


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

    def request(self, method, path, body=None, *, multipart=None, phase=None):
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
            raise JiraError(code, status, phase=phase) from None
        except (TimeoutError, URLError) as exc:
            timeout = isinstance(exc, TimeoutError) or isinstance(getattr(exc,'reason',None), TimeoutError)
            raise JiraError('JIRA_TIMEOUT' if timeout else 'JIRA_HTTP',phase=phase) from None
        except Exception:
            raise JiraError('JIRA_HTTP',phase=phase) from None

    def issue_types(self):
        types, start = {}, 0
        for _ in range(10):
            data = self.request('GET',f'issue/createmeta/{self.project}/issuetypes?startAt={start}&maxResults=100',phase='issue_types')
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


def error_record(exc, phase):
    error = exc if isinstance(exc,JiraError) else JiraError('JIRA_HTTP')
    phase = error.phase if error.phase in PATH_TEMPLATES else phase
    return dict(code=error.code,status=error.status,phase=phase,path_template=PATH_TEMPLATES.get(phase))


def error_line(error, project):
    line = f"Jira {error['status'] or error['code']} during {error['phase']}"
    if error['status']==404 and error['phase'] in {'project','issue_types'}:
        line += f" (project {project} not found or not visible to the credential's account)"
    if error.get('path_template'):
        line += ' [path: '+error['path_template']+']'
    return line


def public_name(value):
    # Only displayName/type names, never email/accountId or raw provider bodies.
    text = ' '.join(str(value).split())
    text = ''.join(c for c in text if c.isprintable())
    return re.sub(r'\S+@\S+', '[redacted]', text)[:160]


def check_connection(*, client=None):
    """Read-only diagnostics: GET identity, project visibility and create metadata."""
    result = dict(checks=[],errors=[])
    phase = 'configuration'
    try:
        site = os.getenv('JIRA_SITE','https://lawxueni.atlassian.net').rstrip('/')
        project = os.getenv('JIRA_PROJECT','WBSFP')
        validate_config(site,project)
        client = client or JiraClient(site,project,os.getenv('JIRA_EMAIL',''),os.getenv('JIRA_API_TOKEN',''))
        phase = 'auth'
        me = client.request('GET','myself',phase=phase)
        if not isinstance(me,dict) or not isinstance(me.get('displayName'),str):
            raise JiraError('JIRA_HTTP')
        result['checks'].append(dict(phase=phase,status='OK',display_name=public_name(me['displayName'])))
        phase = 'project'
        visible = client.request('GET','project/'+project,phase=phase)
        if not isinstance(visible,dict) or visible.get('key')!=project:
            raise JiraError('JIRA_HTTP')
        result['checks'].append(dict(phase=phase,status='OK'))
        phase = 'issue_types'
        types = client.issue_types()
        result['checks'].append(dict(phase=phase,status='OK',issue_types=[public_name(n) for n in sorted(types)]))
    except Exception as exc:
        result['errors'].append(error_record(exc,phase))
    return result


def validate_config(site, project):
    if not re.fullmatch(r'https://[a-z0-9-]+\.atlassian\.net/?', site) or not re.fullmatch(r'[A-Z][A-Z0-9_]{1,30}', project):
        raise JiraError('JIRA_CONFIG')


def safe_url(value):
    parts = urlsplit(value or '')
    return value if parts.scheme in {'http','https'} and parts.netloc and not parts.username and not parts.password else ''


def adf(lines):
    return dict(type='doc',version=1,content=[dict(type='paragraph',content=[dict(type='text',text=str(line)[:12000] or '—')]) for line in lines])


def payload_for(finding, dossier, project, issue_type, build_url='', report_url=''):
    step = display_step(finding,dossier)
    actions = [s for s in dossier['test_case'].get('actions',[]) if step is None or s['number']==step]
    expected = [s for s in dossier['test_case'].get('expected',[]) if step is None or s['number']==step]
    source_action = '\n'.join(f"{s['number']}. {s['text']}" for s in actions)
    expected_text = '\n'.join(f"{s['number']}. {s['text']}" for s in expected)
    steps = evidence_steps(finding,dossier)
    identity = json.dumps([finding['case_id'], steps,
        [[n, [e['text'] for e in dossier['test_case'].get('expected',[]) if e['number']==n]] for n in steps]],
        ensure_ascii=False, separators=(',',':'))
    fingerprint = 'wbs-'+finding['case_id'].lower()+'-v2-'+hashlib.sha256(identity.encode()).hexdigest()[:12]
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
        if not ticket_type_for(finding.model_dump(),dossier) or validate_finding(finding,dossier,analysis.get('questions',[])):
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
            client.request('POST',f'issue/{key}/attachments',multipart=(body,boundary),phase='attach')


def matching_issues(client, search_payload, case_id, fingerprint, project):
    """Fetch every page, filter exact v2/legacy labels, and select oldest open match."""
    legacy = re.compile(r'^wbs-'+re.escape(case_id.lower())+r'-step(?:case|[1-9][0-9]*)-[a-f0-9]{12}$')
    matches, tokens = {}, set()
    payload = dict(search_payload)
    while True:
        data = client.request('POST','search/jql',payload,phase='search')
        if not isinstance(data,dict) or not isinstance(data.get('issues'),list):
            raise JiraError('JIRA_HTTP',phase='search')
        for issue in data['issues']:
            if not isinstance(issue,dict) or not isinstance(issue.get('fields'),dict):
                raise JiraError('JIRA_HTTP',phase='search')
            key, fields = issue.get('key',''), issue['fields']
            labels = fields.get('labels')
            if not isinstance(labels,list) or not all(isinstance(label,str) for label in labels):
                raise JiraError('JIRA_HTTP',phase='search')
            if not any(isinstance(label,str) and
                    (label==fingerprint or legacy.fullmatch(label)) for label in labels):
                continue
            if not re.fullmatch(re.escape(project)+r'-[0-9]+',key):
                raise JiraError('JIRA_HTTP',phase='search')
            try:
                created = datetime.fromisoformat(fields['created'].replace('Z','+00:00'))
                if created.tzinfo is None:
                    raise ValueError('Missing timezone')
                created = created.timestamp()
            except (KeyError, TypeError, ValueError):
                raise JiraError('JIRA_HTTP',phase='search') from None
            matches[key] = dict(key=key,created=created,legacy_only=fingerprint not in labels)
        token = data.get('nextPageToken')
        if data.get('isLast') is True:
            break
        if not token:
            if data.get('isLast') is False:
                raise JiraError('JIRA_HTTP',phase='search')
            break
        if not isinstance(token,str) or token in tokens:
            raise JiraError('JIRA_HTTP',phase='search')
        tokens.add(token)
        payload = dict(search_payload,nextPageToken=token)
    return sorted(matches.values(),key=lambda issue:(issue['created'],int(issue['key'].rsplit('-',1)[1])))


def create_tickets(folder, approved, *, send=False, client=None):
    folder = Path(folder).resolve()
    result = dict(dry_run=not send,issues=[],errors=[])
    payloads = []
    phase = 'approval'
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
            phase = 'issue_types'
            types = client.issue_types()
        for finding,dossier in selected:
            phase = 'prepare'
            issue_type = 'Bug' if ticket_type_for(finding,dossier)=='bug' and types and 'Bug' in types else 'Task'
            if types is not None and issue_type not in types:
                raise JiraError('JIRA_CONFIG')
            payload, fingerprint = payload_for(finding,dossier,project,issue_type,os.getenv('BUILD_URL',''),
                os.getenv('TEST_REPORT_URL') or (os.getenv('BUILD_URL','')+'Test_20Report/' if os.getenv('BUILD_URL') else ''))
            paths = attachments_for(finding,dossier,analysis.get('questions',[]))
            jql = f'project = "{project}" AND (labels = "{fingerprint}" OR labels = "{finding["case_id"]}") AND statusCategory != Done ORDER BY created ASC, key ASC'
            entry = dict(finding_id=finding['finding_id'],issue_type=issue_type,
                type_resolution='discovered' if types is not None else 'offline Task fallback; rediscover on send',
                create_payload=payload,search_payload=dict(jql=jql,fields=['labels','created'],maxResults=100),attachments=paths)
            payloads.append(entry)
            if not send:
                continue
            try:
                phase = 'search'
                issues = matching_issues(client,entry['search_payload'],finding['case_id'],fingerprint,project)
                if issues:
                    key = issues[0]['key']
                    if not re.fullmatch(re.escape(project)+r'-\d+',key):
                        raise JiraError('JIRA_HTTP')
                    phase = 'comment'
                    client.request('POST',f'issue/{key}/comment',{'body':adf([
                        'AI suggestion reviewed again; new build: '+(safe_url(os.getenv('BUILD_URL','')) or 'not available'),
                        'Test Report: '+(safe_url(os.getenv('TEST_REPORT_URL','')) or 'not available'),finding['explanation']])},phase=phase)
                    action = 'commented'
                else:
                    phase = 'create'
                    created = client.request('POST','issue',payload,phase=phase)
                    key = created.get('key','')
                    if not re.fullmatch(re.escape(project)+r'-\d+',key):
                        raise JiraError('JIRA_HTTP')
                    action = 'created'
                issue = dict(finding_id=finding['finding_id'],key=key,url=site+'/browse/'+key,action=action,issue_type=issue_type,
                             attachments=0)
                issue['duplicate_keys'] = [i['key'] for i in issues[1:]]
                if issue['duplicate_keys']:
                    issue['warning'] = 'Multiple open matches; commented on the oldest issue.'
                result['issues'].append(issue)  # Preserve created key even if attachment upload fails.
                if action=='commented' and issues[0]['legacy_only']:
                    phase = 'label'
                    client.request('PUT',f'issue/{key}',{'update':{'labels':[{'add':fingerprint}]}},phase=phase)
                    issue['added_v2_label'] = fingerprint
                phase = 'attach'
                attach(client,folder,key,paths)
                issue['attachments'] = len(paths)
            except Exception as exc:
                result['errors'].append(dict(finding_id=finding['finding_id'],**error_record(exc,phase)))
    except Exception as exc:
        error = exc if isinstance(exc,JiraError) else JiraError('JIRA_CONFIG')
        result['errors'].append(error_record(error,phase))
    (folder/'jira_payloads.json').write_text(json.dumps(payloads,ensure_ascii=False,indent=2))
    (folder/'jira_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result
