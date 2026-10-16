"""Evidence and ticket guards; the analyst, not these rules, diagnoses causes."""
import re
from pydantic import ValidationError
from test_agent.schemas.audit_analysis import Finding, Alternative, AnalysisEnvelope


def validate_finding(finding: Finding, dossier, questions):
    f = finding.model_dump()
    rows = {r['row_id']: r for r in dossier['rows']}
    shots = {s['screenshot_id'] for s in dossier['screenshots']}
    answered = {q['question_id']: q for q in questions if q['case_id'] == dossier['case_id'] and q['answered']}
    if f['case_id'] != dossier['case_id']:
        return 'CASE_MISMATCH'
    if f['step'] is not None and f['step'] not in {s['number'] for s in dossier['test_case'].get('actions', [])}:
        return 'UNKNOWN_STEP'
    if not set(f['evidence_rows']) <= rows.keys() or not set(f['evidence_screenshots']) <= shots:
        return 'UNKNOWN_OR_FOREIGN_EVIDENCE'
    if not set(f['evidence_questions']) <= answered.keys():
        return 'UNANSWERED_OR_INVENTED_QUESTION'
    if not f['evidence_rows'] and not f['evidence_questions']:
        return 'NO_OBSERVED_EVIDENCE'
    if f['screenshot_observations'] and not f['evidence_questions']:
        return 'UNOBSERVED_SCREENSHOT_CLAIM'
    selected = [rows[i] for i in f['evidence_rows']]
    cited = [answered[i] for i in f['evidence_questions']]
    if any(q['status'] != 'certain' for q in cited) and f['confidence'] == 'high':
        return 'UNCERTAIN_VISION_NOT_FACT'
    if dossier['status'] == 'PASSED' and f['likely_cause'] not in {'confirmed_pass','possible_false_pass','needs_human_review'}:
        return 'PASSED_CASE_NEEDS_PASS_REVIEW'
    if dossier['status'] != 'PASSED' and f['likely_cause'] == 'confirmed_pass':
        return 'NONPASS_CANNOT_BE_CONFIRMED_PASS'
    if f['likely_cause'] == 'confirmed_pass' and f['confidence'] == 'low':
        return 'LOW_CONFIDENCE_PASS_REQUIRES_REVIEW'
    if f['likely_cause'] == 'needs_human_review' and not f['explanation'].strip():
        return 'REVIEW_REASON_REQUIRED'
    if f['likely_cause'] == 'confirmed_pass' and dossier['screenshots'] and (not cited or any(q['status'] != 'certain' for q in cited)):
        return 'PASS_SCREENSHOT_NOT_CONFIRMED'
    def substantive_failure(row):
        return row['status'] == 'FAILED' and row['row_type'] == 'check' and not re.match(
            r'^(TRANSLATION_REJECTED|NAVIGATION|FORM_NOT_READY|SUBMIT_NO_EFFECT|HEAL_FAILED|VISION_)', row['reason_code'])
    if f['likely_cause'] == 'possible_false_pass':
        if not any(substantive_failure(r) for r in selected) and not any(q.get('contradicts_expected') for q in cited):
            return 'FALSE_PASS_WITHOUT_CONTRADICTION'
        if f['recommend_ticket'] or f['ticket_type'] is not None:
            return 'FALSE_PASS_REQUIRES_HUMAN_REVIEW'
    if f['likely_cause'] == 'software_bug' and not any(substantive_failure(r) for r in selected):
        return 'SOFTWARE_BUG_WITHOUT_FAILED_CHECK'
    if f['recommend_ticket']:
        required = {'bug':'software_bug', 'test_case_fix':'test_case_problem'}.get(f['ticket_type'])
        if required != f['likely_cause']:
            return 'UNSAFE_TICKET_CATEGORY'
    elif f['ticket_type'] is not None:
        return 'TICKET_TYPE_WITHOUT_RECOMMENDATION'
    return None


def field_errors(exc, prefix=()):
    """Never persist input values, custom messages, contexts or unknown extra keys."""
    names = set(Finding.model_fields) | set(Alternative.model_fields) | set(AnalysisEnvelope.model_fields)
    return [dict(field='.'.join(str(x) if isinstance(x,int) or x in names else '<extra>'
                               for x in (*prefix,*error['loc'])) or '$', type=error['type'])
            for error in exc.errors(include_input=False,include_context=False,include_url=False)]


def validate_submission(payload, dossier, questions, known_ids=()):
    drops, accepted, ids = [], [], set(known_ids)
    case_id = dossier['case_id']
    try:
        envelope = AnalysisEnvelope.model_validate(payload)
    except ValidationError as exc:
        return '', [], [dict(finding_id='unavailable',case_id=case_id,reason='AUDIT_SCHEMA',field_errors=field_errors(exc))]
    for index,item in enumerate(envelope.findings):
        try:
            finding = Finding.model_validate(item)
        except ValidationError as exc:
            drops.append(dict(finding_id='item-'+str(index),case_id=case_id,reason='FINDING_SCHEMA',
                              field_errors=field_errors(exc,('findings',index))))
            continue
        error = validate_finding(finding,dossier,questions)
        if finding.finding_id in ids:
            error = 'DUPLICATE_FINDING_ID'
        if error:
            drops.append(dict(finding_id=finding.finding_id,case_id=case_id,reason=error,
                              field_errors=[dict(field=f'findings.{index}',type=error)]))
        else:
            accepted.append(finding.model_dump()); ids.add(finding.finding_id)
    return envelope.summary, accepted, drops
