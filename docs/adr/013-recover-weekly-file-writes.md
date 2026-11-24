# 013. Recover interrupted weekly file writes

## Context

Closing a week can write three sheets. A missed meeting can retire a draft and its copies. Removing a name can touch the whole weekly history. The two-file recovery record in ADR 011 covers only the original lock operation.

## Decision

Use one local undo record for ordinary writes that change more than one file. Record the previous bytes and any absent files before publishing. Restore those bytes after a write error or when the next command finds an unfinished write. Keep existing recovery for a lock interrupted under the previous version.

A damaged content-addressed font is already unusable. Its digest-verified replacement can stay in the shared cache if the rest of the write rolls back. An absent copy first created by the interrupted write is still removed during recovery.

Use a separate recovery record for a dated removal. Validate and render every replacement before writing. Save replacement bytes, the paths to retire and the affected week numbers. If interrupted, finish publishing those replacements on the next command and report the changed weeks. Use a reserved staging file beside each destination so the next command can remove a partially staged copy. Retire files without making copies of their old bytes.

## Consequences

The next command can restore an unfinished lock and retry without making duplicate promises. It can finish a removal without keeping the old name in a recovery copy. The recovery records are temporary. A direct file reader may see a write in progress. The project folder lock still serializes commands on POSIX.
