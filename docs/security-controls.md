# Enterprise Security Controls (Phase 3)

This page covers feedback item 17. Security is enforced at the tool, service, API and data layers. Prompts enforce nothing.
Status values: **Built** (code and tests), **Partly** (some of it), **Infrastructure** (needs a platform service, only the hook is here).

Controls and limits are in `rules/common/security_controls.json` (rule `IN-SECURITY-CONTROLS-2026`).

## The seven backend checks

`services/integrations/gateway.py` runs these checks on every tool call. A denied call is audited as `TOOL_DENIED`.

| Check | How |
|---|---|
| User authorised | The role must be in the tool policy. |
| Agent allowed the tool | The agent name must be in the tool policy. |
| Claim in scope | `enforce_claim_abac` (tenant, policyholder, garage, surveyor scope). |
| Action allowed in the state | The claim status must be in the tool policy. |
| Approval required | An approved approval for the claim. The maker cannot run the action it authorises. |
| Idempotent | A unique key per tool call. A replay returns the first result. A key with a different request returns 409. |
| Safe | Required parameters, rate limit, retry and circuit breaker, no raw contact data. |

Payment is not a gateway tool. No agent can move money. Payment goes through `POST /claims/{id}/payments`, which needs the
finance role, an approved settlement, an idempotency key, and pays only the settlement net minus money already paid.

## Control list

| Control | Status | Where |
|---|---|---|
| OAuth2 / OIDC | Infrastructure | The demo issues its own JWT. Put an identity provider in front. The role and tenant claims stay the same. |
| MFA | Built (demo) | TOTP in `packages/security/mfa.py`. `MFA_STEP_UP_ENABLED=true` requires step-up for payment initiation and approval decisions. The demo secret is derived from the server key. A real deployment keeps it in the identity provider. |
| Role, attribute and claim level access | Built | `require_roles`, `enforce_claim_abac`, SIU and TP access guards. |
| Tenant and partner isolation | Built | Tenant check in `enforce_claim_abac`. Garage and surveyor see only assigned claims. Tested. |
| Encryption in transit and at rest | Infrastructure | Use TLS and database or disk encryption. No application code claims this. |
| Secrets | Partly | `SecretsProvider` interface. In production the API refuses to start with the demo signing key. |
| PII redaction and rehydration | Built | `packages/security/pii.py`. The LLM gateway redacts before the model call. The API never returns rehydrated text. |
| Evidence retention and legal hold | Built | `services/claims/retention.py`. Hold blocks purge. Purge keeps a tombstone with the sha256. |
| Retention and deletion | Built | `POST /operations/retention/purge` (admin, dry run by default). Seven years after closure, illustrative. |
| Prompt-injection defence | Partly | Upload sanitiser (existing) and output validation. A test suite comes in Phase 4. |
| Tool-call authorisation | Built | The tool gateway. |
| Output validation | Built | `validate_model_output`: size, forbidden decisions, raw PII. A failure needs a human. |
| Rate limits | Built | Failed logins (10 per minute), tool calls and LLM calls per user. In process memory. |
| Audit-log integrity | Built | SHA-256 hash chain. `GET /operations/audit/integrity` finds the first broken event. |
| Segregation of duties | Built | The maker cannot be the checker. The approval maker cannot run the approved action. |
| Payment authorisation | Built | Finance role, approved settlement, MFA step-up (when on), idempotency, no double payment. |
| Disaster recovery and incident response | Documented | See the runbook below. |

## Audit chain

Each audit event stores the hash of the previous event and its own hash. A change to any field, or to any earlier event,
breaks the chain at that point. Events from before this change have no hash. They are counted and not checked.

`shortcut:` the chain assumes one writer per tenant. With many API instances, add a per-tenant lock or sequence.

## Disaster recovery and incident response (runbook)

1. **Backups.** Back up the database every day and keep the evidence store in versioned object storage. Test a restore each quarter.
2. **Recovery targets.** Set them with the business. The demo has none.
3. **Suspected data leak.** Revoke the signing key. Run `GET /operations/audit/integrity`. Place a legal hold on affected claims.
4. **Suspected tampering.** If the chain is broken, freeze writes, copy the database, and compare with the last good backup.
5. **Provider outage.** The model gateway circuit opens. Claims continue on the manual path. Check `GET /operations/integration-resilience`.
6. **After the incident.** Write a blameless review. Add a test for the failure.
