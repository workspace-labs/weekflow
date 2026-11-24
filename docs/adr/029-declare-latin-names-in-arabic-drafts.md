# 029. Declare Latin names in Arabic drafts

## Context

Arabic drafts can contain tool names and personal names written in Latin letters. Identifying names by capitalization can let an English sentence through and can refuse valid names.

## Decision

Recognize exact names already given in project setup. Let the draft list additional literal names in an optional `latin_names` list. Compare whole names at word boundaries and retain the list in Arabic meeting content for confirmation. Keep it out of the rendered page and PDF. A name removal drops declarations that contain the removed name.

Apply the Arabic wording and scope checks to the remaining client-facing draft text. Scope checks still read each complete option, including declared words.

## Consequences

The owner keeps control of spelling. A draft with undeclared foreign wording identifies the field to correct. Draft names cannot override the scope decision.
