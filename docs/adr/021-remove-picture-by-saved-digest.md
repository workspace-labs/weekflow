# 021. Remove a saved picture by its digest

## Context

The same saved picture can appear under different filenames and in several weeks. A locked page or PDF can survive even after the facts needed to rebuild it are lost.

## Decision

Use the selected saved file's digest to find its managed copies and snapshot slots. Replace those slots with the dated removal notice and add one Corrections entry for each affected locked week. Preserve the Weeks record, including its decisions and signature. Retire matching image files and check receipts through the replacement-only recovery journal from ADR 013. Keep the digest and earliest date used to prevent a later relabel.

Verify the source of each matching page or PDF before replacing it. If a locked copy cannot be rebuilt, keep its bytes and include the warning in the removal receipt and the recovery journal.

An exact picture reference in Screens or a saved snapshot can be removed after its file is lost. If the saved facts and PDF are present and the renderer is unavailable, refuse before publishing any part of the removal so the owner can retry with ReportLab.

When removal rebuilds a confirmed, unlocked page, keep the prior answers fingerprints in the content snapshot. Bind them to the complete facts of the rebuilt view. Later removals can carry forward the fingerprints that still apply. Downloads continue to contain one fingerprint, and the rebuilt page and PDF use their new fingerprint.

## Consequences

The next command can finish publishing a removal without restoring the picture. A surviving copy whose facts cannot be checked may still hold the picture. The owner receives the affected week number and can arrange to replace any previously sent PDF.
