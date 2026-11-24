"""Send one alert e-mail to every active administrator who has not switched mail off (used by the watchdog).

    python scripts/alert_mail.py "<subject>" "<text>"

Uses the mail server set in Settings -> Email. Prints how many were sent; exit code 0 even when nothing could be sent
(the watchdog must never fail because of mail)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(subject: str, text: str) -> int:
    from app.ops import mail, notify_mail
    if not mail.configured():
        print("no mail server")
        return 0
    try:
        people = asyncio.run(notify_mail._people_async())
    except Exception as e:                     # noqa: BLE001 - the database may be what is broken
        print(f"cannot read administrators: {e}")
        return 0
    sent = 0
    for email, role in people:
        if role != "admin" or not notify_mail.wants_mail(email):
            continue
        try:
            mail.send(email, subject, text)
            sent += 1
        except Exception as e:                 # noqa: BLE001
            print(f"{email}: {e}")
    print(f"sent {sent}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""))
