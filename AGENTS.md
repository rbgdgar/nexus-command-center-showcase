# NEXUS contributor instructions

## Milestone delivery

- Inspect the roadmap, Git status, and existing diff before editing.
- Implement one milestone at a time and create exactly one dedicated commit.
- Never absorb pre-existing work into a later milestone without explicit approval.
- Preserve the local-first architecture and existing safety boundaries.
- Stop for broken or unsafe-to-fix tests, credentials, destructive operations, or
  architecture decisions that require user direction.

## Required validation

Run from the repository root before every milestone commit:

```powershell
python -m compileall backend tests
python -m unittest discover -v
python -c "from backend.main import app; print('API OK', app.version)"
npm --prefix frontend run lint
npm --prefix frontend run build
git status --short --ignored
```

Confirm that `.env`, `.venv`, `node_modules`, `frontend/dist`, databases, caches,
bytecode, and logs are not staged. On Windows, explicitly close SQLite test
connections before cleaning temporary directories.

## Safety invariants

- Project indexing stays within configured approved roots and excludes secrets,
  VCS metadata, dependencies, generated files, binaries, and runtime databases.
- Read-only tools may execute automatically. Writes and privileged actions require
  approval. Destructive operations remain blocked.
- Subprocess integrations use allow-listed argument arrays with `shell=False`.
- Terraform apply requires approval; Terraform destroy remains blocked.
