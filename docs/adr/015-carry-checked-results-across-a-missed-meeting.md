# 015. Carry checked results across a missed meeting

## Context

The owner can give a promise result while preparing a meeting that is later missed. That week gets a short record and its draft is retired.

## Decision

Keep the result and its original checked week. Show checks made since the last held meeting on the next meeting's page and PDF. Use the needs from the last held meeting and list each missed date since then.

If the last held meeting's content is absent, prepare from the available sheets and the new draft. Ask the owner for the previous needs once for that draft. Store the warning state in the untracked content snapshot.

## Consequences

The owner's result remains recorded and reaches the next client copy. The missed week keeps the delivery date and its short record.
