# AI PR reviews

- GitHub Agentic Workflows + Pi + OpenRouter; read-only analysis, advisory comments.
- Automatic: triggering actor has write, maintain, or admin access.
- Otherwise: maintainer posts `/ai-review`; current revision selected when the job runs.

## Edit

| File | Settings |
| --- | --- |
| [workflows/ai-review.md](workflows/ai-review.md) | Prompt, triggers, `on.roles`, provider, tools, limits, publication checks. |
| [scripts/ai-review.cjs](scripts/ai-review.cjs) | `hasWriteAccess()`, event checks, `/ai-review`, approval-request text. |
| [workflows/ai-review-request.yml](workflows/ai-review-request.yml) | Approval-request triggers and permissions. |

Keep `on.roles` and `hasWriteAccess()` aligned.

Generated; do not edit: `workflows/ai-review.lock.yml`, `aw/actions-lock.json`.

## Settings

Target repository → **Settings → Secrets and variables → Actions**.

| Setting | Location / value |
| --- | --- |
| `OPENROUTER_API_KEY` | Repository secret; dedicated inference key. |
| `AI_REVIEW_MODEL` | Repository variable; `z-ai/glm-5.3-flash`. |
| `model-provider` | Workflow: `openai`; endpoint: `https://openrouter.ai/api/v1`. |
| `timeout-minutes` / `max-turns` | Workflow: `15` / `40`. |
| `max-ai-credits` | Workflow: `200` = USD 2 estimated per run. |
| Monthly budget | OpenRouter key: USD 10, monthly reset; configured separately. |

## Compile — gh-aw v1.0.1

From the repository root; commit regenerated files with source changes:

```bash
gh aw compile ai-review --validate --shellcheck --no-check-update
```
