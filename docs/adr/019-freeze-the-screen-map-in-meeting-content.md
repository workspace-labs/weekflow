# 019. Freeze the screen map in meeting content

## Context

Screens can change while the owner is still closing a confirmed meeting. The page and PDF need one set of screen states, dates, comparisons and picture checks.

## Decision

Prepare saves screen order, words and references with digests in the existing numbered content snapshot. Enable picture rendering only for meetings that use these new fields. When a picture changes, compare with the last held meeting's picture where available, or with the saved earlier picture. A screenshot can be marked New when its digest differs from what was shown and its capture date is after the last held meeting, provided the app ran. A missed meeting does not become the date used for comparison.

Check every displayed image before confirming or making a client copy. When the owner checked a picture after preparation, use its digest-bound receipt. Validate each saved picture against the snapshot before trusting a confirmed page. Record, sign and lock use the saved view and do not reread the live Screens sheet.

During preparation, a missing file becomes an unavailable picture slot with the saved reference and digest. The owner sees which screens need pictures. The page and PDF show the absence and omit the New mark. Preparation still refuses altered files. A meeting that already showed an image still needs that image to verify its saved copy.

## Consequences

Changing the live order, names or pictures leaves earlier meetings usable. A missing or altered file names the stale picture. The snapshot and its approved removal notices remain the historical copy without new Weeks columns.
