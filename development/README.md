# Local Nautobot container stack

A throwaway Nautobot 3.1.8 or 3.2.2 + Postgres + Redis stack for running the full test
suite (the contrib / REST-API / crypto tests that skip without a real Nautobot)
and exercising the plugin end-to-end. Dev-only credentials; never used in prod.

```bash
# Select a supported Nautobot release (default is 3.2.2).
export NAUTOBOT_VERSION=3.2.2

# Build + start (Nautobot auto-migrates on startup, including this plugin).
docker compose -p fwdnautobot -f development/docker-compose.yml up -d --build

# Full test suite inside the container (conftest.py runs nautobot.setup();
# -p no:django lets the DB-backed tests talk to the migrated dev database).
docker compose -p fwdnautobot -f development/docker-compose.yml \
  exec -T nautobot python -m pytest tests/ -q -p no:django

# Repeat-apply idempotence check against the real database.
docker compose -p fwdnautobot -f development/docker-compose.yml \
  exec -T nautobot nautobot-server shell < scripts/check_contrib_idempotence.py

# Prometheus metrics.
docker compose -p fwdnautobot -f development/docker-compose.yml \
  exec -T nautobot nautobot-server forward_metrics

# Tear down (removes the ephemeral database volume).
docker compose -p fwdnautobot -f development/docker-compose.yml down -v
```

Repeat the stack with `NAUTOBOT_VERSION=3.1.8` for the other supported release line.

The REST API is served at `http://localhost:8080/api/plugins/forward/` once you
run the web server (`nautobot-server runserver 0.0.0.0:8080` inside the
container); `health/`, `status/`, and `support-bundle/` require authentication.

The source tree is bind-mounted at `/source`, so code edits are live — no rebuild
needed unless dependencies change.

## Installed-Wheel Acceptance

The release gate also builds a separate image that contains the exact wheel but no `/source`
checkout. It migrates a fresh database, seeds a generic local fixture, authenticates, and requests
every plugin HTML/API route on both supported Nautobot versions:

```bash
python -m build
python scripts/check_installed_wheel.py
```

Use `--versions 3.2.2` for a focused iteration. The full local release gate always runs both
supported versions and removes its disposable containers and volumes.
