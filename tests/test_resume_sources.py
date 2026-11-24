"""Source eligibility regression cases. Prepared for the user's test run."""
from datetime import date, datetime, UTC
from types import SimpleNamespace

from app.services.resume_sources import exclusion_reason


def record(**changes):
    values = dict(id='example', deleted_at=None, date_completed=date(2026, 6, 1),
                  status='completed', approval_status='approved', report_inclusion=True,
                  updated_at=datetime(2026, 6, 2, tzinfo=UTC), metric='')
    values.update(changes)
    return SimpleNamespace(**values)


def test_qualitative_accomplishment_is_eligible():
    assert exclusion_reason(record(), {}, date(2026, 11, 10)) == ''


def test_report_exclusion_is_explained():
    assert exclusion_reason(record(report_inclusion=False), {}, date(2026, 11, 10)) == 'Include in reports is turned off'


def test_editing_old_work_does_not_make_it_current_year():
    assert exclusion_reason(record(date_completed=date(2025, 12, 1)), {}, date(2026, 11, 10)) == 'Completed outside this calendar year'


def test_used_source_is_reconsidered_only_when_changed():
    source = record()
    state = {'used': ['example'], 'source_revisions': {'example': source.updated_at.isoformat()}}
    assert exclusion_reason(source, state, date(2026, 11, 10)) == 'Already incorporated; no source changes'
    source.updated_at = datetime(2026, 7, 1, tzinfo=UTC)
    assert exclusion_reason(source, state, date(2026, 11, 10)) == ''


def test_suppression_is_explicit_and_future_dates_are_excluded():
    assert exclusion_reason(record(), {'rejected': ['example']}, date(2026, 11, 10)) == 'You chose not to suggest this source again'
    assert exclusion_reason(record(date_completed=date(2026, 12, 1)), {}, date(2026, 11, 10)) == 'Completion date is in the future'


def test_recommendation_summary_counts_unique_sources_and_all_changes():
    from app.services.resume_sources import recommendation_summary
    proposal = {'sources': {key: {'title': key} for key in ('a', 'b', 'c', 'd')},
                'bullets': [{'kind': 'add', 'source_ids': ['a', 'a', 'b']},
                            {'kind': 'replace', 'source_ids': ['b']},
                            {'kind': 'remove', 'source_ids': []}],
                'source_feedback': {'c': 'Less relevant to the confirmed role.'}}
    summary = recommendation_summary(proposal)
    assert (summary['reviewed'], summary['changes'], summary['covered']) == (4, 3, 2)
    assert summary['kinds'] == {'add': 1, 'replace': 1, 'remove': 1}
    assert [item['id'] for item in summary['omitted']] == ['c', 'd']
    assert summary['omitted'][0]['origin'] == 'AI explanation'
    assert summary['omitted'][1]['origin'] == 'Reason unavailable'


def test_filtered_duplicates_use_application_explanation():
    from app.services.resume_sources import recommendation_summary
    summary = recommendation_summary({'sources': {'a': {'title': 'Assessment'}}, 'bullets': [],
                                      'filtered_sources': {'a': True},
                                      'source_feedback': {'a': 'Unsupported model explanation'}})
    assert summary['omitted'][0]['origin'] == 'Application check'
    assert 'repeated' in summary['omitted'][0]['reason']
    assert summary['covered'] == 0


def test_legacy_and_empty_proposals_need_no_migration():
    from app.services.resume_sources import recommendation_summary
    assert recommendation_summary({})['reviewed'] == 0
    legacy = recommendation_summary({'sources': {'a': {'title': 'Source'}}, 'bullets': []})
    assert legacy['omitted'][0]['origin'] == 'Reason unavailable'


def test_entry_date_default_preserves_original_date_and_explicit_override(monkeypatch):
    from datetime import date, datetime, UTC
    from types import SimpleNamespace
    from app.schemas import AccomplishmentInput
    from app.services import accomplishments
    monkeypatch.setattr(accomplishments.reporting_year, 'preferences', lambda session: SimpleNamespace(timezone='America/Denver'))
    record = SimpleNamespace(created_at=datetime(2026, 11, 5, 1, tzinfo=UTC), date_completed=None)
    result = accomplishments.default_completion(None, AccomplishmentInput(), record)
    assert result.date_completed == date(2026, 11, 4)
    record.date_completed = date(2025, 8, 1)
    assert accomplishments.default_completion(None, AccomplishmentInput(), record).date_completed == date(2025, 8, 1)
    explicit = AccomplishmentInput(date_completed=date(2026, 2, 1))
    assert accomplishments.default_completion(None, explicit, record).date_completed == date(2026, 2, 1)


def source(key, updated='v1'):
    return {'title': key, 'updated': updated}


def test_live_inventory_does_not_hide_new_work_behind_a_saved_shortlist():
    from app.services.resume_sources import workspace
    candidates = {'eligible': {key: source(key) for key in ('a', 'b', 'c')}, 'excluded': []}
    proposal = {'sources': {'a': source('a')}, 'bullets': [{'text': 'A', 'source_ids': ['a']}]}
    view = workspace(candidates, proposal)
    assert len(view['ready']) == 3
    assert view['new'] == ['b', 'c']
    assert view['recommended'] == 1
    assert [row['outcome'] for row in view['ready']] == ['Recommended', 'Newly available', 'Newly available']


def test_refresh_preserves_edited_wording_selection_and_old_source_evidence():
    from starlette.datastructures import FormData
    from app.services.resume_sources import capture_draft, merge_proposal, workspace
    previous = {'sources': {'a': source('a')}, 'bullets': [{'text': 'AI wording', 'source_ids': ['a']}]}
    captured = capture_draft(previous, FormData([('bullet_0', 'My edited wording'), ('selected', '0')]))
    fresh = {'sources': {'a': source('a', 'v2'), 'b': source('b')},
             'bullets': [{'text': 'New wording', 'source_ids': ['a'], 'source_versions': {'a': 'v2'}}]}
    merged = merge_proposal(captured, fresh)
    assert previous['bullets'][0]['text'] == 'AI wording'
    assert merged['selected'] == ['0']
    assert merged['bullets'][0]['text'] == 'My edited wording'
    assert merged['bullets'][0]['evidence']['a']['updated'] == 'v1'
    assert merged['bullets'][1]['new'] is True
    view = workspace({'eligible': fresh['sources'], 'excluded': []}, merged)
    assert view['stale'] == [0]
    assert view['new'] == []


def test_focused_refresh_does_not_claim_other_new_sources_were_reviewed():
    from app.services.resume_sources import merge_proposal, workspace
    old = {'sources': {'a': source('a')}, 'bullets': [], 'selected': []}
    fresh = {'sources': {'b': source('b')}, 'bullets': []}
    result = merge_proposal(old, fresh, focused=True)
    view = workspace({'eligible': {key: source(key) for key in ('a', 'b', 'c')}, 'excluded': []}, result)
    assert view['new'] == ['c']


def test_exact_repeat_does_not_append_after_user_edit_and_stale_feedback_clears():
    from app.services.resume_sources import merge_proposal
    original = {'kind': 'add', 'targets': [], 'source_ids': ['a'], 'source_versions': {'a': 'v1'},
                'generated_text': 'Original wording', 'text': 'Edited wording'}
    previous = {'sources': {'a': source('a')}, 'bullets': [original], 'selected': ['0'],
                'filtered_sources': {'a': True}, 'source_feedback': {'a': 'Old reason'}}
    fresh = {'sources': {'a': source('a')}, 'bullets': [dict(original, text='Original wording')]}
    result = merge_proposal(previous, fresh)
    assert len(result['bullets']) == 1
    assert result['bullets'][0]['text'] == 'Edited wording'
    assert result['last_added'] == 0
    assert result['filtered_sources'] == {}
    assert result['source_feedback'] == {}


def test_inventory_distinguishes_unfinished_used_and_unavailable_sources():
    from app.services.resume_sources import workspace
    candidates = {'eligible': {}, 'excluded': [
        {'id': 'raw', 'reason': 'Not completed'},
        {'id': 'used', 'reason': 'Already incorporated; no source changes'},
    ]}
    proposal = {'sources': {'gone': source('gone')}, 'bullets': [{'source_ids': ['gone']}]}
    view = workspace(candidates, proposal)
    assert [row['id'] for row in view['review']] == ['raw']
    assert [row['id'] for row in view['represented']] == ['used']
    assert view['removed'] == ['gone']
    assert view['stale'] == [0]
    assert view['recommended'] == 0
