# Integration tests

Heavy tests against real network devices and/or live external services
(Nautobot, ISE, git remotes, etc.).

**Not run by default.** Plain `pytest` from `backend/` only collects `tests/unit`.

## Run

```bash
cd backend
python -m pytest tests/integration
# or:
python -m pytest -m integration
```

## Conventions

- Mark every test (or module) with `@pytest.mark.integration`.
- Credentials and device targets come from environment / local ignore-listed
  config — never commit secrets or lab IPs into the suite.
- Keep mocked / in-memory tests in `tests/unit/`.
