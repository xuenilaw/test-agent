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
    summary = (f'Audited {len(covered)} cases: {len(covered-attention_cases)} no action, '
               f'{len(attention_cases)} needs your attention ({tickets} ticket suggestion'+('' if tickets==1 else 's')+').')
    missing = len(cases)-len(covered)
    if missing:
        summary += f' {missing} unanalysed.'
    reasons = sorted({d.get('reason','AUDIT_UNAVAILABLE') for d in analysis.get('case_audits',{}).values()
                      if d['status']=='unanalysed'})
    banner = ('AI audit unavailable. Test results are unchanged; read the report as usual. Reason: '+
              ', '.join(reasons or ['AUDIT_UNAVAILABLE'])) if missing or analysis.get('agent_unavailable') else ''
    return dict(summary=summary,attention=attention,no_action=quiet,attention_count=len(attention),
                ticket_count=tickets,unanalysed_count=missing,banner=banner)


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
