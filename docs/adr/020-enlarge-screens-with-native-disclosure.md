# 020. Enlarge screens with native disclosure controls

## Context

The meeting uses fragments to select one of five panels. Using a screen fragment to enlarge a picture would hide See it. The client must be able to enlarge and close a screen even when scripts are off.

## Decision

Use a native `details` and `summary` for a screen card. Expand it in place, using the same image elements at a larger size. Keep the earlier and current pictures in one two-column comparison. The PDF uses the same prepared screen states and picture captions in print-sized cards.

## Consequences

The meeting fragment and pressed answers stay in place. The browser handles keyboard activation and disclosure state. Each displayed picture has one embedded source per slot, which limits the size of the offline page.
