# 001. Compare a fresh rendering before confirmation and copying

## Context

The owner confirms a specific meeting draft. The draft can become stale when a waiting change or a source file changes, even if the finished item still names the same file. The Week sheet has no extra column for a version marker.

## Decision

Rebuild the page in memory for confirmation and copying. Include a fingerprint of the setup, meeting facts, draft, waiting changes and referenced file bytes in an HTML comment. Compare the full saved HTML to that rendering. Exclude the confirmation date itself so recording it leaves the approved page valid. The plain text copy comes from the freshly checked meeting facts.

## Consequences

An edited page, changed input, or missing file requires preparing the meeting again. A source contributes a digest, while its contents stay in the evidence file. Freshness covers the files the page depends on. The agent still checks that each file supports the claim it cites.
