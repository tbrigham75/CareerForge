from unittest.mock import AsyncMock

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Accomplishment, AccomplishmentRevision, AIProvider
from app.schemas import AccomplishmentInput, AIDraftResponse
from app.services.accomplishments import create
from test_auth_and_capture import token


def test_review_save_resume_apply_undo_and_conflict(logged_in, monkeypatch):
    with SessionLocal() as session:
        record = create(session, AccomplishmentInput(raw_note="Patched four servers.", action="Existing action"))
        provider = AIProvider(display_name="Local", base_url="http://localhost:11434", default_model="test")
        session.add(provider)
        session.commit()
        rid, pid = record.id, provider.id
    generate = AsyncMock(return_value=AIDraftResponse(title="", action="Patched servers", metric="Four servers", impact="Supported patch maintenance", supporting_narrative=""))
    monkeypatch.setattr("app.main.generate_draft", generate)
    url = f"/accomplishments/{rid}/ai-review"
    def post(op, **kwargs):
        return logged_in.post(url, json={"csrf":token(logged_in), "operation":op, "provider_id":pid, **kwargs})
    response = post("generate")
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["content"]["selected"] == ["metric", "impact"]
    assert len(draft["content"]["metric_suggestions"]) == 3
    assert len(draft["content"]["impact_suggestions"]) == 3
    assert post("apply",draft_id=draft["id"],suggestions={"metric":"Across [number] servers"},selected=["metric"]).status_code == 400
    assert post("refine", draft_id=draft["id"], field="metric", answer="Coverage — Confirmed amount or scope: ").status_code == 400
    assert "existing_fields" not in generate.await_args.args[2]
    with SessionLocal() as session:
        assert session.get(Accomplishment, rid).metric == ""
        assert len(list(session.scalars(select(AccomplishmentRevision)))) == 1
    did = draft["id"]
    assert post("save_draft", draft_id=did, suggestions={"metric":"4 servers"}, selected=["metric"], pending_answers={"metric":"Four"}).status_code == 200
    assert post("load").json()["drafts"][0]["content"]["pending_answers"]["metric"] == "Four"
    saved = post("apply", draft_id=did, suggestions={"action":"Do not apply", "metric":"4 servers"}, selected=["metric"])
    assert saved.status_code == 200, saved.text
    assert saved.json()["current"]["action"] == "Existing action"
    assert post("apply", draft_id=did, suggestions={"metric":"4"}, selected=["metric"]).status_code == 409
    assert post("undo", draft_id=did).status_code == 200
    with SessionLocal() as session:
        assert session.get(Accomplishment,rid).metric == ""
        assert len(list(session.scalars(select(AccomplishmentRevision)))) == 3
    new = post("generate", include_context=True).json()
    assert "existing_fields" in generate.await_args.args[2]
    with SessionLocal() as session:
        record=session.get(Accomplishment,rid)
        record.action="New manual edit"
        session.commit()
    assert post("apply",draft_id=new["id"],suggestions={"metric":"4"},selected=["metric"]).status_code == 409
    assert logged_in.post(url,json={"operation":"load","csrf":"wrong"}).status_code == 403


def test_review_panel_browser(logged_in):
    from pathlib import Path

    from playwright.sync_api import sync_playwright
    with SessionLocal() as session:
        record=create(session,AccomplishmentInput(raw_note="Patched four servers",action="Existing"))
        rid=record.id
    html=logged_in.get(f"/accomplishments/{rid}").text
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(channel="msedge",headless=True)
        page=browser.new_page()
        page.set_content(html)
        page.evaluate("""() => {window.fetch=async(url,options)=>{
          const q=JSON.parse(options.body); let data;
          if(q.operation==='load')data={providers:[{id:'p',name:'Local',model:'test'}],current:{action:'Existing',metric:'',impact:''},drafts:[]};
          else if(q.operation==='generate')data={id:'d',content:{baseline:{raw_note:'Patched four servers'},suggestions:{action:'Patched servers',metric:'Four servers',impact:''},selected:['metric'],metric_suggestions:['Patched [number] servers.'],impact_suggestions:['Supported service reliability through patching.'],questions:{impact:'What changed?'},answers:{}}};
          else data={message:'Saved'};
          return {ok:true,headers:{get:()=> 'application/json'},json:async()=>data};
        };} """)
        page.add_script_tag(content=Path('backend/app/static/ai-review.js').read_text(encoding='utf-8'))
        page.get_by_role('button',name='Help with Action, Metric & Impact').click()
        page.get_by_role('button',name='Generate Suggestions',exact=True).click()
        assert page.locator('#ai-check-metric').is_checked()
        assert not page.locator('#ai-check-action').is_checked()
        page.get_by_role('button',name='Use as starting point').first.click()
        assert page.locator('#ai-text-metric').input_value() == 'Patched [number] servers.'
        assert not page.locator('#ai-check-metric').is_checked()
        page.on('dialog', lambda dialog: dialog.accept())
        page.get_by_role('button',name='Use as starting point').nth(1).click()
        assert page.locator('#ai-text-impact').input_value() == 'Supported service reliability through patching.'
        page.locator('#ai-text-metric').fill('Four production servers')
        page.get_by_role('button',name='Save AI Draft',exact=True).click()
        assert page.locator('#ai-status').inner_text()=='AI draft saved. Accomplishment unchanged.'
        page.set_viewport_size({'width':390,'height':844})
        assert page.locator('#ai-text-metric').is_visible()
        browser.close()


def test_empty_metric_gets_focused_starting_sentence(logged_in, monkeypatch):
    note = "Vibecoded ProxInfo to help with our PBS running out of storage"
    with SessionLocal() as session:
        record = create(session, AccomplishmentInput(raw_note=note))
        provider = AIProvider(display_name="Local",base_url="http://localhost:11434",default_model="test")
        session.add(provider)
        session.commit()
        rid,pid=record.id,provider.id
    wording="Built ProxInfo to support PBS storage work across [number of servers or datastores]."
    generate=AsyncMock(side_effect=[
        AIDraftResponse(title="",action="Built ProxInfo",metric="[Quantitative measure not provided]",impact="Supported PBS storage work",supporting_narrative=""),
        AIDraftResponse(title="",action="",metric=wording,impact="",supporting_narrative=""),
    ])
    monkeypatch.setattr("app.main.generate_draft",generate)
    response=logged_in.post(f"/accomplishments/{rid}/ai-review",json={"csrf":token(logged_in),"operation":"generate","provider_id":pid})
    assert response.status_code==200,response.text
    content=response.json()["content"]
    assert content["suggestions"]["metric"]==wording
    assert content["metric_suggestions"]==[wording]
    assert "metric" not in content["selected"]
    assert generate.await_args.args[1]==note
    assert generate.await_args.args[2]["brainstorm_field"]=="metric"
    with SessionLocal() as session:
        assert session.get(Accomplishment,rid).metric==""
