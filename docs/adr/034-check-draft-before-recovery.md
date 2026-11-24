# 034. Check meeting content before recovery can write

## Context

The CLI can replay a pending weekly transaction before it prepares a meeting. Undo and removal journals can replace the selected draft. Secret refusal must leave the project files unchanged.

## Options

- Check content during preparation after recovery. This fits the existing readers and allows recovery to write before refusal.
- Check the selected draft and any pending replacement first. This keeps valid recovery available and lets a secret refusal leave the journal intact.

## Decision

While holding the existing project command lock, check settings, the current draft and any recovery replacement of that draft before recovery runs. Check the recovered draft again when preparation reads that content for use. The recovery readers share their existing journal validation. Normal preparation keeps the previous recovery behavior when the check allows it.

## Consequences

An interrupted command can resume after the owner resolves a refusal. Preparation can still use a draft updated by an interrupted removal. Other CLI commands keep their existing recovery order.
