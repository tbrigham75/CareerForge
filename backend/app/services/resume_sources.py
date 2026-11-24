"""One source eligibility policy for the resume screen and AI generation."""
from collections import Counter
from datetime import date
from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import Accomplishment


def capture_draft(proposal, form):
    """Keep index-based legacy forms compatible; cards never reorder on refresh."""
    result = deepcopy(proposal)
    for index, bullet in enumerate(result['bullets']):
        bullet.setdefault('generated_text', bullet['text'])
        bullet['text'] = str(form.get('bullet_' + str(index), bullet['text']))[:1500]
        bullet.setdefault('source_versions', {
            key: proposal['sources'][key]['updated'] for key in bullet.get('source_ids', [])
        })
    result['selected'] = [str(i) for i in range(len(result['bullets'])) if str(i) in form.getlist('selected')]
    result['suppressed'] = [str(i) for i in range(len(result['bullets'])) if str(i) in form.getlist('suppress')]
    return result


def card_is_stale(bullet, proposal, eligible):
    versions = bullet.get('source_versions', {
        key: source['updated'] for key, source in proposal.get('sources', {}).items()
    })
    return any(key not in eligible or eligible[key]['updated'] != versions.get(key)
               for key in bullet.get('source_ids', []))


def merge_proposal(previous, fresh, focused=False):
    """Append new alternatives; never overwrite wording, selection or source evidence."""
    if not previous:
        fresh['selected'] = []  # Every insertion or replacement is an explicit choice.
        return fresh
    merged = deepcopy(fresh)
    merged['bullets'] = deepcopy(previous['bullets'])
    for bullet in merged['bullets']:
        bullet.setdefault('source_versions', {key: previous['sources'][key]['updated'] for key in bullet.get('source_ids', [])})
        bullet.setdefault('evidence', {key: previous['sources'][key] for key in bullet.get('source_ids', [])})
    # Comparing original AI wording also avoids duplicates after a user edits a card.
    def signature(bullet):
        return (bullet.get('kind', 'add'), tuple(sorted(bullet.get('targets', []))),
                tuple(sorted(bullet.get('source_ids', []))),
                tuple(sorted(bullet.get('source_versions', {}).items())),
                bullet.get('generated_text', bullet['text']).strip().casefold())
    seen = {signature(bullet) for bullet in merged['bullets']}
    added = 0
    for bullet in fresh['bullets']:
        if signature(bullet) not in seen:
            merged['bullets'].append(dict(bullet, new=True))
            seen.add(signature(bullet))
            added += 1
    merged['selected'] = list(previous.get('selected', []))
    merged['suppressed'] = list(previous.get('suppressed', []))
    merged['sources'] = dict(previous.get('sources', {}), **fresh['sources'])
    for field in ('source_feedback', 'filtered_sources', 'nomination_feedback', 'source_outcomes'):
        # Reviewed sources get fresh explanations; don't retain an old duplicate
        # filter or an obsolete model verdict after the facts change.
        retained = {key: value for key, value in previous.get(field, {}).items() if key not in fresh['sources']}
        merged[field] = dict(retained, **fresh.get(field, {}))
    if focused:
        merged['reviewed_sources'] = dict(previous.get('reviewed_sources', previous.get('sources', {})), **fresh['sources'])
    else:
        merged['reviewed_sources'] = fresh['sources']
    merged['last_added'] = added
    return merged


def workspace(candidates, proposal=None):
    """Live inventory and freshness are independent of the saved AI shortlist."""
    proposal = proposal or {}
    eligible = candidates['eligible']
    snapshot = proposal.get('reviewed_sources', proposal.get('sources', {}))
    new = [key for key in eligible if key not in snapshot]
    changed = [key for key in eligible if key in snapshot and eligible[key]['updated'] != snapshot[key]['updated']]
    removed = [key for key in snapshot if key not in eligible]
    stale = [i for i, bullet in enumerate(proposal.get('bullets', [])) if card_is_stale(bullet, proposal, eligible)]
    ready, represented, review = [], [], []
    for key, source in eligible.items():
        cards = [(i, bullet) for i, bullet in enumerate(proposal.get('bullets', [])) if key in bullet.get('source_ids', []) and i not in stale]
        outcome = 'Ready to explore'
        if cards:
            outcome = 'Alternative available' if all(b.get('alternative') for _, b in cards) else 'Recommended'
            if any(len(b.get('source_ids', [])) > 1 for _, b in cards):
                outcome += ' · grouped with related work'
        elif key in new and proposal:
            outcome = 'Newly available'
        elif key in changed:
            outcome = 'Source changed · refresh wording'
        elif proposal.get('source_outcomes', {}).get(key) == 'already_covered':
            outcome = 'AI assessment: already covered'
        elif proposal.get('source_outcomes', {}).get(key) == 'needs_clarification':
            outcome = 'AI assessment: needs clarification'
        reason = proposal.get('source_feedback', {}).get(key, '')
        reason_origin = 'AI feedback'
        if key in proposal.get('filtered_sources', {}):
            reason = 'A proposed addition resembled existing wording. You can request another option.'
            reason_origin = 'Application check'
        ready.append(dict(source, id=key, outcome=outcome, reason=reason, reason_origin=reason_origin, cards=[i + 1 for i, _ in cards]))
    for source in candidates['excluded']:
        (represented if source['reason'] == 'Already incorporated; no source changes' else review).append(source)
    recommended = sum(i not in stale and not b.get('alternative') for i, b in enumerate(proposal.get('bullets', [])))
    return {'ready': ready, 'review': review, 'represented': represented, 'new': new, 'changed': changed,
            'removed': removed, 'stale': stale, 'recommended': recommended,
            'selected': len(proposal.get('selected', []))}


def recommendation_summary(proposal):
    """Count actual validated recommendations, never model-provided totals."""
    sources = proposal.get('sources', {})
    changes = proposal.get('bullets', [])
    covered = {source_id for change in changes for source_id in change.get('source_ids', []) if source_id in sources}
    feedback = proposal.get('source_feedback', {})
    if not isinstance(feedback, dict):
        feedback = {}
    filtered = proposal.get('filtered_sources', {})
    if not isinstance(filtered, dict):
        filtered = {}
    omitted = []
    for source_id, source in sources.items():
        if source_id in covered:
            continue
        reason = feedback.get(source_id)
        explanation = reason.strip()[:1000] if isinstance(reason, str) else ''
        if source_id in filtered:
            explanation = 'The proposed addition repeated or closely resembled existing resume text or another suggested addition.'
            origin = 'Application check'
        elif explanation:
            origin = 'AI explanation'
        else:
            explanation = 'The AI did not provide a reason for leaving this accomplishment out. It remains available for another update.'
            origin = 'Reason unavailable'
        omitted.append({'id': source_id, 'title': source['title'], 'reason': explanation, 'origin': origin})
    return {'reviewed': len(sources), 'changes': len(changes), 'covered': len(covered),
            'omitted': omitted, 'kinds': dict(Counter(change.get('kind', 'add') for change in changes))}


def exclusion_reason(record, state, today):
    if record.deleted_at:
        return 'In Trash'
    if not record.date_completed:
        return 'Completion date missing'
    if record.date_completed.year != today.year:
        return 'Completed outside this calendar year'
    if record.date_completed > today:
        return 'Completion date is in the future'
    if record.status not in {'completed', 'archived'}:
        return 'Not completed'
    if record.approval_status != 'approved':
        return 'Needs approval'
    if not record.report_inclusion:
        return 'Include in reports is turned off'
    if record.id in state.get('rejected', []):
        return 'You chose not to suggest this source again'
    if record.id in state.get('used', []) and state.get('source_revisions', {}).get(record.id) == record.updated_at.isoformat():
        return 'Already incorporated; no source changes'
    return ''


def catalog(session, state, today: date):
    eligible, excluded, counts = {}, [], Counter()
    records = session.scalars(select(Accomplishment).options(selectinload(Accomplishment.projects)).where(
        Accomplishment.deleted_at.is_(None)).order_by(Accomplishment.date_completed.desc(), Accomplishment.id))
    for record in records:
        reason = exclusion_reason(record, state, today)
        if reason:
            counts[reason] += 1
            # Keep older years summarized rather than overwhelming the current-year review.
            if record.date_completed is None or record.date_completed.year == today.year:
                excluded.append({'id': record.id, 'title': record.title, 'reason': reason,
                                 'status': record.status, 'approval': record.approval_status})
            continue
        eligible[record.id] = {
            'title': record.title, 'action': record.action, 'metric': record.metric,
            'impact': record.impact, 'organization': record.organization,
            'projects': [project.name for project in record.projects],
            'completed': record.date_completed.isoformat(), 'updated': record.updated_at.isoformat(),
        }
    return {'eligible': eligible, 'excluded': excluded, 'counts': dict(counts), 'year': today.year}
