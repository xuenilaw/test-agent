"""Fake Claude Haiku exercises analysis, blind observations and evidence validation."""
import asyncio
import contextlib
import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_day6 import fixture_suite
from test_vision import http_reply
from test_agent.audit_agent import dossiers_from_suite, run_audit_agent, claude_analyze, audit_model, approval_preview
from test_agent.audit_validation import validate_finding
from test_agent.audit_vision import ScreenshotQuestions
from test_agent.artifacts import package_reports
from test_agent.schemas.audit_analysis import Finding
from test_agent.verification.vision_providers import ClaudeVision, VisionError
from test_agent.cli import main


def audit_fixture(root):
    summary=fixture_suite(root)
    for entry in summary['cases']:
        folder=Path(entry['run_folder'])
        source=dict(case=dict(name='Layer and duration case',preconditions='Map is visible',
            actions=[dict(number=1,text='Select Topo')],expected=[dict(number=1,text='Topo is selected')],post_action='Reset Standard'),
            contract=dict(selected_layer='Topo',expected_options=['Standard','Topo','Other']))
        (folder/'source.json').write_text(json.dumps(source))
        plan=json.loads((folder/'plan.json').read_text())
        plan['steps'][0]['actions']=[dict(action='select',target='map layer selector',value='Topo')]
        (folder/'plan.json').write_text(json.dumps(plan))
        if entry['status']=='FAILED':
            result=json.loads((folder/'results.json').read_text())
            result['steps'][0]['checks']=[dict(kind='duration_minutes',target='duration',status='FAILED',
                expected=dict(operator='less_than',value=180),actual=dict(raw_text='7:36',parsed_minutes=456),reason='456 >= 180')]
            (folder/'results.json').write_text(json.dumps(result))
    return summary


def finding(dossier, *, cause=None, ticket=False):
    cause=cause or ('confirmed_pass' if dossier['status']=='PASSED' else 'needs_human_review')
    rows=[r['row_id'] for r in dossier['rows'] if r['row_type']=='check']
    return dict(finding_id='F-'+dossier['case_id']+'-1',case_id=dossier['case_id'],step=1,title='Check the expectation',
        likely_cause=cause,confidence='medium',explanation='Compare the expected Topo selection with the observed evidence.',
        alternative_causes=[dict(cause='environment_problem',why='The page may not have settled.')],
        screenshot_observations='',suggested_next_step='Review the source expectation.',evidence_rows=rows,
        evidence_screenshots=[],evidence_questions=[],recommend_ticket=ticket,
        ticket_type='test_case_fix' if ticket else None,severity='medium')


class FakeAuditVision:
    model='fake-haiku'
    def __init__(self, choice='Topo', confidence=.96):
        self.calls=[];self.choice=choice;self.confidence=confidence
    async def request_image(self,image,instructions,schema,**kwargs):
        self.calls.append((image,instructions,schema,kwargs))
        return dict(content=json.dumps(dict(choice=self.choice,confidence=self.confidence,observation='Visible selected radio.')),model=self.model)


async def fake_analyst(dossier,questions):
    f=finding(dossier)
    if dossier['screenshots']:
        q=await questions.ask(dossier['case_id'],dossier['screenshots'][0]['screenshot_id'],
            'Which layer is selected?',['Standard','Topo','unclear'])
        if q.get('answered'):
            f.update(evidence_questions=[q['question_id']],evidence_screenshots=[q['screenshot_id']],
                     screenshot_observations=q['observation'])
    if dossier['status']=='FAILED':
        f.update(likely_cause='test_case_problem',recommend_ticket=True,ticket_type='test_case_fix')
    return json.dumps(dict(summary='Review the expectation, with visual observations.',findings=[f]))


class AuditAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_dossiers_valid_analysis_all_cases_and_packaged_link(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);suite=root/'suite-fixture';audit_fixture(suite)
            (root/'.env').write_text('TOKEN=never-send-this')
            vision=FakeAuditVision()
            seen=[]
            async def analyst(dossier,questions):
                seen.append(json.dumps(dossier))
                return await fake_analyst(dossier,questions)
            result=await run_audit_agent(suite,analyst=analyst,vision=vision)
            self.assertEqual(len(result['findings']),3)
            self.assertEqual({f['case_id'] for f in result['findings']},{'CASE-1','CASE-2','CASE-3'})
            self.assertEqual(result['findings'][0]['likely_cause'],'confirmed_pass')
            self.assertFalse(result['agent_unavailable'])
            self.assertEqual(len(vision.calls),3)
            for payload in seen:
                self.assertIn('Topo is selected',payload)
                self.assertIn('row_id',payload)
                self.assertNotIn('never-send-this',payload)
                self.assertNotIn('base64',payload)
                self.assertNotIn('trace.zip',payload)
                self.assertNotIn('image/png',payload)
            self.assertTrue(all(len(d['screenshots'])<=4 for d in result['cases'].values()))
            preview=approval_preview(suite)
            self.assertEqual(len(preview['candidates']),1)
            reports=package_reports(suite,root/'reports')
            self.assertTrue((reports/'audit_analysis.json').exists())
            self.assertIn('audit_analysis.md',(reports/'report.html').read_text())
            self.assertIn('AI suggestion, verify before acting',(reports/'audit_analysis.md').read_text())

    async def test_tool_rejections_limits_errors_and_uncertainty(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);audit_fixture(root);dossiers=dossiers_from_suite(root)
            vision=FakeAuditVision(confidence=.89);tool=ScreenshotQuestions(root,dossiers,vision)
            shot=dossiers['CASE-1']['screenshots'][0]['screenshot_id']
            for sid,q,opts in [('foreign','Which layer?',['Standard','Topo','unclear']),
                    (shot,'Which layer?',['Topo','unclear']), (shot,'Which layer?',['Standard','Topo','Other']),
                    (shot,'Is it Topo?',['yes','no','unclear'])]:
                answer=await tool.ask('CASE-1',sid,q,opts)
                self.assertIn('code',answer)
                self.assertIn('rule',answer)
            self.assertFalse(vision.calls)
            self.assertEqual(tool.counts['CASE-1'],4)
            answer=await tool.ask('CASE-1',shot,'Which layer?',['Standard','Topo','unclear'])
            self.assertEqual(answer['status'],'uncertain')
            self.assertFalse(answer['contradicts_expected'])
            for _ in range(4): await tool.ask('CASE-1',shot,'Which layer?',['Standard','Topo','unclear'])
            self.assertEqual((await tool.ask('CASE-1',shot,'Which layer?',['Standard','Topo','unclear']))['code'],'VISION_LIMIT')
            self.assertEqual(len(vision.calls),1)
            tool.total=25
            self.assertEqual((await tool.ask('CASE-2',dossiers['CASE-2']['screenshots'][0]['screenshot_id'],
                'Which layer?',['Standard','Topo','unclear']))['code'],'VISION_LIMIT')
            self.assertEqual(len(vision.calls),1)
            failed=ScreenshotQuestions(root,dossiers,SimpleNamespace(model='fake',request_image=AsyncMock(
                side_effect=VisionError('HTTP',http_status=429))))
            reply=await failed.ask('CASE-1',shot,'Which layer?',['Standard','Topo','unclear'])
            self.assertEqual((reply['code'],reply['http_status']),('VISION_HTTP',429))
            self.assertFalse(reply['answered'])

    async def test_claude_request_blind_one_png_and_native_size_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);audit_fixture(root);dossiers=dossiers_from_suite(root)
            tool=ScreenshotQuestions(root,dossiers,ClaudeVision(api_key='fake',model='fake-haiku'))
            response=dict(model='fake-haiku',stop_reason='end_turn',content=[dict(type='text',text=json.dumps(
                dict(choice='Topo',confidence=.96,observation='Radio dot beside Topo')))])
            with patch('test_agent.verification.vision_providers.urlopen',return_value=http_reply(**response)) as send:
                await tool.ask('CASE-1',dossiers['CASE-1']['screenshots'][0]['screenshot_id'],
                               'Which layer is selected?',['Standard','Topo','unclear'])
            body=json.loads(send.call_args.args[0].data)
            blocks=body['messages'][0]['content']
            self.assertEqual(sum(b['type']=='image' for b in blocks),1)
            self.assertEqual(blocks[0]['source']['media_type'],'image/png')
            self.assertEqual(blocks[0]['transformations'],{'oversized_image':'error'})
            self.assertNotIn('Topo is selected',json.dumps(body))
            self.assertNotIn('CASE-1',json.dumps(body))
            self.assertNotIn('PASSED',json.dumps(body))

    async def test_evidence_rejections_and_human_fallbacks(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);audit_fixture(root);dossiers=dossiers_from_suite(root)
            d=dossiers['CASE-3'];base=finding(d)
            for changes,expected in [({'evidence_rows':['R9999']},'UNKNOWN_OR_FOREIGN_EVIDENCE'),
                    ({'evidence_screenshots':['S-CASE-1-1']},'UNKNOWN_OR_FOREIGN_EVIDENCE'),
                    ({'evidence_questions':['Q-CASE-3-99']},'UNANSWERED_OR_INVENTED_QUESTION'),
                    ({'likely_cause':'software_bug','recommend_ticket':True,'ticket_type':'bug'},'SOFTWARE_BUG_WITHOUT_FAILED_CHECK'),
                    ({'likely_cause':'environment_problem','recommend_ticket':True,'ticket_type':'bug'},'UNSAFE_TICKET_CATEGORY')]:
                self.assertEqual(validate_finding(Finding.model_validate({**base,**changes}),d,[]),expected)
            # A blocked-only case may discuss a possible bug, without turning it into a bug recommendation.
            self.assertIsNone(validate_finding(Finding.model_validate({**base,'explanation':'Possibly a software bug; needs investigation.'}),d,[]))
            async def absent(d,q): return json.dumps(dict(summary='No findings',findings=[]))
            result=await run_audit_agent(root,analyst=absent,vision=FakeAuditVision())
            self.assertEqual(result['findings'],[])
            self.assertTrue(all(c['status']=='unanalysed' for c in result['case_audits'].values()))
            self.assertTrue(all(f['likely_cause']=='needs_human_review' and not f['recommend_ticket'] for f in result['findings']))
            for bad in ['not JSON',TimeoutError('do not log this secret')]:
                async def invalid(d,q):
                    if isinstance(bad,Exception): raise bad
                    return bad
                result=await run_audit_agent(root,analyst=invalid,vision=FakeAuditVision())
                self.assertTrue(result['agent_unavailable'])
                self.assertNotIn('do not log this secret',json.dumps(result))

    async def test_false_pass_requires_certain_comparable_contradiction_no_ticket(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);audit_fixture(root);dossiers=dossiers_from_suite(root);d=dossiers['CASE-1']
            f=finding(d,cause='possible_false_pass')
            self.assertEqual(validate_finding(Finding.model_validate(f),d,[]),'FALSE_PASS_WITHOUT_CONTRADICTION')
            tool=ScreenshotQuestions(root,dossiers,FakeAuditVision(choice='Standard'))
            answer=await tool.ask('CASE-1',d['screenshots'][0]['screenshot_id'],'Which layer is selected?',
                                  ['Standard','Topo','unclear'])
            self.assertTrue(answer['contradicts_expected'])
            f.update(evidence_questions=[answer['question_id']],evidence_screenshots=[answer['screenshot_id']])
            self.assertIsNone(validate_finding(Finding.model_validate(f),d,tool.questions))
            f.update(recommend_ticket=True,ticket_type='bug')
            self.assertEqual(validate_finding(Finding.model_validate(f),d,tool.questions),'FALSE_PASS_REQUIRES_HUMAN_REVIEW')
            route_dossier={**d,'contract':dict(route_step=1,origin='Hamburg',destination='Berlin',destination_aliases=['Berlin, Germany'])}
            answer.update(question='Which city is the destination marker?',options=['Berlin','Munich','unclear'],choice='Munich')
            self.assertTrue(ScreenshotQuestions.contradiction(route_dossier,d['screenshots'][0],answer))
            answer.update(choice='Berlin, Germany')
            self.assertFalse(ScreenshotQuestions.contradiction(route_dossier,d['screenshots'][0],answer))

    async def test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'suite-fixture';audit_fixture(root)
            async def analyst(d,q):
                f=finding(d,cause='possible_false_pass' if d['status']=='PASSED' else 'needs_human_review')
                if d['status']=='PASSED':
                    answer=await q.ask(d['case_id'],d['screenshots'][0]['screenshot_id'],
                                       'Which layer is selected?',['Standard','Topo','unclear'])
                    f.update(evidence_questions=[answer['question_id']],evidence_screenshots=[answer['screenshot_id']])
                bad={**f,'finding_id':f['finding_id']+'-invented','evidence_questions':['Q-made-up']}
                return json.dumps(dict(summary='Review the possible false pass.',findings=[f,bad]))
            result=await run_audit_agent(root,analyst=analyst,vision=FakeAuditVision(choice='Standard'))
            self.assertEqual(len(result['findings']),3)
            self.assertEqual(len(result['dropped_findings']),3)
            self.assertEqual(result['findings'][0]['likely_cause'],'possible_false_pass')
            preview=approval_preview(root)
            self.assertEqual(preview['possible_false_passes'],['F-CASE-1-1'])
            reports=package_reports(root,Path(temp)/'reports')
            self.assertIn('⚠ possible false pass, please check',(reports/'audit_analysis.md').read_text())
            self.assertIn('⚠ possible false pass, please check',(reports/'report.html').read_text())

    async def test_claude_only_native_tool_loop_covers_all_cases_without_glm(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);audit_fixture(root);requests=[]
            def http(request,timeout):
                body=json.loads(request.data);requests.append(body)
                self.assertEqual(body['model'],'fake-haiku')
                if 'tools' not in body:
                    return http_reply(model='fake-haiku',content=[dict(type='text',text=json.dumps(
                        dict(choice='Topo',confidence=.96,observation='Topo is highlighted.')))])
                dossier=json.loads(body['messages'][0]['content'])['dossier']
                self.assertNotIn('base64',json.dumps(body))
                if len(body['messages'])==1:
                    return http_reply(model='fake-haiku',stop_reason='tool_use',content=[dict(type='tool_use',
                        id='read-'+dossier['case_id'],name='ask_screenshot',input=dict(
                            screenshot_id=dossier['screenshots'][0]['screenshot_id'],question='Which layer is selected?',
                            options=['Standard','Topo','unclear']))])
                result=body['messages'][-1]['content'][0]
                self.assertEqual(result['tool_use_id'],'read-'+dossier['case_id'])
                observation=json.loads(result['content'])
                f=finding(dossier)
                f.update(evidence_questions=[observation['question_id']],screenshot_observations=observation['observation'],
                         evidence_screenshots=[observation['screenshot_id']])
                if dossier['status']=='FAILED':
                    f.update(likely_cause='test_case_problem',recommend_ticket=True,ticket_type='test_case_fix')
                return http_reply(model='fake-haiku',stop_reason='tool_use',content=[dict(type='tool_use',
                    id='submit-'+dossier['case_id'],name='submit_analysis',input=dict(summary='Claude draft.',findings=[f]))])
            with patch.dict(os.environ,{'ANTHROPIC_API_KEY':'fake','AUDIT_MODEL':'fake-haiku'},clear=True),patch(
                    'test_agent.verification.vision_providers.urlopen',side_effect=http):
                result=await run_audit_agent(root)
            self.assertFalse(result['agent_unavailable'],result['dropped_findings'])
            self.assertEqual(len(result['findings']),3)
            self.assertEqual(len(requests),9)  # Two analysis turns + one blind image request per case.
            self.assertEqual(result['text_model'],'fake-haiku')
            self.assertEqual(result['vision_model'],'fake-haiku')
            self.assertEqual(result['provider'],'anthropic')
            self.assertIn('Ticket: not recommended',(root/'audit_analysis.md').read_text())
            self.assertIn('Ticket: recommended (Test case fix)',(root/'audit_analysis.md').read_text())

    async def test_native_tool_errors_limits_and_incomplete_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);audit_fixture(root);d=dossiers_from_suite(root)['CASE-1']
            provider=FakeAuditVision()
            questions=ScreenshotQuestions(root,{'CASE-1':d},provider)
            def tool(call_id,name,arguments):
                return dict(model='fake-haiku',stop_reason='tool_use',blocks=[dict(type='tool_use',
                    id=call_id,name=name,input=arguments)])
            provider.request_message=AsyncMock(side_effect=[tool('bad-args','ask_screenshot',{}),
                tool('bad-name','write_ticket',{}),dict(model='fake-haiku',stop_reason='end_turn',blocks=[dict(type='text',text='{}')])])
            with self.assertRaises(VisionError) as error:await claude_analyze(d,questions)
            self.assertEqual(error.exception.code,'SUBMIT_REQUIRED')
            self.assertFalse(provider.calls)
            calls=provider.request_message.call_args_list
            self.assertIn('AUDIT_TOOL_ARGUMENTS',str(calls[1]))
            self.assertIn('AUDIT_UNKNOWN_TOOL',str(calls[2]))
            provider.request_message=AsyncMock(return_value=dict(model='fake-haiku',stop_reason='max_tokens',blocks=[]))
            with self.assertRaises(VisionError) as error:await claude_analyze(d,questions)
            self.assertEqual(error.exception.code,'INCOMPLETE')
            provider.request_message=AsyncMock(side_effect=[tool(str(n),'ask_screenshot',dict(
                screenshot_id='invented',question='Which layer?',options=['Standard','Topo','unclear'])) for n in range(12)])
            with self.assertRaises(VisionError) as error:await claude_analyze(d,questions)
            self.assertEqual(error.exception.code,'TURN_LIMIT')
            self.assertEqual(provider.request_message.await_count,12)
            # A first invalid submission on turn 12 still gets exactly one repair turn.
            blocked=dossiers_from_suite(root)['CASE-3']
            questions=ScreenshotQuestions(root,{'CASE-3':blocked},provider)
            valid=dict(summary='Explained environment issue.',findings=[finding(blocked,cause='environment_problem')])
            invalid={**valid,'summary':42}
            provider.request_message=AsyncMock(side_effect=[tool('unknown-'+str(n),'unknown',{}) for n in range(11)]+
                [tool('first-submit','submit_analysis',invalid),tool('repair-submit','submit_analysis',valid)])
            repaired=json.loads(await claude_analyze(blocked,questions))
            self.assertEqual(len(repaired['findings']),1)
            self.assertEqual(provider.request_message.await_count,13)
            self.assertEqual(questions.validation_drops[0]['field_errors'],[dict(field='summary',type='string_type')])
            self.assertTrue(questions.repairs['CASE-3'])

    async def test_missing_claude_key_never_uses_glm_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);audit_fixture(root)
            with patch.dict(os.environ,{'OPENAI_API_KEY':'must-not-be-used','OPENAI_MODEL':'glm'},clear=True),patch(
                    'test_agent.verification.vision_providers.urlopen') as send:
                result=await run_audit_agent(root)
            send.assert_not_called()
            self.assertTrue(result['agent_unavailable'])
            self.assertEqual(result['findings'],[])
            self.assertTrue(all(c['status']=='unanalysed' for c in result['case_audits'].values()))
            self.assertEqual(result['dropped_findings'][0]['provider_code'],'VISION_CONFIG')
            self.assertNotIn('must-not-be-used',json.dumps(result))
            with patch.dict(os.environ,{'AUDIT_VISION_MODEL':'old-name'},clear=True):
                self.assertEqual(audit_model(),'old-name')
                with patch.dict(os.environ,{'AUDIT_MODEL':'new-name'}):self.assertEqual(audit_model(),'new-name')


    async def test_native_one_repair_and_safe_field_errors(self):
        from test_agent.schemas.audit_analysis import submission_schema
        for repair_succeeds in [True,False]:
            with self.subTest(repair_succeeds=repair_succeeds),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);audit_fixture(root);provider=FakeAuditVision();results=[]
                async def request(messages,instructions,**kwargs):
                    dossier=json.loads(messages[0]['content'])['dossier']
                    schema=kwargs['tools'][1]
                    self.assertTrue(schema['strict'])
                    self.assertEqual(schema['input_schema'],submission_schema())
                    self.assertEqual(set(schema['input_schema']['properties']),{'summary','findings'})
                    def assert_supported(node):
                        if isinstance(node,dict):
                            self.assertFalse(set(node) & {'minimum','maximum','minLength','maxLength','maxItems'})
                            for v in node.values():assert_supported(v)
                        elif isinstance(node,list):
                            for v in node:assert_supported(v)
                    assert_supported(schema['input_schema'])
                    turn=len(messages)//2
                    if turn==0:
                        name='ask_screenshot';arguments=dict(screenshot_id=dossier['screenshots'][0]['screenshot_id'],
                            question='Which layer is selected?',options=['Standard','Topo','unclear'])
                    else:
                        name='submit_analysis';f=finding(dossier,cause='confirmed_pass' if dossier['status']=='PASSED' else 'environment_problem')
                        f.update(evidence_questions=['Q-'+dossier['case_id']+'-1'])
                        f.update(title='t'*200,explanation='e'*1000,screenshot_observations='o'*600,
                                 suggested_next_step='n'*500)
                        if turn==1 or not repair_succeeds:
                            f['likely_cause']='SECRET_PRIVATE_CONTENT'
                        arguments=dict(summary='s'*1200,findings=[f])
                        if turn==2:
                            result=messages[-1]['content'][0]
                            self.assertTrue(result['is_error'])
                            self.assertEqual(result['tool_use_id'],'submit_analysis-1')
                            diagnostics=json.loads(result['content'])['field_errors']
                            self.assertEqual(diagnostics,[dict(field='findings.0.likely_cause',type='literal_error')])
                            self.assertNotIn('SECRET_PRIVATE_CONTENT',result['content'])
                            results.append(result)
                    return dict(model='fake-haiku',stop_reason='tool_use',blocks=[dict(type='tool_use',
                        id=name+'-'+str(turn),name=name,input=arguments)])
                provider.request_message=AsyncMock(side_effect=request)
                a=await run_audit_agent(root,vision=provider)
                self.assertTrue(a['repair_used'])
                self.assertEqual(provider.request_message.await_count,9)
                self.assertEqual(len(results),3)
                self.assertNotIn('SECRET_PRIVATE_CONTENT',json.dumps(a))
                self.assertTrue(all(d.get('field_errors') for d in a['dropped_findings'] if d['reason'] in {'AUDIT_SCHEMA','FINDING_SCHEMA'}))
                self.assertTrue(all(c['repair_used'] for c in a['case_audits'].values()))
                if repair_succeeds:
                    self.assertFalse(a['agent_unavailable'],a['dropped_findings'])
                    self.assertEqual(len(a['findings']),3)
                    f=a['findings'][0]
                    for field,size in [('title',120),('explanation',800),('screenshot_observations',400),('suggested_next_step',300)]:
                        self.assertEqual(len(f[field]),size)
                else:
                    self.assertTrue(a['agent_unavailable'])
                    self.assertEqual(a['findings'],[])
                    text=(root/'audit_analysis.md').read_text()
                    self.assertEqual(text.count('AI audit unavailable.'),1)
                    self.assertNotIn('Human review needed',text)
                    self.assertEqual(approval_preview(root)['candidates'],[])

    async def test_envelope_diagnostics_and_attention_groups(self):
        from test_agent.audit_validation import validate_submission
        from test_agent.audit_presentation import presentation,html_audit
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);audit_fixture(root);dossiers=dossiers_from_suite(root)
            for payload,field,error in [({'summary':42,'findings':[]},'summary','string_type'),
                    ({'summary':'ok','findings':'SECRET'},'findings','list_type'),
                    ({'summary':'ok','findings':[],'SECRET_KEY':'SECRET'},'<extra>','extra_forbidden')]:
                _,_,drops=validate_submission(payload,dossiers['CASE-1'],[])
                self.assertEqual(drops[0]['reason'],'AUDIT_SCHEMA')
                self.assertIn(dict(field=field,type=error),drops[0]['field_errors'])
                self.assertNotIn('SECRET',json.dumps(drops))
            async def analyst(d,q):
                raw=json.loads(await fake_analyst(d,q))
                if d['status']=='BLOCKED':raw['findings'][0]['likely_cause']='environment_problem'
                return json.dumps(raw)
            a=await run_audit_agent(root,analyst=analyst,vision=FakeAuditVision())
            view=presentation(a);preview=approval_preview(root)
            expected='Audited 3 cases: 2 no action, 1 needs your attention (1 ticket suggestion).'
            self.assertEqual(view['summary'],expected)
            self.assertEqual(preview['summary'],expected)
            self.assertEqual(preview['attention_count'],1)
            self.assertEqual(preview['attention_details'],['CASE-2: test_case_problem (medium)'])
            self.assertEqual(len(preview['candidates']),1)
            text=(root/'audit_analysis.md').read_text()
            self.assertLess(text.index('F-CASE-2-1'),text.index('<summary>No action needed</summary>'))
            self.assertGreater(text.index('F-CASE-1-1'),text.index('<summary>No action needed</summary>'))
            html=html_audit(a)
            self.assertIn(expected,html)
            self.assertNotIn('<details open',html)
            self.assertLess(html.index('F-CASE-2-1'),html.index('<details>'))
            a['findings'][1].update(recommend_ticket=False,ticket_type=None)
            for cause,confidence,count in [('environment_problem','medium',0),('environment_problem','low',1),
                    ('needs_human_review','medium',1)]:
                a['findings'][1].update(likely_cause=cause,confidence=confidence)
                (root/'audit_analysis.json').write_text(json.dumps(a))
                preview=approval_preview(root)
                self.assertEqual(preview['candidates'],[])
                self.assertEqual(preview['attention_count'],count)
            a['case_audits']['CASE-1']=dict(status='unanalysed',reason='AUDIT_SCHEMA',repair_used=True)
            a['findings']=a['findings'][1:]
            a['agent_unavailable']=True
            view=presentation(a)
            self.assertEqual(view['unanalysed_count'],1)
            self.assertEqual(view['attention_count'],1)
            self.assertEqual(html_audit(a).count('AI audit unavailable.'),1)


class AuditCliTests(unittest.TestCase):
    def test_ci_unavailable_mode_never_calls_models_and_still_writes_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);suite=root/'suite-fixture';audit_fixture(suite)
            with patch.dict(os.environ,{},clear=True),patch('test_agent.audit_agent.claude_analyze',new=AsyncMock()) as model,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--project-dir',temp,'audit-agent',str(suite),'--unavailable']),0)
            model.assert_not_awaited()
            result=json.loads((suite/'audit_analysis.json').read_text())
            self.assertTrue(result['agent_unavailable'])
            self.assertEqual(result['findings'],[])
            self.assertEqual(result['questions'],[])
            self.assertEqual(json.loads((suite/'audit_review.json').read_text())['candidates'],[])
