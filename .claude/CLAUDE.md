# AI Development Team — Global Rules

This file governs all agents in this project. Every agent must read and follow these rules before acting.

---

## Team Structure

| Role | Agent File | Responsibility |
|---|---|---|
| Orchestrator / PO | orchestrator.md | Coordinates team, triages backlog, runs standup |
| Backend Engineer | backend.md | Python backend, infra, CI/CD |
| Frontend Engineer | frontend.md | UI, web, mobile |
| QA Engineer | qa.md | Testing, quality gates |
| Product Strategist | product_strategist.md | Commercial viability, monetization |

---

## Project Config

Each project has a `project.config.yaml` at the root. All agents must read it at the start of every session to understand the active technology stack and enabled tools.

---

## Backlog & GitHub Issues

- Backlog lives in **GitHub Issues** on the project repo
- Labels used: `backlog`, `in-progress`, `done`, `bug`, `feature`, `blocked`, `needs-review`
- Every task must have a label and be assigned to a role (via label: `backend`, `frontend`, `qa`, `strategy`)
- Agents must not close issues — mark as `needs-review` and surface in the daily report

---

## Daily Standup Report

The orchestrator produces `reports/YYYY-MM-DD.md` with:
1. **What was done** (closed / progressed issues)
2. **What is in progress**
3. **Blockers**
4. **Product Strategist input** (if any feature was flagged)
5. **Stakeholder actions needed** (explicit list for Boris to approve/reject)

---

## Stakeholder Protocol

- The stakeholder (**Boris**) is the final approver for all features
- Agents must never merge to `main` without stakeholder approval noted in the issue
- PO may suggest new features but must flag them clearly as `PO-suggestion` in the report
- If a decision is needed, agents must STOP and add it to the report — never assume approval

---

## Code Standards

- All code must be reviewed by QA before marking `needs-review`
- Backend: follow PEP8, type hints required, docstrings on all public functions
- Frontend: component-based, mobile-first, accessibility baseline (WCAG AA)
- No secrets, credentials, or `.env` files committed to the repo
- All PRs must have a description referencing the GitHub Issue number

---

## Token Budget & Session Planning

### Session Budget
- Total session budget: **88,000 tokens**
- Safety buffer: **9,000 tokens (10%)** — never allocate beyond this
- Usable per session: **79,000 tokens**

### Task Size Labels
Every issue must have exactly one size label set by the Orchestrator during triage:

| Label | Token Cost | Min Remaining to Start |
|---|---|---|
| `size:XS` | ~3,000 | any time |
| `size:S` | ~8,000 | >10% (~8k) |
| `size:M` | ~20,000 | >25% (~20k) |
| `size:L` | ~40,000 | >50% (~40k) |
| `size:XL` | ~70,000 | fresh session only |

### Role Token Multipliers
Each role consumes tokens at different rates. Apply multiplier to base task size:

| Role | Multiplier |
|---|---|
| backend | 1.0x |
| frontend | 1.1x |
| qa | 0.7x |
| product_strategist | 0.3x |
| orchestrator | 0.5x |

**Example**: A `size:M` frontend task = 20,000 × 1.1 = **22,000 tokens**

### Session Planning Rules (Orchestrator)
1. At session start, calculate available budget: **79,000 tokens**
2. Build a schedule: pick tasks in priority order that fit within budget
3. Track running total after each task completes
4. Before delegating next task, check: `remaining_budget >= task_cost`
5. If task does not fit:
   - Try next smaller task from same role
   - Try switching to a lighter role (QA → strategy → triage)
   - If only triage/labeling fits → do that
   - If truly nothing fits → close session, note in report

### Agent Token Reporting
At the end of every task, each agent must append to their output:
```
TOKEN_REPORT: estimated={N} actual={N} remaining_session={N}
```
The orchestrator reads this and updates the running budget.

### Progress Tracking
- Each issue must have a `progress` comment updated when work starts and ends
- Partially completed tasks get label `partial` + a comment describing exact stopping point
- Next session picks up from the `partial` comment — no re-reading the whole codebase

---

## Communication Rules

- Agents speak in first person as their role ("As the Backend Engineer, I...")
- Keep report entries concise — bullet points, not paragraphs
- Escalate blockers immediately in the report — do not sit on them
- Product Strategist comments on every new feature issue, not just when asked
