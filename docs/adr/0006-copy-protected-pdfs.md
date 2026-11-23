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

## Revision (2026-11-22, same day): read the text layer instead of OCR

**Measured.** On AS/NZS 3500.2:2018, the protected copy's page images were read by OCR and compared with the unlocked copy, which is the exact truth. Only 84% of the numbers came out right (words 94%):
- page numbers and list markers were lost;
- small labels in drawings were lost;
- a few values were misread, e.g. 13.10 as 13.1.

A higher resolution did not help (1,400 px: 84.7%; 2,200 px: 84.2%). Every such file would have landed in review.

**Decision (score 9.6 against 7.0).** With the switch on, a copy-only restricted PDF is read through its own text layer. That is the publisher's exact text, the same thing the "-已解锁" (unlocked) copies in the library contain. It is then checked against OCR of sampled page images like every text PDF (`visual_check`), and flagged `copy_restricted_source`. The legal footing is the owner's licence decision, unchanged. A password-locked PDF is still never opened.
