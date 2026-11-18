# Asking the compliance knowledge base — user manual

One page for staff. Nothing to install: the AI tool (Grok today) already has the `au-compliance-kb`
skill and the Dropbox connector.

## Ask
- Ask as you would ask a colleague, in English or Chinese: *"What is the maximum riser height for a
  public stairway?"* You do not need to know the clause number.
- Say the **state** and the **building class** when they matter (NSW, Class 2 …). If you don't, the AI
  should ask, or answer for each case.
- One topic per question gives the fastest answers (simple look-ups take 10–20 seconds; questions that
  need several documents take longer).

## Read the answer
Every answer has four lines:
```
Answer:   the requirement, copied from the library
Source:   file, clause, page        ← open this page in the original if the value is critical
Status:   verified / pending review
Edition:  standard and year; jurisdiction
```
- **"Not found in the knowledge base"** is a correct answer when the library does not hold it — the AI
  must not guess. It lists the words it searched; try again with other words if you think it should be there.
- **"Formula not readable … check the source page"**: some formulas could not be read from the PDF.
  Open the page given.
- **Draft, not in force**: drafts are kept for reference; the AI must answer from the published edition.
- **Pending review / from a scan / drawing**: check the original before relying on a critical figure.
- **NSW and NCC 2025**: NSW adopts NCC 2025 from 2027-05-01; until then NCC 2022 applies in NSW.

## When an answer looks wrong
Tell the AI: *"This is wrong — the value should be …"*. It re-reads the source and saves an **error
report**, which the maintainers check. Confirmed errors are fixed and added to the test set so they
cannot come back. Never edit the library files yourself.

## Where answers are kept
Each answer is saved to the chat-log folder (shown in the first answer of the chat, normally
`/Library_Installation_Chat_Logs`). The line `📁 Saved: …` at the end confirms it.

## Not for
Legal advice, project approval, or anything outside the library. The source documents remain the authority.
