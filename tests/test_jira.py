"""Only fake HTTP: approvals, payloads, deduplication, attachments, safe errors."""
import copy
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
from test_agent.jira import JiraClient, create_tickets, payload_for


class FakeJiraHTTP:
    def __init__(self, *, bug=True, duplicate=False, error=None):
        self.bug,self.duplicate,self.error=bug,duplicate,error
        self.calls=[]
    def __call__(self,request,timeout):
        self.calls.append(request)
        if self.error:
            raise HTTPError(request.full_url,self.error,'do not expose token or response',{},io.BytesIO(b'private body'))
        path=request.full_url
        if 'createmeta' in path:
            data=dict(issueTypes=[dict(id='2',name='Task',subtask=False)]+([dict(id='1',name='Bug',subtask=False)] if self.bug else []),isLast=True)
        elif path.endswith('/search/jql'):
            data=dict(issues=[dict(key='WBSFP-42')] if self.duplicate else [])
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
