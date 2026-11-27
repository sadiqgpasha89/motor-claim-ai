# Test & Verification Strategy

- **Unit (`tests/unit/`):** Deterministic `Decimal` settlement math (with/without Zero-Dep, Consumables, CTL >75% IDV), estimate duplicate & rate-card variance detection, state machine transitions, hybrid BM25+vector policy retrieval.
- **Integration (`tests/integration/`):** Full E2E vertical slice via FastAPI `TestClient` (idempotent FNOL -> evidence OCR -> coverage -> triage -> surveyor -> damage -> estimate -> survey report -> fraud check -> DoA escalation -> SIU/manager approval -> payment timeout -> safe reconciliation -> repair -> close -> audit timeline).
- **Security (`tests/security/`):** Cross-tenant IDOR (`403`), garage/SIU ABAC enforcement, same-user maker-checker rejection, bulk-approval rejection, EICAR malware block, prompt injection quarantine, and agent tool-allowlist enforcement (`ToolPermissionError`).
- **Model Eval (`tests/model_eval/`):** All 11 agents typed schema conformance and AI outage manual fallback verification.
- **AI Evaluation & Release Gate (`evals/`, `tests/evals/`):** 250 golden cases (17 scenario categories), per-agent metrics, an independent exact-arithmetic settlement oracle, six safety suites and `python -m evals.gate`, which blocks a release on any regression, threshold breach or baseline drift. See [ai-evaluation.md](ai-evaluation.md).
- **Frontend (`apps/web`):** TypeScript (`tsc --noEmit`), ESLint (`npm run lint`), and Next.js production build (`npm run build`).
