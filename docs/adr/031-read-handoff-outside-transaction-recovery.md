# 031. Read the handoff without recovering writes

## Context

The usual command path finishes interrupted writes under the project folder lock. Those repairs can replace or remove files. The date handoff has to read a consistent history and leave every project file as it was, including when an earlier write was interrupted.

## Decision

Use the existing project folder lock for the handoff. Skip write recovery on that command and refuse when a pending transaction or removal staging file is present. The owner can resume the interrupted weekly command to complete recovery and then retry the handoff.

## Consequences

The date handoff cannot export a partly updated history, such as a name removal only applied to some records. Existing commands still run their usual recovery. Neither the preview nor the confirmed output creates a file.
