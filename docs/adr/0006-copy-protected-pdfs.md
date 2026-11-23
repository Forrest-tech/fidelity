# ADR 0006: Read copy-protected PDFs from images of their pages (owner's switch)

Date: 2026-11-22. Status: accepted by the owner.

**Context.** Some standards PDFs open normally but forbid copying their text. The PDF permission flag does this; there is no password. Until now they were listed as "cannot be processed: copying text not allowed" (IR-3: no bypass of copy protection). The owner confirmed on 2026-11-22 that the company is licensed to use this content, and asked that such files be read: render each page, read the text from the image, then discard the image.

**Decision.** A switch in Settings → Defaults, "Copy-protected PDFs", off by default. When it is on, a PDF whose only restriction is on copying is read through the scan route:
- Each page is rendered in memory and read by both OCR engines. The engines are compared, and the page goes to review when they disagree, exactly like a scanned document.
- No page image is written to disk.
- The output carries the flag `from_page_images`, and its triage reason says how the text was obtained.

A PDF that needs a password is never worked around.

**Consequences.**
- IR-3 is relaxed for copy-only restrictions, by the owner's decision, for content the company is licensed to use. The switch makes the choice visible and reversible.
- Files listed as protected before are read again on the next run once the switch is on.
- Such a file costs 2 capacity points, like any scan.
