# 017. Keep a stable screen list across flow imports

## Context

A frameflow screen can appear under several stories. Its number is local to each story, and a picture path belongs to the storyboard.

## Decision

Use the first occurrence of each screen name, compared without case differences. Give imported rows a free `screen-N` ID and append them after the saved app order. An existing row with the same name keeps its ID, state and pictures. List saved rows that no longer appear in the flow for the owner to review. Treat picture and marker lines as storyboard details and import only the screen names.

## Consequences

Re-running the import after a story moves or repeats a screen keeps its saved picture history. A renamed screen appears as a new entry and the owner sees the old entry in the report. The import does not read any of the storyboard's picture files.
