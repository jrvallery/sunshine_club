# Agent Worktree Workflow

Last updated: 2026-05-27

## Goal

Allow multiple agents to work on this project at the same time without changing
each other's selected branch or clobbering local runtime files.

Git branches are checked out per working directory. If two agents share one
directory, a `git switch` by one agent changes the branch underneath the other
agent. The fix is one git worktree per agent.

## Worktrees

Canonical integration checkout:

```text
/home/james/projects/active/sunshine_club
branch: main
```

Backend / project lead checkout:

```text
/home/james/projects/active/sunshine_club_backend
branch: backend/main-agent
```

Frontend review checkout:

```text
/home/james/projects/active/sunshine_club_frontend
branch: frontend-review/agent
```

Agents should not switch branches in another agent's worktree.

## Agent Ownership

Backend / project lead agent:

- Works in `/home/james/projects/active/sunshine_club_backend`.
- Owns backend, extraction, OCR, embeddings, LangGraph, DB schema, API routes,
  tests, run orchestration, and integration decisions.
- May inspect frontend code and make small unblockers, but should avoid broad UI
  changes while the frontend review agent is active.

Frontend review agent:

- Works in `/home/james/projects/active/sunshine_club_frontend`.
- Owns dashboard UX, layout, accessibility, visual polish, table/filter behavior,
  and frontend review tooling.
- Should avoid backend/API/schema changes unless explicitly requested.

Main checkout:

- Used for integration merges and final verification.
- Keep it clean when possible.

## Runtime Ports

Use separate ports when both agents need live servers.

Backend agent:

```bash
cd /home/james/projects/active/sunshine_club_backend
export SUNSHINE_REVIEW_DB_PATH=.local/backend-review.sqlite
.venv/bin/uvicorn sunshine_api.main:app --host 0.0.0.0 --port 8001
npm --workspace apps/dashboard run dev -- --hostname 0.0.0.0 --port 3001
```

Frontend review agent:

```bash
cd /home/james/projects/active/sunshine_club_frontend
export SUNSHINE_REVIEW_DB_PATH=.local/frontend-review.sqlite
.venv/bin/uvicorn sunshine_api.main:app --host 0.0.0.0 --port 8002
npm --workspace apps/dashboard run dev -- --hostname 0.0.0.0 --port 3002
```

The frontend worktree may need its own dependency install if `node_modules` or
`.venv` are not available there. Prefer local setup per worktree over sharing
mutable generated directories.

## Mac Tunnels

Backend agent UI:

```bash
ssh -N -L 3001:127.0.0.1:3001 -L 8001:127.0.0.1:8001 james@192.168.30.63
```

Open:

```text
http://localhost:3001/runs
```

Frontend review UI:

```bash
ssh -N -L 3002:127.0.0.1:3002 -L 8002:127.0.0.1:8002 james@192.168.30.63
```

Open:

```text
http://localhost:3002/review
```

## Merge Back To Main

When a branch is ready:

```bash
cd /home/james/projects/active/sunshine_club
git switch main
git merge backend/main-agent
git merge frontend-review/agent
.venv/bin/python -m pytest -q
npm --workspace apps/dashboard run build
```

Resolve conflicts on `main`, rerun full verification, then keep or delete merged
worktrees as appropriate.

## Cleanup

List worktrees:

```bash
git worktree list
```

Remove a finished worktree after its branch is merged:

```bash
git worktree remove /home/james/projects/active/sunshine_club_frontend
```

