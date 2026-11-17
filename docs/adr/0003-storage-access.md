# ADR 0003: Storage access and the read-only source (Spike 3)

Date: 2026-11-17. Status: accepted (rclone not installed on the VM; no live rclone test was run).

**Question.** Can rclone with a read-only credential replace the Dropbox SDK for the source folder (spec section 7)?

**Findings.**
- Read-only is enforced by the *credential*, not by the client: the Dropbox token must carry only the read scopes (`files.metadata.read`, `files.content.read`, `sharing.read`). rclone has no built-in global read-only switch; with a write-scoped token it could write.
- The existing pipeline already authorises two roles with the SDK (`dropbox_io.py`): a reader token (read scopes only) for the source and a writer token for the output folder, plus the `SafeWriter` path guard covered by `backend/tests/test_distill_guard.py`. This gives two independent layers.
- rclone would add a native executable to install and secure on every machine, without strengthening the guarantee.

**Decision.** Keep the official Dropbox SDK with the reader/writer role split for Dropbox. Adopt rclone only when another provider (Google Drive, OneDrive) is needed, and then only with a read-scoped credential, a remote that is read-only by construction (`rclone copy remote: local` direction only, never `sync` into the remote) and a test equivalent to the guard test.

**Revisit** when a second storage provider is required (Phase 5 packs / Phase 8 server).
