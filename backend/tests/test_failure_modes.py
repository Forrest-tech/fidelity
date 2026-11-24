"""Failure modes seen in real runs (docs/quality/FMEA.md): each one is retried or stopped cleanly, never a crash."""
import ssl

from app.distill import sync as SY


def _winerr(code):
    e = PermissionError(13, "The process cannot access the file because it is being used by another process")
    e.winerror = code
    return e


def test_a_file_held_by_antivirus_is_retried_but_access_denied_is_not():
    assert SY._transient(_winerr(32))            # sharing violation: lets go within seconds
    assert not SY._transient(_winerr(5))         # access denied: retrying does not help
    assert not SY._transient(PermissionError("no winerror"))


def test_dropped_connections_are_retried():
    assert SY._transient(ssl.SSLError("UNEXPECTED_EOF_WHILE_READING"))
    assert SY._transient(ConnectionError("reset"))
    assert SY._transient(TimeoutError())
    assert not SY._transient(ValueError("bad input"))


def test_retry_gives_up_after_the_back_off(monkeypatch):
    monkeypatch.setattr(SY, "_BACKOFF", (0, 0))
    monkeypatch.setattr(SY.time, "sleep", lambda s: None)
    calls = []

    def flaky():
        calls.append(1)
        raise _winerr(32)
    try:
        SY._retry(flaky, "download")
    except PermissionError:
        pass
    assert len(calls) == 3
    assert SY._retry(iter([1]).__next__, "x") == 1


def test_the_watchdog_alert_reaches_administrators_who_want_mail(tmp_path, monkeypatch):
    import asyncio
    import glob
    import sys
    from app.ops import mail, notify_mail
    monkeypatch.setenv("FIDELITY_MAIL_OUTBOX", str(tmp_path / "box"))

    async def people():
        return [("boss@example.com", "admin"), ("quiet@example.com", "admin"), ("rev@example.com", "reviewer")]
    monkeypatch.setattr(notify_mail, "_people_async", people)
    monkeypatch.setattr(notify_mail, "wants_mail", lambda e: e != "quiet@example.com")
    sys.path.insert(0, "scripts")
    import alert_mail
    assert alert_mail.main("Fidelity server was down", "watchdog restarted it") == 0
    sent = glob.glob(str(tmp_path / "box" / "*.eml"))
    assert len(sent) == 1 and "boss_at_example.com" in sent[0]
    asyncio.run(people())
