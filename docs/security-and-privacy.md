# Security & Privacy Controls (`packages/security/`)

- **Server-side Tenant & ABAC Enforcement:** Every claim endpoint invokes `enforce_claim_abac(user, claim)`. Cross-tenant IDOR returns `403 NOT_AUTHORISED`. Garages see only assigned claims with customer PII omitted; surveyors see only assigned claims; policyholders see only their own claims.
- **Restricted Sub-domains:** SIU fraud alerts and entity graphs require `SIU_ALLOWED_ROLES`. Third-party injury/medical party records require `TP_LEGAL_ALLOWED_ROLES`. EV cases show a policyholder only a customer safety view; surveyors and EV garages see an EV case only on claims assigned to them and may record work only for their own organisation (`partner_id`).
- **Maker-Checker & Anti-Tamper:** `validate_approval_authority` forbids same-user maker & checker (`403 NOT_AUTHORISED`). Bulk approval/repudiation/payout endpoints are explicitly disabled (`403`).
- **Upload Hardening (`validate_upload_bytes`):** Enforces size limit, magic-byte MIME sniffing, EICAR malware signature rejection, and SHA-256 checksums.
- **Prompt Injection & PII Masking:** Untrusted OCR/chat text passes through `sanitize_untrusted_text` and `mask_text_pii` before logging or agent execution.
