"""Read-only smoke check with synthetic facts and a configured local AI provider."""
import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AIProvider
from app.services.ai import classify_and_validate_url, generate_draft


async def main():
    with SessionLocal() as session:
        provider = session.scalars(select(AIProvider).where(AIProvider.enabled.is_(True))).first()
        if not provider or classify_and_validate_url(provider.base_url) != 'local':
            print('SKIPPED: no configured local provider; no remote transmission made.')
            return
        print('Testing configured local provider with synthetic facts only...', flush=True)
        draft = await generate_draft(provider, 'I built a change tracker for 12 services. The team can now see what changed between runs instead of comparing files manually.', {})
        print(draft.model_dump_json(indent=2))
        draft = await generate_draft(provider, 'I built a change tracker. The team can now see what changed between runs instead of comparing files manually.', {'follow_up_answers': 'Field: metric\nQuestion: How many services does it cover?\nAnswer: It covers 12 services.'})
        print('Refinement from a metric-specific answer:')
        print(draft.model_dump_json(indent=2))


asyncio.run(main())
