# 023. Preview docs decisions with native controls

## Context

A docs meeting presents decisions inside real sentences and repeats their live answers in a table. The page must work offline with scripts off.

## Decision

Reuse the five fragment links and a native radio group for each decision. CSS selectors show the matching option in each sentence and table cell. Each decision contributes one value to the running count. Reuse the existing local Save download, with the visible option labels as values and `later` for the built-in deferral.

## Consequences

The page grows by the controls, styles and sentence occurrences for each added decision. The preview works with scripts off. With scripts on, Save supplies the same answers the agent can enter manually. The client PDF uses the same saved labels and total.
