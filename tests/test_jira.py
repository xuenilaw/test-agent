"""Only fake HTTP: approvals, payloads, deduplication, attachments, safe errors."""
import copy
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from test_audit_agent import audit_fixture, fake_analyst, FakeAuditVision
from test_vision import FakeHTTP
from test_agent.audit_agent import run_audit_agent
from test_agent.artifacts import package_reports
from test_agent.jira import JiraClient, create_tickets, payload_for, check_connection, error_line, PATH_TEMPLATES, matching_issues, JiraError
from test_agent.cli import main


class FakeJiraHTTP:
    def __init__(self, *, bug=True, duplicate=False, error=None, error_phase=None):
        self.bug,self.duplicate,self.error=bug,duplicate,error
        self.calls=[];self.error_phase=error_phase
    def __call__(self,request,timeout):
        self.calls.append(request)
        path=request.full_url
        phase=('issue_types' if 'createmeta' in path else 'search' if path.endswith('/search/jql') else
               'create' if path.endswith('/issue') else 'comment' if path.endswith('/comment') else
               'attach' if path.endswith('/attachments') else 'label' if request.get_method()=='PUT' else 'auth' if path.endswith('/myself') else 'project')
        if self.error and (self.error_phase is None or phase==self.error_phase):
            raise HTTPError(request.full_url,self.error,'do not expose token or response',{},io.BytesIO(b'private body'))
        path=request.full_url
        if path.endswith('/myself'):
            data=dict(displayName='Test Engineer',emailAddress='private-email@example.test',accountId='private-account-id')
        elif path.endswith('/project/WBSFP'):
            data=dict(key='WBSFP',email='private-email@example.test')
        elif 'createmeta' in path:
            data=dict(issueTypes=[dict(id='2',name='Task',subtask=False)]+([dict(id='1',name='Bug',subtask=False)] if self.bug else []),isLast=True)
        elif path.endswith('/search/jql'):
            data=dict(issues=[dict(key='WBSFP-42',fields=dict(labels=['wbs-case-2-step1-012345abcdef'],created='2026-10-16T10:00:00Z'))] if self.duplicate else [],isLast=True)
        elif path.endswith('/issue'):
            data=dict(key='WBSFP-43')
        else:
            data={}
        return FakeHTTP(json.dumps(data).encode())


class JiraTests(unittest.IsolatedAsyncioTestCase):
    async def prepare(self,root):
        suite=root/'suite-fixture';audit_fixture(suite)
        analysis=await run_audit_agent(suite,analyst=fake_analyst,vision=FakeAuditVision())
        reports=package_reports(suite,root/'reports')
        candidate=next(f for f in analysis['findings'] if f['recommend_ticket'])
        return reports,candidate

    async def test_dry_run_sends_nothing_and_writes_plain_adf_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            reports,f=await self.prepare(Path(temp))
            with patch('test_agent.jira.JiraClient',side_effect=AssertionError('dry run made HTTP')),patch.dict(os.environ,
                    {'BUILD_URL':'http://127.0.0.1:8080/job/test-agent/9/','TEST_REPORT_URL':'http://127.0.0.1:8080/job/test-agent/9/Test_20Report/'}):
                result=create_tickets(reports,[f['finding_id']])
            self.assertTrue(result['dry_run']);self.assertFalse(result['errors'])
            payload=json.loads((reports/'jira_payloads.json').read_text())[0]
            fields=payload['create_payload']['fields']
            self.assertEqual(fields['project'],{'key':'WBSFP'})
            self.assertEqual(fields['issuetype'],{'name':'Task'})
            self.assertEqual(fields['description']['type'],'doc')
            self.assertEqual(fields['description']['version'],1)
            text=json.dumps(fields['description'])
            for value in ['AI analysis (suggestion, verify)','Source action:','Expected (Excel):','Actual / reason:',
                          'Designed outcome:','http://127.0.0.1:8080/job/test-agent/9/','Test_20Report/']:
                self.assertIn(value,text)
            self.assertIn('wbs-test-agent',fields['labels']);self.assertIn('CASE-2',fields['labels'])
            self.assertTrue(payload['attachments'])
            self.assertNotIn('Authorization',(reports/'jira_payloads.json').read_text())
            d=json.loads((reports/'audit_analysis.json').read_text())['cases']['CASE-2']
            _,a=payload_for(f,d,'WBSFP','Task')
            _,b=payload_for({**f,'title':'A different model wording','explanation':'Different explanation'},d,'WBSFP','Task')
            self.assertEqual(a,b)

    async def test_fingerprint_uses_failed_source_steps_only(self):
        with tempfile.TemporaryDirectory() as temp:
            reports,f=await self.prepare(Path(temp))
            d=json.loads((reports/'audit_analysis.json').read_text())['cases']['CASE-2']
            def label(item,dossier=d): return payload_for(item,dossier,'WBSFP','Task')[1]
            original=label(f)
            self.assertEqual(original,label({**f,'step':None,'ticket_type':'bug','title':'Changed','explanation':'Changed'}))
            self.assertEqual(original,label({**f,'step':5,'recommend_ticket':False}))
            changed=copy.deepcopy(d)
            for r in changed['rows']:
                if r['row_id'] in f['evidence_rows'] and r['status']=='FAILED':r['step']='5'
            changed['test_case']['expected'].append(dict(number=5,text='Another expectation'))
            self.assertNotEqual(original,label(f,changed))
            changed=copy.deepcopy(d);changed['test_case']['expected'][0]['text']='Changed expectation'
            self.assertNotEqual(original,label(f,changed))
            # Source actions and row IDs/order are not part of identity.
            changed=copy.deepcopy(d);changed['test_case']['actions'][0]['text']='Reworded action'
            self.assertEqual(original,label({**f,'evidence_rows':list(reversed(f['evidence_rows']))},changed))

    async def test_legacy_search_paginates_and_comments_on_oldest_match(self):
        with tempfile.TemporaryDirectory() as temp:
            reports,f=await self.prepare(Path(temp))
            path=reports/'audit_analysis.json';a=json.loads(path.read_text())
            next(i for i in a['findings'] if i['finding_id']==f['finding_id']).update(recommend_ticket=False,ticket_type=None,step=None)
            path.write_text(json.dumps(a))
            http=FakeJiraHTTP();searches=[]
            def opener(request,timeout):
                if not request.full_url.endswith('/search/jql'):return http(request,timeout)
                searches.append(json.loads(request.data))
                if len(searches)==1:
                    data=dict(issues=[dict(key='WBSFP-2',fields=dict(labels=['wbs-case-2-stepcase-a5fa2c19fefc'],created='2026-10-17T10:00:00Z'))],nextPageToken='page2')
                else:
                    data=dict(issues=[dict(key='WBSFP-1',fields=dict(labels=['wbs-case-2-step5-596e53579875'],created='2026-10-16T10:00:00Z')),
                        dict(key='WBSFP-3',fields=dict(labels=['CASE-2','wbs-case-2-v2-unrelated'],created='2026-10-15T10:00:00Z'))],isLast=True)
                return FakeHTTP(json.dumps(data).encode())
            client=JiraClient('https://lawxueni.atlassian.net','WBSFP','fake','fake',opener=opener)
            result=create_tickets(reports,[f['finding_id']],send=True,client=client)
            self.assertFalse(result['errors'],result)
            issue=result['issues'][0]
            self.assertEqual((issue['action'],issue['key'],issue['duplicate_keys']),('commented','WBSFP-1',['WBSFP-2']))
            self.assertIn('oldest',issue['warning'])
            self.assertEqual(searches[1]['nextPageToken'],'page2')
            self.assertIn('labels = "CASE-2"',searches[0]['jql'])
            self.assertFalse(any(r.full_url.endswith('/issue') for r in http.calls))

    def test_fingerprint_multi_step_sorting_and_blocked_fallback(self):
        f=dict(case_id='CASE-2',step=None,title='Issue',likely_cause='test_case_problem',confidence='high',
            explanation='Why',alternative_causes=[],screenshot_observations='',suggested_next_step='Review',
            evidence_rows=['b','a'])
        def row(row_id,step,status):return dict(row_id=row_id,step=str(step),status=status,row_type='check',actual='',reason_code='',reason='')
        d=dict(test_case=dict(actions=[],expected=[dict(number=5,text='Five'),dict(number=2,text='Two')]),
               rows=[row('a',5,'FAILED'),row('b',2,'FAILED')],designed_outcome='FAILED')
        label=payload_for(f,d,'WBSFP','Task')[1]
        reverse=copy.deepcopy(d);reverse['rows'].reverse();reverse['test_case']['expected'].reverse()
        self.assertEqual(label,payload_for({**f,'evidence_rows':['a','b']},reverse,'WBSFP','Task')[1])
        for r in d['rows']:r['status']='BLOCKED'
        self.assertEqual(label,payload_for(f,d,'WBSFP','Task')[1])
        d['rows'][0]['status']='PASSED'
        self.assertNotEqual(label,payload_for(f,d,'WBSFP','Task')[1])

    def test_search_matches_exact_v2_and_rejects_incomplete_responses(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        label='wbs-case-2-v2-012345abcdef'
        issue=dict(key='WBSFP-7',fields=dict(labels=[label],created='2026-10-17T10:00:00Z'))
        client=SimpleNamespace(request=Mock(return_value=dict(issues=[issue],isLast=True)))
        self.assertEqual(matching_issues(client,{},'CASE-2',label,'WBSFP')[0]['key'],'WBSFP-7')
        for data in [dict(issues=[dict(key='WBSFP-7')],isLast=True),dict(issues=[],isLast=False),
                     dict(issues=[{**issue,'fields':dict(labels=[label],created='invalid')}],isLast=True)]:
            client.request=Mock(return_value=data)
            with self.assertRaises(JiraError):matching_issues(client,{},'CASE-2',label,'WBSFP')
        client.request=Mock(return_value=dict(issues=[],nextPageToken='repeated'))
        with self.assertRaises(JiraError):matching_issues(client,{},'CASE-2',label,'WBSFP')

    async def test_bug_metadata_present_or_absent_and_attachment_header(self):
        for bug,expected in [(True,'Bug'),(False,'Task')]:
            with self.subTest(bug=bug),tempfile.TemporaryDirectory() as temp:
                reports,f=await self.prepare(Path(temp))
                path=reports/'audit_analysis.json';analysis=json.loads(path.read_text())
                candidate=next(i for i in analysis['findings'] if i['finding_id']==f['finding_id'])
                candidate.update(likely_cause='software_bug',ticket_type='bug')
                path.write_text(json.dumps(analysis))
                http=FakeJiraHTTP(bug=bug)
                client=JiraClient('https://lawxueni.atlassian.net','WBSFP','fake@example.test','fake-token',opener=http)
                result=create_tickets(reports,[f['finding_id']],send=True,client=client)
                self.assertFalse(result['errors'],result)
                self.assertEqual(result['issues'][0]['issue_type'],expected)
                self.assertEqual(result['issues'][0]['action'],'created')
                create=next(r for r in http.calls if r.full_url.endswith('/issue'))
                self.assertEqual(json.loads(create.data)['fields']['issuetype']['name'],expected)
                attach=next(r for r in http.calls if r.full_url.endswith('/attachments'))
                self.assertEqual(attach.get_header('X-atlassian-token'),'no-check')
                self.assertIn(b'name="file"',attach.data)
                self.assertIn(b'\x89PNG\r\n\x1a\n',attach.data)
                self.assertFalse(any('fake-token' in p.read_text() for p in reports.glob('jira*.json')))

    async def test_duplicate_uses_new_search_and_comment_no_create(self):
        with tempfile.TemporaryDirectory() as temp:
            reports,f=await self.prepare(Path(temp));http=FakeJiraHTTP(duplicate=True)
            client=JiraClient('https://lawxueni.atlassian.net','WBSFP','fake@example.test','fake-token',opener=http)
            with patch.dict(os.environ,{'BUILD_URL':'http://127.0.0.1:8080/job/test-agent/10/'}):
                result=create_tickets(reports,[f['finding_id']],send=True,client=client)
            self.assertFalse(result['errors'],result)
            self.assertEqual(result['issues'][0]['action'],'commented')
            self.assertFalse(any(r.full_url.endswith('/issue') for r in http.calls))
            search=next(r for r in http.calls if r.full_url.endswith('/search/jql'))
            self.assertIn('statusCategory != Done',json.loads(search.data)['jql'])
            comment=next(r for r in http.calls if r.full_url.endswith('/comment'))
            self.assertIn('/job/test-agent/10/',comment.data.decode())

    async def test_legacy_comment_adds_v2_label_and_retains_key_on_label_error(self):
        for fail in [False,True]:
            with self.subTest(fail=fail),tempfile.TemporaryDirectory() as temp:
                reports,f=await self.prepare(Path(temp))
                http=FakeJiraHTTP(duplicate=True,error=403 if fail else None,error_phase='label')
                client=JiraClient('https://lawxueni.atlassian.net','WBSFP','fake','fake',opener=http)
                result=create_tickets(reports,[f['finding_id']],send=True,client=client)
                update=next(r for r in http.calls if r.get_method()=='PUT')
                label=json.loads(update.data)['update']['labels'][0]['add']
                self.assertIn('-v2-',label)
                self.assertTrue(update.full_url.endswith('/issue/WBSFP-42'))
                issue=result['issues'][0]
                self.assertEqual((issue['key'],issue['action']),('WBSFP-42','commented'))
                if fail:
                    self.assertNotIn('added_v2_label',issue)
                    self.assertEqual(result['errors'][0]['phase'],'label')
                    self.assertFalse(any(r.full_url.endswith('/attachments') for r in http.calls))
                else:
                    self.assertFalse(result['errors'],result)
                    self.assertEqual(issue['added_v2_label'],label)
                    self.assertEqual(json.loads((reports/'jira_results.json').read_text())['issues'][0]['added_v2_label'],label)

    async def test_exact_v2_comment_does_not_add_label_again(self):
        with tempfile.TemporaryDirectory() as temp:
            reports,f=await self.prepare(Path(temp))
            d=json.loads((reports/'audit_analysis.json').read_text())['cases'][f['case_id']]
            label=payload_for(f,d,'WBSFP','Task')[1]
            http=FakeJiraHTTP()
            def opener(request,timeout):
                if request.full_url.endswith('/search/jql'):
                    return FakeHTTP(json.dumps(dict(issues=[dict(key='WBSFP-1',fields=dict(labels=[label],created='2026-10-16T10:00:00Z'))],isLast=True)).encode())
                return http(request,timeout)
            client=JiraClient('https://lawxueni.atlassian.net','WBSFP','fake','fake',opener=opener)
            result=create_tickets(reports,[f['finding_id']],send=True,client=client)
            self.assertFalse(result['errors'],result)
            self.assertEqual(result['issues'][0]['action'],'commented')
            self.assertNotIn('added_v2_label',result['issues'][0])
            self.assertFalse(any(r.get_method()=='PUT' for r in http.calls))

    async def test_unapproved_unknown_changed_analysis_and_safe_http_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            reports,f=await self.prepare(Path(temp))
            for approved in [['invented'],['F-CASE-1-1']]:
                http=FakeJiraHTTP();client=JiraClient('https://lawxueni.atlassian.net','WBSFP','fake','fake',opener=http)
                result=create_tickets(reports,approved,send=True,client=client)
                self.assertEqual(result['errors'][0]['code'],'JIRA_CONFIG');self.assertFalse(http.calls)
            decision=dict(status='approved',approved=[f['finding_id']],approved_by='test-user',analysis_sha256='wrong hash')
            (reports/'jira_decision.json').write_text(json.dumps(decision))
            result=create_tickets(reports,[f['finding_id']],send=True,client=client)
            self.assertEqual(result['errors'][0]['code'],'JIRA_CONFIG');self.assertFalse(http.calls)
            (reports/'jira_decision.json').unlink()
            for status,code in [(401,'JIRA_AUTH'),(503,'JIRA_HTTP')]:
                http=FakeJiraHTTP(error=status);client=JiraClient('https://lawxueni.atlassian.net','WBSFP','fake','fake',opener=http)
                result=create_tickets(reports,[f['finding_id']],send=True,client=client)
                self.assertEqual(result['errors'][0]['code'],code)
                self.assertEqual(result['errors'][0]['status'],status)
                self.assertNotIn('private body',json.dumps(result));self.assertNotIn('token',json.dumps(result))


    async def assert_phase_404(self,phase):
        with tempfile.TemporaryDirectory() as temp:
            reports,f=await self.prepare(Path(temp))
            http=FakeJiraHTTP(error=404,error_phase=phase,duplicate=phase=='comment')
            client=JiraClient('https://lawxueni.atlassian.net','WBSFP','private-email@example.test','private-token',opener=http)
            result=create_tickets(reports,[f['finding_id']],send=True,client=client)
            error=result['errors'][0]
            self.assertEqual((error['status'],error['phase'],error['path_template']),(404,phase,PATH_TEMPLATES[phase]))
            text=json.dumps(result['errors'])
            for secret in ['private-email','private-token','private body','startAt','maxResults','https://']:
                self.assertNotIn(secret,text)
            self.assertIn('Jira 404 during '+phase,error_line(error,'WBSFP'))
            if phase=='issue_types':
                self.assertIn("project WBSFP not found or not visible to the credential's account",error_line(error,'WBSFP'))
            if phase=='attach':self.assertEqual(result['issues'][0]['key'],'WBSFP-43')

    async def test_404_during_issue_types_is_diagnosable(self):await self.assert_phase_404('issue_types')
    async def test_404_during_search_is_diagnosable(self):await self.assert_phase_404('search')
    async def test_404_during_create_is_diagnosable(self):await self.assert_phase_404('create')
    async def test_404_during_comment_is_diagnosable(self):await self.assert_phase_404('comment')
    async def test_404_during_attach_is_diagnosable(self):await self.assert_phase_404('attach')


class JiraCheckTests(unittest.TestCase):
    def test_check_uses_only_get_and_returns_no_email_or_account_id(self):
        http=FakeJiraHTTP()
        client=JiraClient('https://lawxueni.atlassian.net','WBSFP','private-email@example.test','private-token',opener=http)
        result=check_connection(client=client)
        self.assertEqual(result['errors'],[])
        self.assertEqual([c['phase'] for c in result['checks']],['auth','project','issue_types'])
        self.assertEqual(result['checks'][0]['display_name'],'Test Engineer')
        self.assertEqual(result['checks'][2]['issue_types'],['Bug','Task'])
        self.assertTrue(all(r.method=='GET' for r in http.calls))
        self.assertEqual([r.full_url.split('/rest/api/3/')[1].split('?')[0] for r in http.calls],
                         ['myself','project/WBSFP','issue/createmeta/WBSFP/issuetypes'])
        self.assertNotIn('private-',json.dumps(result))

    def test_check_404_reports_each_read_phase_and_stops(self):
        for phase,count in [('auth',1),('project',2),('issue_types',3)]:
            with self.subTest(phase=phase):
                http=FakeJiraHTTP(error=404,error_phase=phase)
                client=JiraClient('https://lawxueni.atlassian.net','WBSFP','fake','fake',opener=http)
                result=check_connection(client=client)
                self.assertEqual(len(http.calls),count)
                self.assertEqual(result['errors'][0]['phase'],phase)
                self.assertEqual(result['errors'][0]['path_template'],PATH_TEMPLATES[phase])

    def test_check_cli_prints_safe_statuses_and_failure_has_nonzero_exit(self):
        for status in [None,401,404]:
            with self.subTest(status=status),tempfile.TemporaryDirectory() as temp:
                http=FakeJiraHTTP(error=status,error_phase='project' if status==404 else 'auth')
                client=JiraClient('https://lawxueni.atlassian.net','WBSFP','private-email@example.test','private-token',opener=http)
                out=io.StringIO()
                with patch.dict(os.environ,{},clear=True),patch('test_agent.jira.JiraClient',return_value=client),contextlib.redirect_stdout(out):
                    code=main(['--project-dir',temp,'jira','check'])
                self.assertEqual(code,0 if status is None else 1)
                self.assertEqual(list(Path(temp).iterdir()),[])
                text=out.getvalue()
                for secret in ['private-email','private-token','private body','private-account-id']:
                    self.assertNotIn(secret,text)
                if status is None:
                    self.assertIn('Jira auth: OK — Test Engineer',text)
                    self.assertIn('Jira issue_types: OK — Bug, Task',text)
                elif status==404:self.assertIn('Jira 404 during project',text)
                else:self.assertIn('Jira 401 during auth',text)

    def test_email_shaped_display_name_is_redacted(self):
        from test_agent.jira import public_name
        self.assertEqual(public_name('Name private-email@example.test\nextra'), 'Name [redacted] extra')
