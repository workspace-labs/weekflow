# 003. Keep a canonical copy of the meeting content

## Context

The agent writes a draft and the tool later needs the same input to check the HTML. Decisions must come from the change log.

## Decision

Accept a project-relative content path or an absolute path within the project. Keep the approved content fields under the meeting's numbered content filename. Default missing lists to empty and leave an unknown need date unstated. Ignore extra content keys.

## Consequences

A draft may start in a temporary project file and confirmation reads the numbered copy. Text outside the defined fields has no effect on the meeting, including any purported decisions.
