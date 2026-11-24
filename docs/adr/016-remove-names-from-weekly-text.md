# 016. Remove names from weekly text

## Context

A name can occur in free text as well as the fields marked personal. A dated name removal also covers promise descriptions and check notes.

## Decision

Replace whole-name matches in saved weekly text and rebuild affected locked copies from the updated snapshots. Fixed page wording and formatting stay in the renderer. Keep identifiers, stored dates, answers, signature state and finished-work source paths and digests. Refuse if the name occurs in a finished-work source path or a recorded week that still needs to be locked. Prepare accepts input drafts directly in the weekly pages folder so removal can update them. Refuse before writing if a separate artifact prevents confirming that the weekly copies will be clean. Keep a dated correction for each affected locked week.

For Arabic names in Arabic meetings, automatically replace only the exact whole name, ignoring vowel marks and tatweel. List each distinct spelling with an attached conjunction, preposition or article, or a possible letter variant, and pause the removal until the owner decides each one. Use `--also` to remove that exact listed spelling or `--keep` to preserve it. Keep these choices in memory for the command. Replace the complete span of each approved match and preserve the surrounding text.

For possible spellings, compare names with Unicode format characters omitted and compatibility forms normalized. List the original spelling, including any format characters or presentation letters copied from a PDF. Use the original spelling to check for an exact match and to apply the owner's choice to the full word.

## Consequences

Removal reaches the saved history and the copies it can rebuild. Report missing copies and leave them absent during removal. Keep a surviving locked HTML page or PDF byte-identical when its content snapshot is missing. Report the week and the copies that could not be checked and may still hold the name. The owner decides what to do with those copies. The owner's separately sent copies and older Git commits may still hold the name. The owner asks the client to replace any PDF they already sent.
