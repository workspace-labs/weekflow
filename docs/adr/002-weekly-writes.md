# 002. Replace weekly files after validation

## Context

A refusal must leave project records alone. Preparation replaces a meeting record, a content file and a page. A partial write must never leave a changed draft confirmed.

## Decision

Resolve inputs inside the selected project. Keep all output paths inside `docs/weekly/` and reject links on those paths. Validate and encode the draft before staging replacements next to their destinations. Use an exclusive write for first setup and atomic replacements for updates. Replace the week record first to clear confirmation before publishing its content and page. Serialize commands on POSIX with a lock on the existing project directory.

## Consequences

Validation refusals retain the existing files and folders. An interruption during replacement can leave an unconfirmed draft that another prepare call can rebuild. The skill runs commands one at a time. Windows concurrency has no directory lock in this build.
