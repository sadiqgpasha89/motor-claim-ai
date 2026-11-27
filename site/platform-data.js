/* GENERATED FILE - do not edit by hand.
 * Source: live calls to the Phase 3 platform controls (DEMO / SYNTHETIC data).
 * Regenerate with: python scripts/export_platform_demo_data.py
 */
window.PLATFORM_DEMO = {
 "generated_for": "DEMO / SYNTHETIC",
 "tool_policy": {
  "tool_policy": {
   "policy_lookup": {
    "port": "policy_admin",
    "side_effect": false,
    "idempotency_required": false,
    "approval_required": false,
    "allowed_agents": [
     "coverage_intelligence",
     "claim_triage",
     "human"
    ],
    "allowed_roles": [
     "claims_handler",
     "claims_manager",
     "auditor"
    ],
    "allowed_states": [
     "*"
    ]
   },
   "claims_ledger_post": {
    "port": "claims_system",
    "side_effect": true,
    "idempotency_required": true,
    "approval_required": false,
    "allowed_agents": [
     "orchestrator",
     "human"
    ],
    "allowed_roles": [
     "claims_handler",
     "claims_manager"
    ],
    "allowed_states": [
     "*"
    ]
   },
   "garage_book": {
    "port": "garage",
    "side_effect": true,
    "idempotency_required": true,
    "approval_required": false,
    "allowed_agents": [
     "provider_coordination",
     "human"
    ],
    "allowed_roles": [
     "claims_handler",
     "claims_manager"
    ],
    "allowed_states": [
     "REGISTERED",
     "VALIDATION",
     "TRIAGE",
     "ASSESSMENT",
     "ESTIMATE_VALIDATION",
     "ESTIMATE_REVIEW",
     "APPROVED",
     "REPAIR_IN_PROGRESS"
    ]
   },
   "surveyor_assign": {
    "port": "surveyor",
    "side_effect": true,
    "idempotency_required": true,
    "approval_required": false,
    "allowed_agents": [
     "provider_coordination",
     "human"
    ],
    "allowed_roles": [
     "claims_handler",
     "claims_manager"
    ],
    "allowed_states": [
     "REGISTERED",
     "VALIDATION",
     "TRIAGE",
     "ASSESSMENT",
     "ESTIMATE_VALIDATION",
     "ESTIMATE_REVIEW"
    ]
   },
   "notify": {
    "port": "messaging",
    "side_effect": true,
    "idempotency_required": true,
    "approval_required": false,
    "allowed_agents": [
     "customer_communication",
     "human"
    ],
    "allowed_roles": [
     "claims_handler",
     "claims_manager"
    ],
    "allowed_states": [
     "*"
    ]
   },
   "payment_execute": {
    "port": "payment_gateway",
    "side_effect": true,
    "idempotency_required": true,
    "approval_required": true,
    "route_only": true,
    "allowed_agents": [],
    "allowed_roles": [
     "finance_approver"
    ],
    "allowed_states": [
     "APPROVED",
     "PAYMENT_PENDING"
    ]
   }
  },
  "checks": [
   "user authorised",
   "agent allowed the tool",
   "claim in scope",
   "action allowed in current state",
   "approval present when required",
   "idempotent",
   "safe (valid input, rate limit, resilient call)"
  ]
 },
 "tool_calls": {
  "retry_then_success": {
   "http_status": 200,
   "body": {
    "tool": "garage_book",
    "replayed": false,
    "status": "succeeded",
    "result": {
     "booking_ref": "GBK-38C85B9211",
     "slot": "10:00"
    },
    "attempts": 3
   }
  },
  "idempotent_replay": {
   "http_status": 200,
   "body": {
    "tool": "garage_book",
    "replayed": true,
    "status": "succeeded",
    "result": {
     "booking_ref": "GBK-38C85B9211",
     "slot": "10:00"
    },
    "attempts": 3
   }
  },
  "denied_agent": {
   "http_status": 403,
   "body": {
    "error_code": "NOT_AUTHORISED",
    "message": "Agent 'claim_triage' is not allowed to use tool 'garage_book'.",
    "correlation_id": "34acdd67-d5d4-4a5c-a914-0b02af2afbc8",
    "details": null
   }
  },
  "denied_payment_tool": {
   "http_status": 403,
   "body": {
    "error_code": "NOT_AUTHORISED",
    "message": "Agent 'human' is not allowed to use tool 'payment_execute'.",
    "correlation_id": "2622646a-cef5-4822-b61a-fca067ecaa43",
    "details": null
   }
  },
  "outage_then_fast_fail": [
   {
    "http_status": 503,
    "body": {
     "error_code": "DEPENDENCY_UNAVAILABLE",
     "message": "surveyor is unavailable after 3 attempts.",
     "correlation_id": "a9933383-fc37-491b-a387-bef7c7f5249a",
     "details": null
    }
   },
   {
    "http_status": 503,
    "body": {
     "error_code": "DEPENDENCY_UNAVAILABLE",
     "message": "Circuit 'surveyor' is open",
     "correlation_id": "64c4579d-35ec-4df6-b6e4-ff5faa770442",
     "details": null
    }
   }
  ]
 },
 "circuit_breakers": {
  "circuit_breakers": [
   {
    "name": "garage",
    "state": "closed",
    "consecutive_failures": 0
   },
   {
    "name": "surveyor",
    "state": "open",
    "consecutive_failures": 3
   },
   {
    "name": "claims_system",
    "state": "closed",
    "consecutive_failures": 0
   }
  ],
  "tool_invocations": {
   "succeeded": 1,
   "failed": 1
  }
 },
 "event_bus": {
  "failing_consumer_passes": [
   {
    "delivered": 0,
    "failed": 22,
    "dead": 0,
    "skipped": 0
   },
   {
    "delivered": 0,
    "failed": 22,
    "dead": 0,
    "skipped": 0
   },
   {
    "delivered": 0,
    "failed": 0,
    "dead": 22,
    "skipped": 0
   }
  ],
  "dead_deliveries": {
   "dead": 22
  },
  "replayed": {
   "id": "b351dc96-0dc7-4fd6-8042-1d2fa10a6a8e",
   "status": "pending"
  },
  "after_recovery": {
   "consumers": [
    "claims_ledger",
    "customer_notifications"
   ],
   "delivered": 1,
   "failed": 0,
   "dead": 0,
   "skipped": 21
  }
 },
 "audit_integrity": {
  "ok": true,
  "checked": 44,
  "legacy_unchained": 0,
  "head_hash": "a45050450f3e229c10f56f08edda73fc48dc8bb9e5e6a6bc0a2f19d2554abc87"
 },
 "llm_gateway": {
  "text": "[summary] Processed 1 minimised claim context keys safely.",
  "pii_tokens_redacted": 2,
  "model": "motorclaim-deterministic-stub",
  "model_version": "1.0.0",
  "usage": {
   "tokens_input": 14,
   "tokens_output": 15,
   "source": "estimated",
   "cost_inr": "0.0118"
  }
 }
};
