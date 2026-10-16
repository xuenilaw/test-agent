"""One attention policy shared by Markdown, HTML and Jenkins approval metadata."""
from html import escape


def presentation(analysis):
    attention, quiet = [], []
    cases = analysis.get('cases',{})
    for f in analysis.get('findings',[]):
        needed = (f['recommend_ticket'] or f['likely_cause'] in {'possible_false_pass','needs_human_review'} or
                  (cases[f['case_id']]['status'] in {'FAILED','BLOCKED'} and f['confidence']=='low'))
        (attention if needed else quiet).append(f)
    covered = {f['case_id'] for f in attention+quiet}
    attention_cases = {f['case_id'] for f in attention}
    tickets = sum(f['recommend_ticket'] for f in attention)
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
                ' ('+f['confidence']+'). '+f['explanation']+' Next: '+f['suggested_next_step']+
                (' Ticket suggestion: approval required.' if f['recommend_ticket'] else '')+
                (' ⚠ possible false pass, please check.' if f['likely_cause']=='possible_false_pass' else ''))
        return '<p>'+escape(text)+'</p>'
    return ('<section aria-label="AI audit"><h2>AI audit</h2><p>'+escape(view['summary'])+'</p>'+
            ('<p class="plain-summary">'+escape(view['banner'])+'</p>' if view['banner'] else '')+
            '<h3>Needs your attention</h3>'+(''.join(map(card,view['attention'])) or '<p>None.</p>')+
            '<details><summary>No action needed</summary>'+''.join(map(card,view['no_action']))+'</details></section>')
