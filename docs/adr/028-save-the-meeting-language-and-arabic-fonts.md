# 028. Save the meeting language and Arabic fonts

## Context

An Arabic meeting can be closed or rebuilt after the project setup or design changes. English pages and PDFs already have saved confirmations and receipts.

## Decision

Save `language: ar` in the numbered week at preparation or when recording a missed Arabic meeting. Read weeks without a language as English. Use the week's language on a refresh and throughout recording, closing and removal. New weeks take their language from project setup.

Use two Arabic font roles, Regular and Bold, only for Arabic. Keep the Arabic font metadata in the page fingerprint even for Studio. Arabic and Latin runs use their respective Arabic and text faces. Keep the existing digest-addressed storage, recovery from saved HTML or local project files, and Studio substitution when the saved face is unavailable.

## Consequences

The original Arabic font digests also bind the PDF receipt through the page fingerprint. Older English records retain their format, receipts and rendering.
