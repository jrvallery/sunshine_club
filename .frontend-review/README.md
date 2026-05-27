# Frontend Review Harness

This directory contains a reusable Playwright-based UI review harness for agent-driven frontend work.

## Install

From the repository root:

```bash
npm install --save-dev @playwright/test @axe-core/playwright
npx playwright install chromium
```

## Run

Edit `.frontend-review/config.json`, then run:

```bash
node .frontend-review/scripts/review.mjs
```

Outputs are written to `.frontend-review/runs/<timestamp>/`:

- `report.md`
- `report.json`
- viewport screenshots
- full-page screenshots when enabled

## Common Modes

Use an already-running server:

```bash
node .frontend-review/scripts/review.mjs --url http://localhost:3000 --no-server
```

Review one route:

```bash
node .frontend-review/scripts/inspect.mjs /dashboard
```
