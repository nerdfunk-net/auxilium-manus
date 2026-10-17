## What and why

<!-- What does this change, and why? Link the issue if there is one. -->

## How it was tested

<!-- Tests added or changed, commands run, manual checks. -->

## Checklist

- [ ] A test that failed before the change (for a fix) or covers the new behaviour
- [ ] `ruff check`, `pyright`, the five guard scripts and `pytest` pass (backend); `npm run lint`, `npx tsc --noEmit` and `npm test` pass (frontend)
- [ ] Only the files I changed were formatted
- [ ] No secrets or real device data in code, fixtures or docs
- [ ] `CHANGELOG.md` "Upgrade notes" updated if an operator has to do something on upgrade
