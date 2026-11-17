# ADR 0003: Storage access and the read-only source (Spike 3)

Date: 2026-11-17. Status: accepted for Dropbox; rclone verified up to a scope requirement.

**Question.** Can rclone with a read-only credential serve as the storage layer for the source folder (spec section 7)?

**Experiment.** rclone v1.76.0 (Windows, unpacked to `tools/rclone/`, git-ignored) configured purely through environment variables (no secret written to disk) with the existing *reader* token (scopes `files.metadata.read`, `files.content.read`, `sharing.read`), run `rclone lsd dbx:/`.

**Result.** It fails: `get current account failed: missing_scope`. rclone's Dropbox backend always calls `users/get_current_account`, which needs the read-only scope `account_info.read`. The reader token must be re-issued with that scope (and the scope enabled for the app in the Dropbox developer console).

**Findings.**
- Read-only is a property of the token's scopes, not of rclone; rclone has no global read-only switch. A write-scoped token would let it write.
- The existing SDK path already separates roles (reader token for the source, writer token for the output folder) and guards paths with `SafeWriter` (tested in `backend/tests/test_distill_guard.py`).

**Decision.** `READ_SCOPES` now includes `account_info.read` (still read-only). After the reader token is re-authorised, rclone becomes the storage layer for any provider (Dropbox, Google Drive, OneDrive, local), always with: a read-scoped credential for sources; `rclone copy`/`lsf` direction source to local only; writes to the output only through the guarded writer. The SDK stays as the fallback.

**Owner action to complete the test:** enable `account_info.read` in the Dropbox app's Permissions tab, then re-run the reader authorisation: `cd backend; python -m app.distill.dropbox_io auth --app-key <app_key> --role reader --read-only`, open the URL, click Allow, paste the code.
