# 022. Freeze docs sources and decisions with the meeting

## Context

Docs meetings quote project documents and use questions from the meeting form. Those files can change as soon as the meeting ends. The docs meeting needs to stay readable through recording, locking and entry into build mode.

## Decision

Keep sections, sentences, decision IDs, options, the form's stage history, its open questions and each sentence's source digest in the numbered meeting content. At preparation and confirmation, check the live sources and form. Once confirmed, verify the saved content against the page fingerprint and use that copy. The fingerprint for a docs week uses its real meeting date and project details. Scope approval and the build delivery schedule are outside those inputs.

If the PRD is approved before a docs draft is confirmed, allow preparation again for that existing unrecorded draft on its saved meeting date. Check the live sources and form again and require confirmation of the refreshed page before recording. Enter build mode after the docs week is locked. The PRD remains the source of scope approval.

In a sentence with a decision marker, match the surrounding text in order within one source sentence. The source can use a placeholder such as `TBD` or `not decided`. Treat common titles such as `Dr.` and `Ms.` as part of the sentence and keep time abbreviations such as `p.m.` when followed by a lowercase continuation or `TBD`. A period after the unit `ms` can end a sentence. Keep sentence and document-block boundaries in the evidence check.

Keep choices that approve or stop the scope out of the meeting page, even when other words separate the action and the scope. Refuse approval, acceptance, stop and cancellation choices about project, build or scope dates and venues. Allow timing references and standalone confirmations such as `Confirm the build date`.

Save an option's exact label and its decider in the weekly answers. Reserve `later` for **Decide next week**. An omitted or deferred answer stays open and needs no decider. Carry forward its ID and question, or list its exact old question text in `settled` when the owner reports that it was settled outside the meeting or reworded. A missed week leaves the last held meeting as the source of carry-over.

When the earlier snapshot is missing, prepare from the live form and tell the owner once for the draft to ask about the earlier open questions. On entry into build mode, report the last held docs meeting's open questions or say that they could not be read.

## Consequences

A question added to the form after confirmation is available for a later meeting. A saved answer can close its original meeting after the source files change. The next build meeting can read the preceding docs week's needs and promises. Settled questions appear in the meeting page and PDF. The PDF shows the decider for each recorded answer that has one. A dated name removal covers the saved decider and the PDF when it can be rebuilt.
