"""One attention policy shared by Markdown, HTML and Jenkins approval metadata."""
from html import escape
from test_agent.audit_validation import ticket_type_for


def presentation(analysis):
    attention, quiet = [], []
    cases = analysis.get('cases',{})
    for f in analysis.get('findings',[]):
        needed = (ticket_type_for(f,cases[f['case_id']]) or f['likely_cause'] in {'possible_false_pass','needs_human_review'} or
                  (cases[f['case_id']]['status'] in {'FAILED','BLOCKED'} and f['confidence']=='low'))
        (attention if needed else quiet).append(f)
    covered = {f['case_id'] for f in attention+quiet}
    attention_cases = {f['case_id'] for f in attention}
    tickets = sum(bool(ticket_type_for(f,cases[f['case_id']])) for f in attention)
    summary = (f'Audited {len(covered)} '+('case' if len(covered)==1 else 'cases')+f': {len(covered-attention_cases)} no action, '
               f'{len(attention_cases)} needs your attention ({tickets} ticket suggestion'+('' if tickets==1 else 's')+').')
    missing = len(cases)-len(covered)
    if missing:
        summary += f' {missing} unanalysed.'
    unanalysed = [case_id+' unanalysed ('+str(analysis.get('case_audits',{}).get(case_id,{}).get('reason') or 'AUDIT_UNAVAILABLE')+')'
                  for case_id in cases if case_id not in covered]
    if covered and missing:
        banner = f'AI audit analysed {len(covered)} of {len(cases)} cases; '+', '.join(unanalysed)+'.'
    elif not covered:
        banner = ('AI audit unavailable. Test results are unchanged; read the report as usual. Reason: '+
                  (', '.join(unanalysed) or 'AUDIT_UNAVAILABLE'))
    else:
        banner = ''
    return dict(summary=summary,attention=attention,no_action=quiet,attention_count=len(attention),
                ticket_count=tickets,unanalysed_count=missing,banner=banner)


def credential_warning(analysis):
    """Only controlled auth codes; never expose provider messages or credentials."""
    errors = [*analysis.get('dropped_findings',[]), *analysis.get('questions',[])]
    statuses = sorted({e['http_status'] for e in errors
        if (e.get('provider_code')=='VISION_HTTP' or e.get('code')=='VISION_HTTP')
        and type(e.get('http_status')) is int and e['http_status'] in {401,403}})
    return '; '.join(f'Anthropic credential rejected ({status}): update `wbs-anthropic-api-key`'
                     for status in statuses)


def html_audit(analysis):
    view = presentation(analysis)
    def card(f):
        text = (f['finding_id']+' · '+f['case_id']+' · '+f['title']+' — '+f['likely_cause']+
                ' ('+f['confidence']+'). '+f['explanation']+' AI ticket advice: '+str(f['recommend_ticket'])+' Next: '+f['suggested_next_step']+
                (' Ticket suggestion: approval required.' if ticket_type_for(f,analysis['cases'][f['case_id']]) else '')+
                (' ⚠ possible false pass, please check.' if f['likely_cause']=='possible_false_pass' else ''))
        return '<p>'+escape(text)+'</p>'
    return ('<section aria-label="AI audit"><h2>AI audit</h2><p>'+escape(view['summary'])+'</p>'+
            ('<p class="plain-summary">'+escape(view['banner'])+'</p>' if view['banner'] else '')+
            '<h3>Needs your attention</h3>'+(''.join(map(card,view['attention'])) or '<p>None.</p>')+
            '<details><summary>No action needed</summary>'+''.join(map(card,view['no_action']))+'</details></section>')


APPROVAL_MESSAGE = ("AI audit requires human approval. Tick the test case(s) you want to report, then click "
                    "'Create Jira ticket'. Unticked items are not created.")
CAUSE_NAMES = dict(software_bug='Software bug',test_case_problem='Test case problem',
    test_tool_problem='Test tool problem',environment_problem='Environment problem',
    possible_false_pass='Possible false pass',needs_human_review='Needs human review',confirmed_pass='Confirmed pass')


def approval_dialog(analysis, suite_summary):
    cases = suite_summary.get('cases',[])
    counts = {s:sum(c.get('status')==s for c in cases) for s in ['PASSED','FAILED','BLOCKED']}
    summary = (f"Total TC: {len(cases)}; Passed: {counts['PASSED']}; Failed: {counts['FAILED']}; Blocked: {counts['BLOCKED']}")
    candidates = []
    for f in analysis.get('findings',[]):
        if not ticket_type_for(f,analysis['cases'][f['case_id']]):
            continue
        reason = ' '.join(f['short_reason'].split())[:160]
        candidates.append(dict(finding_id=f['finding_id'],description=escape(
            f"{f['finding_id']} | {f['case_id']} | Cause: {CAUSE_NAMES[f['likely_cause']]} | "
            f"Confidence: {f['confidence']} | Reason: {reason}",quote=True)))
    return dict(approval_message=APPROVAL_MESSAGE,suite_summary=summary,candidates=candidates)
