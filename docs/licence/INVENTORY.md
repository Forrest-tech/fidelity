# Licence inventory — Phase A (2026-11-22)

Requirement IR-5 (docs/REQUIREMENTS_V2.md): standards text is distributed only within the licence the company holds,
and is given to a third-party AI service only with written permission.

**How this was produced.** The vendor stamps every page of a standards PDF with the licence it was sold under
("Licensed to … Personal use licence only …", "Accessed by <organisation> on …"). `backend/app/distill/licence.py`
reads that stamp from each file's distilled text; `backend/scripts/licence_inventory.py` lists it per file. Anyone can
re-run it: `python scripts/licence_inventory.py <room_id>` from `backend/`. The full list with licensee names stays on
the machine (`backend/data/licence/<room>.csv`); names of individuals are withheld here.

## 1. AS 3500 source folder (39 files, room 蒸馏室-test)

| Licence stamp on the copy | Files | Published to `/Transfer_Md/AS 3500` |
|---|---|---|
| Organisation subscription — Norman Disney & Young (2012, 2017) | 5 (1990 Pt 3; 2015 Pts 1–4) | 5 |
| Organisation subscription — TAFE NSW (2011, 2018, 2019) | 5 (2003 Pt 2 amended; 2018 Pts 1, 2, 4) | 4 |
| An individual, "For Committee WS-014 / WS-020 use only" (2003–04) | 5 (2003 Pts 1–4; Glossary) | 5 |
| An individual, "Personal use licence only. Storage, distribution or use on network prohibited" (2011) | 9 (2003 amendments) | 9 |
| No stamp found (2021 printed scans; 1990 Pt 1 scan) | 12 | 6 |
| Copy-protected, not read | 3 | 0 |

Two of the 2018 files are copies whose copy-protection someone removed ("-已解锁" = "unlocked").

**None of the 39 copies carries a licence issued to our company.** Every stamped copy belongs to another
organisation, a committee member, or a private individual, and nine say in so many words that storage or use on a
network is prohibited.

## 2. What the vendor's current terms say

Standards Australia's current terms (Content Subscription Service user terms and general terms) state that a user
must not upload or store the content on a network — defined to include corporate networks, intranets and document
sharing platforms — and must not upload, input or otherwise provide Standards content to any artificial-intelligence
system, without prior written consent.

- https://standards.org.au/legal/css-user-terms
- https://www.standards.org.au/legal/terms-and-conditions
- https://standards.org.au/legal/definitions

These terms apply to copies the company licenses itself; the copies in section 1 are licensed to others, so the
company has no licence to them at all.

## 3. NCC (source folder `/2025`)

The National Construction Code 2022 and later editions are published by the ABCB under **Creative Commons
Attribution 4.0 (CC BY 4.0)**, and the ABCB states that NCC 2022 may be used to train AI systems under that licence.
Requirements: attribution ("The National Construction Code … was provided by the Australian Building Codes Board under
the CC BY licence"); ABCB logos and third-party images are excluded. Older editions (2016: CC BY-NC-ND; 2019: CC BY-ND)
are more restrictive.

- https://www.nccb.gov.au/faq/copyright
- https://abcb.gov.au/editions/ncc-2022/adopted/volume-two/preface/copyright-and-licence-notice

## 4. Current exposure

- 29 AS 3500 documents are published in `/Transfer_Md/AS 3500`, a shared Dropbox folder read by Grok.
- The published Markdown repeats the licence stamps, including the names of the individuals the copies were
  licensed to (personal data of people outside the company).

## 5. Owner decision (2026-11-22)

The owner confirmed that the company is authorised to use this material — much of it is publicly permitted — and
decided:

- `/Transfer_Md/AS 3500` stays published and in use;
- every similar source is handled the same way: licence stamps are **recorded** in this inventory, and they do
  **not** block distilling or publishing.

The owner's confirmation is the evidence for IR-5. The options below were considered and are kept for the record.

## 6. Options considered before the decision

1. Withdraw `/Transfer_Md/AS 3500` from the folder Grok reads (move it to a restricted folder; nothing is deleted)
   until the company holds a licence that covers this use.
2. Obtain a licence: a company subscription from Standards Australia **and** their written consent for AI use; or
   decide AS standards stay out of the AI knowledge base.
3. Stop using copies whose protection was removed by someone else ("-已解锁"); treat them like the protected original.
4. Proceed with NCC (CC BY 4.0) as the first content of the knowledge base, with the attribution line in every file.
