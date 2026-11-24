# 035. Read notes on PRD approval stamps

## Context

An approved PRD can end its stamp with a parenthesized note. A note without an approver used to make setup treat that PRD as unapproved. Invalid dates caused the same result.

## Options

- Keep using one pattern for the complete stamp and treat unmatched text as missing approval.
- Recognize the approval marker first, then validate its date and read any trailing note.

## Decision

Look for approval on the first nonblank line after the PRD title. Recognize likely English and Arabic stamps even with changed case, punctuation, version format or quote markup. An approval counts only if it follows the standard stamp format on line 2 and gives a real date in ISO format. If the stamp looks like an approval but cannot be read, report its actual file and line. A misplaced stamp must move directly below the title. Ordinary prose, Draft stamps and unstamped PRDs remain eligible for docs meetings.

Read a trailing balanced parenthesized note with or without an approver, and keep its original wording when reading it back.

## Consequences

Setup and entry into build mode read the note beside the date. Existing stamps without notes keep their output. The note belongs to the PRD and does not add a field to the weekly record or change the meeting page or PDF. Closing an already recorded meeting uses the confirmed meeting content and can proceed while the PRD stamp awaits correction.
