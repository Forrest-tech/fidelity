"""Requirements v2 U-4 / S-5: what the bell shows also goes out by e-mail, once per item, to the people it concerns,
without a flood of old news, and only to people who did not switch it off."""
import email
import email.policy
import glob

import pytest

from app.api import notifications as N
from app.ops import health as H
from app.ops import mail
from app.ops import notify_mail as NM

ROOM = {"key": "review:r1:3", "type": "review", "tone": "warn", "n": 3, "room_name": "AS 3500", "to": "/distill?room=r1"}
DISK = {"key": "sys:disk:4", "type": "system", "tone": "bad", "kind": "disk", "to": "/settings/system"}


@pytest.fixture()
def world(tmp_path, monkeypatch):
    box = tmp_path / "outbox"
    monkeypatch.setenv("FIDELITY_MAIL_OUTBOX", str(box))
    monkeypatch.setattr(mail, "PATH", str(tmp_path / "email_settings.json"))
    people = [("boss@example.com", "admin"), ("rev@example.com", "reviewer")]
    monkeypatch.setattr(NM, "people", lambda: people)
    items = []
    monkeypatch.setattr(N, "_items", lambda user: list(items))
    con = NM._con()
    con.execute("DELETE FROM notification_mail")
    con.execute("DELETE FROM notification_pref")
    con.commit()
    con.close()
    return box, items


def _mails(box, to):
    out = []
    for f in sorted(glob.glob(str(box / "*.eml"))):
        m = email.message_from_bytes(open(f, "rb").read(), policy=email.policy.default)
        if m["To"] == to:
            out.append(m.get_body(("plain",)).get_content())
    return out


def test_old_news_is_not_mailed_and_new_news_is_mailed_once_to_whom_it_concerns(world):
    box, items = world
    items.append({**ROOM, "key": "review:r1:1", "n": 1})
    NM.run_once()                                    # first pass: remembers what is already there
    assert not glob.glob(str(box / "*.eml"))
    items.extend([ROOM, DISK])
    NM.run_once()
    boss, rev = _mails(box, "boss@example.com"), _mails(box, "rev@example.com")
    assert len(boss) == 1 and "3 file(s) wait for review" in boss[0] and "disk space is low" in boss[0]
    assert "/distill?room=r1" in boss[0] and "/settings/notifications" in boss[0]
    assert len(rev) == 1 and "wait for review" in rev[0] and "disk" not in rev[0]     # system news is for admins
    NM.run_once()                                    # nothing new: nothing sent
    assert len(glob.glob(str(box / "*.eml"))) == 2


def test_a_person_who_switched_it_off_gets_nothing(world):
    box, items = world
    NM.run_once()
    NM.set_wants_mail("rev@example.com", False)
    items.append(ROOM)
    NM.run_once()
    assert not _mails(box, "rev@example.com") and _mails(box, "boss@example.com")
    assert NM.wants_mail("rev@example.com") is False and NM.wants_mail("boss@example.com") is True


def test_nothing_is_sent_without_a_mail_server(world, monkeypatch):
    monkeypatch.delenv("FIDELITY_MAIL_OUTBOX")
    assert NM.run_once() == {"sent": 0, "why": "no mail server"}


def test_an_ai_account_without_credit_is_a_system_alert(monkeypatch):
    from app import db
    db.init_trust()
    con = db.trust_rw()
    con.execute("INSERT INTO ai_call(id, skill, provider, status, message, created_at) VALUES('t402','arbitrate','deepseek',"
                "'error','the provider account has no credit left: top it up on the provider''s website', 9e12)")
    con.commit()
    con.close()
    try:
        assert any(a["kind"] == "ai_credit" and a["level"] == "bad" for a in H.alerts())
        assert "no credit left" in NM.describe({"type": "system", "kind": "ai_credit"})
    finally:
        con = db.trust_rw()
        con.execute("DELETE FROM ai_call WHERE id='t402'")
        con.commit()
        con.close()
