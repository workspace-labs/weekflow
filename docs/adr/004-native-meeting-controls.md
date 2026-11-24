# 004. Use native controls for the meeting page

## Context

The five tabs, Back and Next, and decision answers must all work with scripts off in a single file.

## Decision

Use one named disclosure group for step navigation. A tab, Back, or Next opens its disclosure and closes the previous one. The active tab is an indicator with `aria-current="step"`. Each decision has its own native radio group, initially unchecked.

## Consequences

Tabs, Back and Next work with the browser's normal keyboard navigation and disclosure activation. Decision radios retain their selections when the user changes steps. The browser holds both states for the open page. A decision press leaves the project's records untouched.
