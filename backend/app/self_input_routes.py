"""Authenticated source review, AI proposals and immutable annual self-input versions."""
import re
import uuid
from copy import deepcopy
from datetime import UTC, date, datetime
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import and_, delete, or_, select, update

from app.db import get_session
from app.models import AIProvider, AuditEvent, SelfInput
from app.security import require_csrf
from app.services import reporting_year, self_input, self_input_exports, self_input_sources


def register(app, templates, context, current_user):
    def get_record(session, record_id):
        record = session.get(SelfInput, record_id)
        if record is None:
            raise HTTPException(404, "Self input not found.")
        return record

    def revision(form, record):
        try:
            value = int(form.get("revision", -1))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "Invalid draft revision. Reload this page.") from exc
        if value != record.revision:
            raise HTTPException(409, "This self input changed in another window. Reload before continuing.")
        return value

    def save(session, record, state, expected, event="self_input.saved"):
        changed = session.execute(update(SelfInput).where(SelfInput.id == record.id, SelfInput.revision == expected)
                                  .values(state=state, revision=expected + 1))
        if changed.rowcount != 1:
            session.rollback()
            raise HTTPException(409, "A newer draft was saved while this request was working. Reload; it was not overwritten.")
        session.add(AuditEvent(event_type=event, metadata_json={"self_input_id": record.id}))
        session.commit()

    def preferences(form):
        style, length = str(form.get("style", "narrative")), str(form.get("length", "standard"))
        if style not in {"narrative", "bullets", "mixed"} or length not in {"brief", "standard", "detailed"}:
            raise ValueError("Choose a writing format and length.")
        limit = int(form.get("character_limit", "0") or 0)
        if not 0 <= limit <= 100000:
            raise ValueError("The character limit must be between 0 (unlimited) and 100,000.")
        sample = str(form.get("voice_sample", ""))
        if len(sample) > 8000:
            raise ValueError("Keep the optional writing sample within 8,000 characters.")
        goals = str(form.get("review_goals", "")).replace("\r\n", "\n").strip()
        if len(goals) > 12000:
            raise ValueError("Keep goals or performance expectations within 12,000 characters.")
        return {"style": style, "length": length, "target_words": {"brief": 350, "standard": 700, "detailed": 1200}[length],
                "character_limit": limit, "voice_sample": sample, "review_goals": goals}

    async def recommend(provider, state, apply_initial=False):
        state.pop("selection_recommendation", None)
        state["selection_error"] = ""
        try:
            recommendation = await self_input.recommend_selection(provider, state)
            recommendation["created_at"] = datetime.now(UTC).isoformat()
            state["selection_recommendation"] = recommendation
            if apply_initial:
                for section in state["sections"]:
                    section["included"] = recommendation["decisions"][section["id"]]["include"]
        except ValueError as exc:
            state["selection_error"] = str(exc)
        except Exception:
            state["selection_error"] = "AI could not suggest a section selection. Your text and checkboxes are preserved. Retry Suggest section selection."

    async def complete_questions(provider, state, section_ids):
        for section in state["sections"]:
            if section["id"] not in section_ids:
                continue
            target = state["proposals"].get(section["id"], section)
            section["questions_error"] = ""
            section["questions_checked"] = False
            try:
                questions = await self_input.suggest_questions(provider, state, section)
                # Keep useful questions produced by this same writing pass if
                # the focused question pass has nothing further to ask.
                target["questions"] = questions or target.get("questions", [])
                section["questions_checked"] = True
            except Exception:
                # A question request must never discard successful draft writing.
                section["questions_error"] = "AI could not suggest follow-up questions. Your writing is saved. Use the question button below to retry."

    def selection_page(request, session, record=None, error="", status=200, values=None):
        values = values if values is not None else request.query_params
        settings = reporting_year.preferences(session)
        try:
            if record:
                saved = record.state["period"]
                selected_period = reporting_year.Period(date.fromisoformat(saved["start"]), date.fromisoformat(saved["end"]), saved["label"])
            else:
                selected_period = self_input_sources.period(settings, values.get("year"), values.get("start"), values.get("end"))
        except (ValueError, OverflowError):
            selected_period = reporting_year.current_period(settings)
            error, status = "Choose a valid year or an ordered start and end date.", 400
        current = reporting_year.current_period(settings)
        label_year = current.end.year if settings.year_naming == "ending" else current.start.year
        inventory = self_input_sources.catalog(session, selected_period)
        selected = set(record.state["sources"]) if record else {
            row["record"].id for group in ("ready", "review") for row in inventory[group]
        }
        if hasattr(values, "getlist") and "source_selection" in values:
            selected = set(values.getlist("source_ids")) | set(values.getlist("confirmed_source_ids"))
        return templates.TemplateResponse("self_input_start.html", context(
            request, record=record, period=selected_period, inventory=inventory, selected=selected,
            years=list(range(label_year, label_year - 8, -1)), values=values, error=error,
            assessments=list(session.scalars(select(SelfInput).order_by(SelfInput.created_at.desc()))),
        ), status_code=status)

    @app.get("/self-input")
    def library(request: Request, session=Depends(get_session), user=Depends(current_user)):
        return selection_page(request, session)

    @app.get("/self-input/{record_id}/sources")
    def select_sources(record_id: str, request: Request, session=Depends(get_session), user=Depends(current_user)):
        return selection_page(request, session, get_record(session, record_id))

    def bulk_records(session, form):
        ids = list(dict.fromkeys(form.getlist("assessment_ids")))
        if not ids or len(ids) > 200 or any(not isinstance(key, str) for key in ids):
            raise HTTPException(400, "Select between 1 and 200 self inputs to delete.")
        records = list(session.scalars(select(SelfInput).where(SelfInput.id.in_(ids)).order_by(SelfInput.created_at.desc())))
        if len(records) != len(ids):
            raise HTTPException(409, "A selected self input is no longer available. Reload the list and select again. Nothing was deleted.")
        return records

    @app.post("/self-input/bulk-delete/preview")
    async def preview_bulk_delete(request: Request, session=Depends(get_session), user=Depends(current_user)):
        form = await request.form()
        require_csrf(request, str(form.get("csrf", "")))
        records = bulk_records(session, form)
        return templates.TemplateResponse("self_input_bulk_delete.html", context(request, assessments=records))

    @app.post("/self-input/bulk-delete/confirm")
    async def confirm_bulk_delete(request: Request, session=Depends(get_session), user=Depends(current_user)):
        form = await request.form()
        require_csrf(request, str(form.get("csrf", "")))
        if form.get("confirm_delete") != "yes":
            raise HTTPException(400, "Confirm deletion before removing the selected self inputs.")
        records = bulk_records(session, form)
        conditions = []
        for record in records:
            expected = revision({"revision": form.get("revision_" + record.id)}, record)
            conditions.append(and_(SelfInput.id == record.id, SelfInput.revision == expected))
        # One transaction: a stale selection cannot result in partial deletion.
        removed = session.execute(delete(SelfInput).where(or_(*conditions)))
        if removed.rowcount != len(records):
            session.rollback()
            raise HTTPException(409, "A selected self input changed. Nothing was deleted. Reload and review your selection.")
        for record in records:
            session.add(AuditEvent(event_type="self_input.deleted", metadata_json={"self_input_id": record.id}))
        session.commit()
        return RedirectResponse("/self-input?deleted=selected#self-input-library", 303)

    @app.get("/self-input/{record_id}/delete")
    def confirm_delete(record_id: str, request: Request, session=Depends(get_session), user=Depends(current_user)):
        return templates.TemplateResponse("self_input_delete.html", context(
            request, record=get_record(session, record_id),
        ))

    @app.post("/self-input/{record_id}/delete")
    async def delete_assessment(record_id: str, request: Request, session=Depends(get_session), user=Depends(current_user)):
        form = await request.form()
        require_csrf(request, str(form.get("csrf", "")))
        record = get_record(session, record_id)
        expected = revision(form, record)
        if form.get("confirm_delete") != "yes":
            raise HTTPException(400, "Confirm deletion before removing this self input.")
        removed = session.execute(delete(SelfInput).where(SelfInput.id == record_id, SelfInput.revision == expected))
        if removed.rowcount != 1:
            session.rollback()
            raise HTTPException(409, "This self input changed while you were deleting it. Reload and review it before deleting.")
        session.add(AuditEvent(event_type="self_input.deleted", metadata_json={"self_input_id": record_id}))
        session.commit()
        return RedirectResponse("/self-input?deleted=1", 303)

    async def store_sources(request, session, record=None):
        form = await request.form()
        require_csrf(request, str(form.get("csrf", "")))
        expected = revision(form, record) if record else 0
        if record and record.state.get("proposals"):
            raise HTTPException(409, "Apply or dismiss the pending AI proposals before refreshing sources. Your draft is preserved.")
        try:
            selected_period = self_input_sources.period(reporting_year.preferences(session), start=str(form.get("start", "")), end=str(form.get("end", "")))
            if record:
                old = record.state["period"]
                if str(selected_period.start) != old["start"] or str(selected_period.end) != old["end"]:
                    raise ValueError("Create a new self input to use a different review period.")
            confirmed_sources = form.getlist("confirmed_source_ids")
            ids = list(dict.fromkeys(form.getlist("source_ids") + confirmed_sources))
            confirmed = set(form.getlist("confirmed_ids")) | set(confirmed_sources)
            include_attachments = form.get("attachments") == "yes"
            sources = self_input_sources.collect(session, selected_period, ids, confirmed, include_attachments)
            if record:
                state = deepcopy(record.state)
            else:
                title = str(form.get("title", "")).strip()
                if not title or len(title) > 300:
                    raise ValueError("Give this self input a title of up to 300 characters.")
                state = {"period": {"start": str(selected_period.start), "end": str(selected_period.end), "label": str(selected_period.label)},
                         "preferences": preferences(form), "sections": self_input.initial_sections(str(form.get("employer_questions", "")), form.getlist("extra_section")),
                         "versions": [], "proposals": {}, "history": {}}
            state["history"].update({source["fingerprint"]: source for source in sources.values()})
            state.update(sources=sources, confirmed_ids=list(confirmed), attachments=include_attachments, digest=None, omissions={}, error="")
            if record:
                save(session, record, state, expected, "self_input.sources_refreshed")
            else:
                record = SelfInput(title=title, state=state)
                session.add(record)
                session.flush()
                session.add(AuditEvent(event_type="self_input.created", metadata_json={"self_input_id": record.id, "source_count": len(sources)}))
                session.commit()
        except (ValueError, OverflowError) as exc:
            return selection_page(request, session, record, str(exc), 400, form)
        return RedirectResponse("/self-input/" + record.id, 303)

    @app.post("/self-input")
    async def create(request: Request, session=Depends(get_session), user=Depends(current_user)):
        return await store_sources(request, session)

    @app.post("/self-input/{record_id}/sources")
    async def refresh_sources(record_id: str, request: Request, session=Depends(get_session), user=Depends(current_user)):
        return await store_sources(request, session, get_record(session, record_id))

    @app.get("/self-input/{record_id}")
    def detail(record_id: str, request: Request, session=Depends(get_session), user=Depends(current_user)):
        record = get_record(session, record_id)
        state = self_input.editable_state(record.state)
        saved = state["period"]
        selected_period = reporting_year.Period(date.fromisoformat(saved["start"]), date.fromisoformat(saved["end"]), saved["label"])
        inventory = self_input_sources.catalog(session, selected_period)
        current_ids = {row["record"].id for key in ("ready", "review") for row in inventory[key]}
        changed_count = sum(row["record"].id in state["sources"] and row["record"].updated_at.isoformat() != state["sources"][row["record"].id]["updated"]
                            for key in ("ready", "review") for row in inventory[key])
        new_count = len(current_ids - set(state["sources"]))
        unavailable = set(state["sources"]) - current_ids
        return templates.TemplateResponse("self_input_detail.html", context(
            request, record=record, state=state, issues=self_input_sources.issues(state["sources"]),
            coverage=self_input.coverage(state["sources"], state["sections"]), narrative=self_input.plain_text(state["sections"]),
            selection_current=self_input.selection_is_current(state),
            new_count=new_count, changed_count=changed_count, unavailable=unavailable,
            providers=list(session.scalars(select(AIProvider).where(AIProvider.enabled.is_(True)).order_by(AIProvider.priority))),
        ))

    @app.post("/self-input/{record_id}/review")
    async def review(record_id: str, request: Request, session=Depends(get_session), user=Depends(current_user)):
        form = await request.form()
        require_csrf(request, str(form.get("csrf", "")))
        record = get_record(session, record_id)
        expected = revision(form, record)
        state = self_input.capture(record.state, form)
        operation = str(form.get("operation", "save"))
        section_id = str(form.get("section_id", ""))
        if ":" in operation:
            operation, section_id = operation.split(":", 1)
        apply_id = str(form.get("apply_section", ""))
        if apply_id:
            operation = "apply"
        if operation not in {"save", "generate", "generate_missing", "apply", "dismiss", "approve", "add", "questions", "recommend", "select_ai", "fill"}:
            raise HTTPException(400, "Unknown self-input action.")
        try:
            state["preferences"] = preferences(form)
            state["provider"] = str(form.get("provider", ""))
            state["error"] = ""
            if operation == "fill":
                section = next((s for s in state["sections"] if s["id"] == section_id), None)
                if section is None:
                    raise ValueError("Choose a section in this self input.")
                if any(block["text"].strip() for block in section["blocks"]):
                    # An edit made before submitting already supplies the missing text.
                    section["included"] = True
                else:
                    section["included"] = False
                    if section_id in state["proposals"]:
                        raise ValueError("This section has proposed wording waiting for review. Accept its rewrite, then include the section.")
                    if self_input_sources.issues(state["sources"]) and form.get("ack_issues") != "yes":
                        raise ValueError("Review the unavailable attachment text and confirm you want to continue with the readable information.")
                    provider = session.get(AIProvider, state["provider"])
                    if provider is None:
                        raise ValueError("Set up and select an AI provider under Settings → AI Providers.")
                    save(session, record, state, expected)
                    expected += 1
                    proposals, facts, _ = await self_input.propose(
                        provider, state, section_id,
                        "The user wants to include this empty section. Write a concise contribution specific to this section, "
                        "using relevant selected evidence and confirmed answers. Do not just repeat the overall summary. "
                        "If the evidence cannot support this topic, leave blocks empty and ask a specific question. Never invent facts.",
                    )
                    proposal = proposals[section_id]
                    for block in proposal["blocks"]:
                        block["source_versions"] = {key: state["sources"][key]["fingerprint"] for key in block["source_ids"]}
                    section["blocks"] = self_input.merge_locked(section["blocks"], proposal["blocks"])
                    section["questions"] = proposal["questions"]
                    section["draft_initialized"] = True
                    section["included"] = any(block["text"].strip() for block in section["blocks"])
                    state.update(digest=facts, generated_at=datetime.now(UTC).isoformat())
                    if not section["included"]:
                        if not section["questions"]:
                            section["questions"] = ["What did you personally contribute in this area during the review period?"]
                        state["error"] = (f"AI could not find enough supporting information to write '{section['title']}'. "
                                          "Answer its questions below, then choose Write and include this section. It has not been added to the draft.")
                    save(session, record, state, expected)
                    expected += 1
                    await complete_questions(provider, state, [section_id])
                    await recommend(provider, state)
            if operation == "select_ai":
                if not self_input.selection_is_current(state):
                    raise ValueError("The draft or writing preferences changed. Ask AI to suggest a fresh section selection first.")
                for section in state["sections"]:
                    section["included"] = state["selection_recommendation"]["decisions"][section["id"]]["include"]
            if operation == "recommend":
                provider = session.get(AIProvider, state["provider"])
                if provider is None:
                    raise ValueError("Set up and select an AI provider under Settings → AI Providers.")
                save(session, record, state, expected)
                expected += 1
                await recommend(provider, state)
            if operation == "questions":
                section = next((s for s in state["sections"] if s["id"] == section_id), None)
                provider = session.get(AIProvider, state["provider"])
                if section is None or provider is None:
                    raise ValueError("Choose a section and a configured local AI provider.")
                save(session, record, state, expected)
                expected += 1
                questions = await self_input.suggest_questions(provider, state, section)
                target = state["proposals"].get(section_id, section)
                target["questions"] = questions
                section["questions_checked"] = True
                section["questions_error"] = ""
            if operation == "add":
                section = next((s for s in state["sections"] if s["id"] == section_id), None)
                if section is None:
                    raise ValueError("Choose a valid section.")
                section["blocks"].append({"id": str(uuid.uuid4()), "text": "", "source_ids": [], "locked": False})
            if operation == "apply":
                proposal = state["proposals"].get(apply_id)
                section = next((s for s in state["sections"] if s["id"] == apply_id), None)
                if proposal is None or section is None:
                    raise ValueError("That proposal is no longer available.")
                section["blocks"] = self_input.merge_locked(section["blocks"], proposal["blocks"])
                section["questions"] = proposal["questions"]
                del state["proposals"][apply_id]
            if operation == "dismiss":
                state["proposals"] = {}
            if operation in {"generate", "generate_missing", "approve"} and state["proposals"]:
                raise ValueError("Apply the sections you want, then dismiss remaining proposals before generating again or approving.")
            if operation == "approve":
                narrative = self_input.plain_text(state["sections"])
                if not narrative.strip() or form.get("confirm_review") != "yes":
                    raise ValueError("Write a draft and confirm that you reviewed every claim before approving.")
                if re.search(r"\[[^\]]+\]", narrative):
                    raise ValueError("Remove bracketed placeholders before approving.")
                limit = state["preferences"]["character_limit"]
                if limit and len(narrative) > limit and form.get("allow_length") != "yes":
                    raise ValueError("The draft exceeds your character limit. Shorten it or explicitly allow the extra length.")
                current_period = reporting_year.Period(date.fromisoformat(state["period"]["start"]), date.fromisoformat(state["period"]["end"]), state["period"]["label"])
                fresh = self_input_sources.collect(session, current_period, list(state["sources"]), set(state["confirmed_ids"]), state["attachments"])
                changed = any(fresh[key]["fingerprint"] != source["fingerprint"] for key, source in state["sources"].items())
                outdated_blocks = any(key not in state["sources"] or state["sources"][key]["fingerprint"] != fingerprint
                                      for section in state["sections"] if section.get("included", True) for block in section["blocks"]
                                      for key, fingerprint in block.get("source_versions", {}).items())
                if (changed or outdated_blocks) and form.get("ack_stale") != "yes":
                    raise ValueError("Some source evidence changed or was removed from this selection. Refresh sources and review the wording, or explicitly confirm your review against the saved evidence.")
                state["versions"].append({"id": str(uuid.uuid4()), "created_at": datetime.now(UTC).isoformat(),
                                          "sections": deepcopy(state["sections"]), "period": deepcopy(state["period"]),
                                          "sources": deepcopy(state["sources"]), "history": deepcopy(state["history"]),
                                          "preferences": deepcopy(state["preferences"]), "source_changes_acknowledged": changed or outdated_blocks})
            if operation in {"generate", "generate_missing"}:
                initial_draft = (not state.get("generated_at") and not state.get("versions")
                                 and not any(block["text"].strip() for section in state["sections"] for block in section["blocks"]))
                if self_input_sources.issues(state["sources"]) and form.get("ack_issues") != "yes":
                    raise ValueError("Review the unavailable attachment text and confirm you want to continue with the readable information.")
                provider = session.get(AIProvider, state["provider"])
                if provider is None:
                    raise ValueError("Set up and select an AI provider under Settings → AI Providers.")
                # Durable checkpoint before potentially slow local inference.
                save(session, record, state, expected)
                expected += 1
                instruction = str(form.get("refinement", ""))[:2000]
                missing_ids = [s["id"] for s in state["sections"] if not any(b["text"].strip() for b in s["blocks"])]
                if operation == "generate_missing":
                    if not missing_ids:
                        raise ValueError("Every section already has text. Use the checkboxes to choose your final draft.")
                    proposals, facts, omissions = await self_input.propose(provider, state, instruction=instruction, requested_ids=missing_ids)
                else:
                    proposals, facts, omissions = await self_input.propose(provider, state, section_id, instruction)
                for proposal in proposals.values():
                    for block in proposal["blocks"]:
                        block["source_versions"] = {key: state["sources"][key]["fingerprint"] for key in block["source_ids"]}
                state.update(proposals=proposals, digest=facts, omissions=omissions, generated_at=datetime.now(UTC).isoformat())
                if operation == "generate_missing":
                    # Fill only empty sections; existing text and inclusion choices stay intact.
                    for section in state["sections"]:
                        if section["id"] in proposals:
                            section["blocks"] = self_input.merge_locked(section["blocks"], proposals[section["id"]]["blocks"])
                            section["questions"] = proposals[section["id"]]["questions"]
                            section["draft_initialized"] = True
                    state["proposals"] = {}
                state = self_input.editable_state(state)
                # Keep successful writing even if the separate editorial pass fails.
                state.pop("selection_recommendation", None)
                save(session, record, state, expected)
                expected += 1
                await complete_questions(provider, state, list(proposals))
                await recommend(provider, state, apply_initial=initial_draft)
        except ValueError as exc:
            state["error"] = str(exc)
        except Exception:
            # Never expose credential-bearing provider errors or document content.
            state["error"] = "The local AI request could not finish. Your draft was preserved. Check the provider and retry."
        save(session, record, state, expected, "self_input.approved" if operation == "approve" and not state["error"] else "self_input.saved")
        anchor = "#self-combined-draft" if operation == "fill" and not state["error"] else ""
        return RedirectResponse("/self-input/" + record_id + anchor, 303)

    @app.get("/self-input/{record_id}/versions/{version_id}/{extension}")
    def download(record_id: str, version_id: str, extension: str, session=Depends(get_session), user=Depends(current_user)):
        record = get_record(session, record_id)
        version = next((v for v in record.state["versions"] if v["id"] == version_id), None)
        if version is None or extension not in self_input_exports.MIME:
            raise HTTPException(404, "Approved version or format not found.")
        filename = record.title + "." + extension
        return Response(self_input_exports.export(record.title, version, extension), media_type=self_input_exports.MIME[extension],
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename, safe="")})
