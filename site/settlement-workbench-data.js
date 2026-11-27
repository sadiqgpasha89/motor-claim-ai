/* GENERATED FILE - do not edit by hand.
 * Source: rules/india/*.json, knowledge/synthetic_policy_samples/*.json
 * Regenerate with: python scripts/export_settlement_workbench_data.py
 */
(function (root) {
  "use strict";
  var data = {
  "depreciation": {
    "rule_id": "IN-MOTOR-DEPRECIATION-2024",
    "version": "1.0.0",
    "part_category_rates": {
      "rubber_nylon_plastic_tyres_tubes_batteries_airbags": "0.50",
      "fibreglass": "0.30",
      "glass": "0.00",
      "painting_material_component_ratio": "0.50",
      "labour": "0.00",
      "consumables_default": "1.00"
    },
    "metal_wood_age_schedule": [
      {
        "max_months": 6,
        "rate": "0.00",
        "label": "Up to 6 months"
      },
      {
        "max_months": 12,
        "rate": "0.05",
        "label": "6 months to 1 year"
      },
      {
        "max_months": 24,
        "rate": "0.10",
        "label": "1 to 2 years"
      },
      {
        "max_months": 36,
        "rate": "0.15",
        "label": "2 to 3 years"
      },
      {
        "max_months": 48,
        "rate": "0.25",
        "label": "3 to 4 years"
      },
      {
        "max_months": 60,
        "rate": "0.35",
        "label": "4 to 5 years"
      },
      {
        "max_months": 120,
        "rate": "0.40",
        "label": "5 to 10 years"
      },
      {
        "max_months": 9999,
        "rate": "0.50",
        "label": "Above 10 years"
      }
    ],
    "compulsory_deductible_by_vehicle_class_inr": {
      "private_car_under_1500cc": "1000.00",
      "private_car_over_1500cc": "2000.00",
      "two_wheeler": "100.00",
      "ev_private_car": "1500.00",
      "commercial_goods": "2500.00"
    },
    "zero_depreciation_addon_waives_part_depreciation": true,
    "consumables_addon_covers_consumables": true,
    "constructive_total_loss_idv_ratio_threshold": "0.75"
  },
  "doa": {
    "rule_id": "IN-DOA-MATRIX-2026",
    "version": "1.0.0",
    "authority_tiers": [
      {
        "role": "claims_handler",
        "max_settlement_inr": "75000.00",
        "allowed_claim_types": [
          "own_damage",
          "cashless",
          "reimbursement"
        ],
        "disallowed_conditions": [
          "fraud_alert_open",
          "total_loss",
          "repudiation",
          "tp_injury",
          "ev_battery",
          "high_risk_complex"
        ]
      },
      {
        "role": "claims_manager",
        "max_settlement_inr": "500000.00",
        "allowed_claim_types": [
          "own_damage",
          "cashless",
          "reimbursement",
          "theft",
          "total_loss",
          "commercial_fleet"
        ],
        "disallowed_conditions": [
          "tp_fatality"
        ]
      },
      {
        "role": "legal_tp",
        "max_settlement_inr": "1500000.00",
        "allowed_claim_types": [
          "third_party",
          "own_damage"
        ],
        "disallowed_conditions": []
      },
      {
        "role": "finance_approver",
        "max_settlement_inr": "5000000.00",
        "allowed_claim_types": [
          "own_damage",
          "cashless",
          "reimbursement",
          "theft",
          "total_loss",
          "third_party",
          "commercial_fleet"
        ],
        "disallowed_conditions": [],
        "required_for_payment_release": true
      }
    ]
  },
  "scenario_rule": {
    "rule_id": "IN-SETTLEMENT-SCENARIOS-2026",
    "version": "1.0.0",
    "jurisdiction": "IN",
    "title": "Settlement Decision Workbench - Scenario Parameters, Labels & Policy Clause Map",
    "source_reference": "Synthetic Insurer Settlement Playbook V1 (demo)",
    "owner": "Motor Claims Product Owner",
    "effective_from": "2026-01-01T00:00:00Z",
    "effective_to": null,
    "status": "published",
    "policy_document_id": "POL-WORDING-PC-2024",
    "parameters": {
      "ctl_stress_repair_ratio_of_idv": "0.90",
      "salvage_disposal_cost_ratio": "0.05",
      "supplementary_reinspection_variance_threshold": "0.20",
      "voluntary_deductible_options_inr": [
        "0.00",
        "2500.00",
        "5000.00",
        "7500.00",
        "15000.00"
      ],
      "deductible_matrix_vehicle_classes": [
        "private_car_under_1500cc",
        "ev_private_car",
        "private_car_over_1500cc"
      ],
      "reimbursement_documents": [
        "Original GST repair invoice",
        "Proof of payment to the workshop",
        "Repair completion and delivery confirmation",
        "Photographs of the repaired vehicle"
      ]
    },
    "labels": {
      "duplicate_line": "Duplicate quote line removed",
      "rate_variance": "Quoted rate above benchmark rate card",
      "repair_substitution": "Repair assessed instead of replacement",
      "evidence_pending": "Line held pending photographic evidence",
      "idv_basis": "Settled on IDV (agreed value) basis instead of the requested value",
      "tariff_depreciation": "Depreciation deduction (tariff schedule)",
      "addon_zero_dep": "Zero Depreciation add-on benefit",
      "addon_consumables": "Consumables add-on benefit",
      "compulsory_excess": "Compulsory excess",
      "voluntary_excess": "Voluntary deductible",
      "other_deductions": "Other eligible deductions",
      "salvage_retained": "Salvage value retained by the owner",
      "pro_rata": "Pro-rata reduction for underinsurance (IDV / market value)",
      "floor_cap": "Floor at zero / IDV cap adjustment",
      "approved_amount": "Approved repair amount",
      "net_payable": "Net payable",
      "basis_garage_quote": "Garage repair quote as submitted",
      "basis_garage_quote_plus_supplementary": "Garage quote plus supplementary estimate as submitted",
      "basis_market_value": "Market value of the vehicle at date of loss, as expected by the customer",
      "basis_repair_estimate": "Structural repair estimate as submitted",
      "payee_network_garage": "Network garage (direct settlement)",
      "payee_customer": "Customer (bank transfer)",
      "outcome_cashless": "Repaired vehicle returned by the network garage; insurer pays the garage directly",
      "outcome_reimbursement": "Cash reimbursement after GST invoice, proof of payment and repair completion",
      "outcome_repair": "Repaired (not replaced) panels; insurer pays the garage directly",
      "outcome_partial": "Approved lines repaired now; withheld line payable once evidence is supplied",
      "outcome_supplementary": "Revised settlement covering the original repair plus hidden damage",
      "outcome_total_loss": "Total loss payout against surrender of the vehicle and its documents",
      "outcome_ctl_retention": "Constructive total loss payout; owner keeps the wreck and its assessed salvage value is deducted",
      "outcome_ctl_not_triggered": "Repair threshold not reached; repair settlement stands",
      "outcome_addon": "Repair settlement with the add-on applied",
      "outcome_deductible": "Repair settlement at the selected excess levels",
      "outcome_pro_rata": "Repair settlement reduced pro-rata for underinsurance (what-if)",
      "role_settlement_agent": "Settlement recommendation agent (recommendation only, always routed to a human)",
      "role_maker": "Claims officer (maker)",
      "role_claims_handler": "Claims Handler",
      "role_claims_manager": "Claims Manager",
      "role_legal_tp": "Legal / TP Counsel",
      "role_finance_approver": "Finance Approver",
      "role_admin": "Administrator",
      "skip_amount_exceeds_limit": "amount exceeds the role's settlement limit",
      "skip_claim_type_not_allowed": "claim type is not in the role's allowed list",
      "skip_condition_blocked": "an active condition requires a higher tier",
      "maker_checker_note": "Maker and checker must be different users (IN-DOA-MATRIX-2026); bulk approval is forbidden.",
      "approval_demo_note": "Illustrative authority resolution for a synthetic claim - no real approval has been recorded.",
      "assessor_decision_holdback": "Claims handler withheld the line and opened an evidence follow-up instead of rejecting the claim",
      "assessor_decision_none": "No lines withheld; all assessed lines approved",
      "assessor_decision_reinspection": "Surveyor re-inspection required because the supplementary uplift crossed the variance threshold",
      "assessor_decision_no_reinspection": "Supplementary uplift is within the re-inspection variance threshold",
      "option_replace": "Replace bumper and fender",
      "option_repair": "Repair and refinish bumper and fender"
    },
    "scenarios": [
      {
        "code": "cashless_repair",
        "number": 1,
        "label": "Cashless garage repair",
        "group": "Settlement pathway",
        "pathway": "cashless",
        "claim_type": "cashless",
        "status": "recommended",
        "summary": "The insurer settles the approved amount directly with a network garage; the customer pays only the excess and any non-admissible amount.",
        "assumptions": [
          "Network garage is bound to the benchmark rate card, so duplicate and above-benchmark quote lines are removed before billing.",
          "Customer pays the difference between the assessed repair invoice and the insurer's payment at the garage."
        ],
        "clauses": [
          {
            "id": "SEC-1-1",
            "applied_for": "Accidental external means is an insured peril"
          },
          {
            "id": "SEC-1-2",
            "applied_for": "Standard parts depreciation schedule applied line by line"
          },
          {
            "id": "ADDON-ZD-01",
            "when": "zd_active",
            "applied_for": "Part and paint depreciation waived"
          },
          {
            "id": "ADDON-CONS-01",
            "when": "cons_active",
            "applied_for": "Consumables covered instead of fully deducted"
          },
          {
            "id": "SEC-1-5",
            "applied_for": "Excess deducted once from the amount payable"
          },
          {
            "id": "COND-CLAIM-02",
            "applied_for": "Cashless settlement directly with the network garage"
          }
        ]
      },
      {
        "code": "reimbursement",
        "number": 2,
        "label": "Reimbursement claim",
        "group": "Settlement pathway",
        "pathway": "reimbursement",
        "claim_type": "reimbursement",
        "status": "alternative",
        "summary": "The customer repairs at any workshop, pays the invoice and is reimbursed the admissible amount against documents.",
        "assumptions": [
          "Non-network invoice is assumed equal to the quoted amount, so the customer first funds the whole invoice.",
          "The insurer's admissible amount is identical to cashless; the difference is who funds the repair and how much stays with the customer."
        ],
        "clauses": [
          {
            "id": "SEC-1-1",
            "applied_for": "Accidental external means is an insured peril"
          },
          {
            "id": "SEC-1-2",
            "applied_for": "Standard parts depreciation schedule applied line by line"
          },
          {
            "id": "ADDON-ZD-01",
            "when": "zd_active",
            "applied_for": "Part and paint depreciation waived"
          },
          {
            "id": "ADDON-CONS-01",
            "when": "cons_active",
            "applied_for": "Consumables covered instead of fully deducted"
          },
          {
            "id": "SEC-1-5",
            "applied_for": "Excess deducted once from the amount payable"
          },
          {
            "id": "COND-CLAIM-02",
            "applied_for": "Reimbursement against GST invoice, payment proof and completion confirmation"
          }
        ]
      },
      {
        "code": "repair_vs_replacement",
        "number": 3,
        "label": "Repair vs replacement",
        "group": "Settlement pathway",
        "pathway": "cashless",
        "claim_type": "cashless",
        "status": "alternative",
        "summary": "Compares replacing the bumper and fender with repairing and refinishing them; labour carries no depreciation and paint only 25%.",
        "assumptions": [
          "Surveyor and damage assessment confirm both panels are technically repairable; safety-critical parts are always replaced.",
          "Repair lines use the garage's alternative repair quote for the same panels."
        ],
        "clauses": [
          {
            "id": "SEC-1-8",
            "applied_for": "Insurer may repair instead of replace where feasible and safe"
          },
          {
            "id": "SEC-1-2",
            "applied_for": "Paint material depreciated at 25%; labour at 0%"
          },
          {
            "id": "ADDON-ZD-01",
            "when": "zd_active",
            "applied_for": "Paint depreciation waived"
          },
          {
            "id": "ADDON-CONS-01",
            "when": "cons_active",
            "applied_for": "Consumables covered instead of fully deducted"
          },
          {
            "id": "SEC-1-5",
            "applied_for": "Excess deducted once from the amount payable"
          }
        ]
      },
      {
        "code": "partial_approval",
        "number": 4,
        "label": "Partial approval",
        "group": "Assessment outcome",
        "pathway": "cashless",
        "claim_type": "cashless",
        "status": "what_if",
        "summary": "One line is withheld because evidence is missing; the rest is approved now and the withheld line can be released later.",
        "assumptions": [
          "The withheld line is held, not rejected, so the customer can still supply evidence (IRDAI fair-documentation principle).",
          "While the line is withheld the customer funds it at the garage."
        ],
        "clauses": [
          {
            "id": "SEC-1-1",
            "applied_for": "Only damage proven to arise from the insured accident is payable"
          },
          {
            "id": "SEC-1-3",
            "applied_for": "Unproven or pre-existing damage is outside cover"
          },
          {
            "id": "COND-CLAIM-01",
            "applied_for": "Missing evidence triggers structured follow-up, not rejection"
          },
          {
            "id": "SEC-1-2",
            "applied_for": "Standard parts depreciation schedule on approved lines"
          },
          {
            "id": "ADDON-ZD-01",
            "when": "zd_active",
            "applied_for": "Part and paint depreciation waived"
          },
          {
            "id": "SEC-1-5",
            "applied_for": "Excess deducted once from the amount payable"
          }
        ]
      },
      {
        "code": "supplementary_estimate",
        "number": 5,
        "label": "Supplementary estimate",
        "group": "Assessment outcome",
        "pathway": "cashless",
        "claim_type": "cashless",
        "status": "what_if",
        "summary": "Hidden damage is found on dismantling; the settlement is recomputed on the cumulative estimate and only the increment is newly payable.",
        "assumptions": [
          "Supplementary lines are notified before repair and assessed at the quoted amount.",
          "The excess is applied once on the cumulative claim, never again on the supplementary."
        ],
        "clauses": [
          {
            "id": "COND-CLAIM-03",
            "applied_for": "Supplementary estimate, re-inspection threshold and cumulative authority check"
          },
          {
            "id": "SEC-1-2",
            "applied_for": "Standard parts depreciation schedule on supplementary parts"
          },
          {
            "id": "ADDON-ZD-01",
            "when": "zd_active",
            "applied_for": "Part depreciation waived on supplementary parts"
          },
          {
            "id": "ADDON-CONS-01",
            "when": "cons_active",
            "applied_for": "Consumables covered instead of fully deducted"
          },
          {
            "id": "SEC-1-5",
            "applied_for": "Excess applied once across original and supplementary"
          }
        ]
      },
      {
        "code": "total_loss",
        "number": 6,
        "label": "Total loss",
        "group": "Loss type",
        "pathway": "total_loss",
        "claim_type": "total_loss",
        "status": "what_if",
        "summary": "Irreparable damage, fire or theft: the insurer pays IDV less excess against surrender of the vehicle and takes the salvage.",
        "assumptions": [
          "Surrender basis: the insurer takes ownership of the wreck, so no salvage value is deducted from the payout.",
          "The customer expected the market value of the vehicle, but an agreed-value policy settles at IDV."
        ],
        "clauses": [
          {
            "id": "SEC-1-6",
            "applied_for": "IDV is the agreed value and the maximum payable on a total loss"
          },
          {
            "id": "SEC-1-7",
            "applied_for": "IDV less excess paid against surrender of the vehicle"
          },
          {
            "id": "SEC-1-5",
            "applied_for": "Excess deducted once from the amount payable"
          }
        ]
      },
      {
        "code": "constructive_total_loss",
        "number": 7,
        "label": "Constructive total loss",
        "group": "Loss type",
        "pathway": "total_loss",
        "claim_type": "total_loss",
        "status": "what_if",
        "summary": "A severe structural estimate is tested against 75% of IDV; if the net repair cost crosses it the claim converts to a total loss with the owner retaining the wreck.",
        "assumptions": [
          "Stress estimate is a single aggregate structural repair line set as a fixed share of IDV (rule parameter).",
          "Retention basis: the owner keeps the wreck, so its assessed salvage value is deducted from the payout."
        ],
        "clauses": [
          {
            "id": "SEC-1-4",
            "applied_for": "Net repair cost tested against 75% of IDV"
          },
          {
            "id": "SEC-1-6",
            "applied_for": "IDV is the agreed value and the maximum payable"
          },
          {
            "id": "SEC-1-7",
            "applied_for": "Salvage retained by the owner is deducted"
          },
          {
            "id": "SEC-1-5",
            "applied_for": "Excess deducted once from the amount payable"
          }
        ]
      },
      {
        "code": "salvage_recovery",
        "number": 8,
        "label": "Salvage recovery",
        "group": "Loss type",
        "pathway": "total_loss",
        "claim_type": "total_loss",
        "status": "what_if",
        "summary": "After a surrender-basis total loss the insurer sells the wreck; compare its net claim cost with letting the owner retain the salvage.",
        "assumptions": [
          "Salvage auction proceeds equal the assessed salvage value; disposal cost is a fixed share of proceeds (rule parameter).",
          "The customer receives the same payout as the total-loss scenario; only the insurer's net cost changes."
        ],
        "clauses": [
          {
            "id": "SEC-1-7",
            "applied_for": "Insurer is entitled to the salvage on surrender; retention deducts its value"
          },
          {
            "id": "SEC-1-6",
            "applied_for": "IDV is the agreed value and the maximum payable"
          },
          {
            "id": "SEC-1-5",
            "applied_for": "Excess deducted once from the amount payable"
          }
        ]
      },
      {
        "code": "zero_dep_addon",
        "number": 9,
        "label": "Zero-depreciation add-on",
        "group": "Policy terms and add-ons",
        "pathway": "cashless",
        "claim_type": "cashless",
        "status": "what_if",
        "summary": "Shows exactly what the Zero Depreciation endorsement is worth on this claim by recomputing with and without it.",
        "assumptions": [
          "All other inputs, including the consumables add-on, are held at their current values.",
          "Claim-count limits in the policy schedule are not modelled."
        ],
        "clauses": [
          {
            "id": "ADDON-ZD-01",
            "applied_for": "Depreciation on replaced parts and paint waived"
          },
          {
            "id": "SEC-1-2",
            "applied_for": "Standard depreciation that applies without the endorsement"
          },
          {
            "id": "SEC-1-5",
            "applied_for": "Excess deducted once from the amount payable"
          }
        ]
      },
      {
        "code": "consumables_addon",
        "number": 10,
        "label": "Consumables add-on",
        "group": "Policy terms and add-ons",
        "pathway": "cashless",
        "claim_type": "cashless",
        "status": "what_if",
        "summary": "Shows what the Consumables endorsement is worth by recomputing with and without it; without it consumables are fully deducted.",
        "assumptions": [
          "All other inputs, including the zero-depreciation add-on, are held at their current values."
        ],
        "clauses": [
          {
            "id": "ADDON-CONS-01",
            "applied_for": "Consumables covered instead of fully deducted"
          },
          {
            "id": "SEC-1-3",
            "applied_for": "Consumables are otherwise excluded as wear and tear items"
          },
          {
            "id": "SEC-1-5",
            "applied_for": "Excess deducted once from the amount payable"
          }
        ]
      },
      {
        "code": "different_deductibles",
        "number": 11,
        "label": "Different deductibles",
        "group": "Policy terms and add-ons",
        "pathway": "cashless",
        "claim_type": "cashless",
        "status": "what_if",
        "summary": "A grid of compulsory excess by vehicle class against voluntary deductible slabs, showing the net payable for each pairing.",
        "assumptions": [
          "Premium discount earned for a higher voluntary deductible is not modelled.",
          "The headline figure uses the compulsory and voluntary excess currently entered."
        ],
        "clauses": [
          {
            "id": "SEC-1-5",
            "applied_for": "Compulsory excess by vehicle class plus any voluntary deductible"
          },
          {
            "id": "SEC-1-2",
            "applied_for": "Standard parts depreciation schedule applied line by line"
          },
          {
            "id": "ADDON-ZD-01",
            "when": "zd_active",
            "applied_for": "Part and paint depreciation waived"
          },
          {
            "id": "ADDON-CONS-01",
            "when": "cons_active",
            "applied_for": "Consumables covered instead of fully deducted"
          }
        ]
      },
      {
        "code": "underinsurance_idv",
        "number": 12,
        "label": "Underinsurance and IDV implications",
        "group": "Policy terms and add-ons",
        "pathway": "cashless",
        "claim_type": "cashless",
        "status": "what_if",
        "summary": "Compares IDV with market value: the IDV cap, the shortfall on a total loss, and what a pro-rata average would do to a partial loss if the policy carried one.",
        "assumptions": [
          "The synthetic wording applies no pro-rata average to partial loss by default; the reduction shown is a what-if for policies or segments whose wording provides for it.",
          "Pro-rata is applied to the loss after depreciation and before the excess."
        ],
        "clauses": [
          {
            "id": "SEC-1-6",
            "applied_for": "IDV cap, agreed-value basis and any pro-rata condition in the schedule"
          },
          {
            "id": "SEC-1-7",
            "applied_for": "Total loss is paid at IDV, not market value"
          },
          {
            "id": "SEC-1-5",
            "applied_for": "Excess deducted once from the amount payable"
          }
        ]
      }
    ]
  },
  "clauses": {
    "SEC-1-1": {
      "clause_id": "SEC-1-1",
      "page": 3,
      "title": "Insured Perils (Own Damage)"
    },
    "SEC-1-2": {
      "clause_id": "SEC-1-2",
      "page": 4,
      "title": "Standard Parts Depreciation Schedule"
    },
    "SEC-1-3": {
      "clause_id": "SEC-1-3",
      "page": 5,
      "title": "General Exclusions (Consequential Loss, Wear & Tear, Invalid Licence, Intoxication)"
    },
    "SEC-1-4": {
      "clause_id": "SEC-1-4",
      "page": 6,
      "title": "Total Loss / Constructive Total Loss Criterion"
    },
    "ADDON-ZD-01": {
      "clause_id": "ADDON-ZD-01",
      "page": 11,
      "title": "Nil Depreciation Waiver"
    },
    "ADDON-CONS-01": {
      "clause_id": "ADDON-CONS-01",
      "page": 12,
      "title": "Engine Oil, Coolant & Nut-Bolt Consumables"
    },
    "SEC-2-1": {
      "clause_id": "SEC-2-1",
      "page": 7,
      "title": "Third-Party Bodily Injury, Fatality & Property Damage"
    },
    "COND-CLAIM-01": {
      "clause_id": "COND-CLAIM-01",
      "page": 9,
      "title": "Notice of Loss & Fair Documentation"
    },
    "SEC-1-5": {
      "clause_id": "SEC-1-5",
      "page": 6,
      "title": "Compulsory & Voluntary Excess"
    },
    "SEC-1-6": {
      "clause_id": "SEC-1-6",
      "page": 6,
      "title": "IDV Limit of Liability & Basis of Settlement"
    },
    "SEC-1-7": {
      "clause_id": "SEC-1-7",
      "page": 7,
      "title": "Salvage & Total Loss Settlement"
    },
    "SEC-1-8": {
      "clause_id": "SEC-1-8",
      "page": 7,
      "title": "Repair, Reinstatement or Replacement Option"
    },
    "COND-CLAIM-02": {
      "clause_id": "COND-CLAIM-02",
      "page": 9,
      "title": "Cashless Network Repair & Reimbursement"
    },
    "COND-CLAIM-03": {
      "clause_id": "COND-CLAIM-03",
      "page": 10,
      "title": "Supplementary Estimates & Re-inspection"
    }
  },
  "demo": {
    "claim_ref": "CLM-DEMO-2026-0001",
    "title": "Front-end collision, private car (synthetic demo claim)",
    "disclaimer": "Illustrative values - synthetic demo claim",
    "incident_at": "2026-11-20T10:00:00+00:00",
    "defaults": {
      "vehicle_age_months": 18,
      "idv_inr": "780000.00",
      "market_value_inr": "910000.00",
      "compulsory_deductible_inr": "1000.00",
      "voluntary_deductible_inr": "0.00",
      "salvage_value_inr": "85000.00",
      "zero_depreciation": true,
      "consumables": true
    },
    "quote_lines": [
      {
        "id": "L1",
        "part_code": "PRT-FRT-BMP-01",
        "description": "Front Bumper Assembly (plastic)",
        "part_category": "rubber_nylon_plastic_tyres_tubes_batteries_airbags",
        "line_type": "part",
        "claimed_inr": "12500.00",
        "assessed_inr": "12500.00",
        "assessment_code": null
      },
      {
        "id": "L1D",
        "part_code": "PRT-FRT-BMP-01",
        "description": "Front Bumper Assembly (duplicate quote line)",
        "part_category": "rubber_nylon_plastic_tyres_tubes_batteries_airbags",
        "line_type": "part",
        "claimed_inr": "12500.00",
        "assessed_inr": "0.00",
        "assessment_code": "duplicate_line"
      },
      {
        "id": "L2",
        "part_code": "PRT-HL-LED-RH",
        "description": "Headlamp Assembly LED RH (glass)",
        "part_category": "glass",
        "line_type": "part",
        "claimed_inr": "18400.00",
        "assessed_inr": "18400.00",
        "assessment_code": null
      },
      {
        "id": "L3",
        "part_code": "PRT-FND-RH-01",
        "description": "Front Fender Panel RH (metal)",
        "part_category": "metal",
        "line_type": "part",
        "claimed_inr": "11000.00",
        "assessed_inr": "7800.00",
        "assessment_code": "rate_variance"
      },
      {
        "id": "L4",
        "part_code": "LABOUR-RNR-01",
        "description": "Bumper + Fender R&R Labour & Painting",
        "part_category": "labour",
        "line_type": "labour",
        "claimed_inr": "7600.00",
        "assessed_inr": "7600.00",
        "assessment_code": null
      },
      {
        "id": "L5",
        "part_code": "PRT-CONS-KIT-01",
        "description": "AC Gas, Coolant & Fasteners Kit",
        "part_category": "consumables_default",
        "line_type": "consumable",
        "claimed_inr": "2400.00",
        "assessed_inr": "2400.00",
        "assessment_code": null
      }
    ],
    "partial_approval": {
      "withheld_line_ids": [
        "L2"
      ],
      "reason_code": "evidence_pending"
    },
    "repair_alternative": {
      "replaces_line_ids": [
        "L1",
        "L3",
        "L4"
      ],
      "lines": [
        {
          "id": "R1",
          "part_code": "BMP-REP-01",
          "description": "Front Bumper Repair - plastic welding (labour)",
          "part_category": "labour",
          "line_type": "labour",
          "amount_inr": "3600.00"
        },
        {
          "id": "R2",
          "part_code": "PNT-BMP-01",
          "description": "Front Bumper Refinish - paint & material",
          "part_category": "paint",
          "line_type": "paint",
          "amount_inr": "2400.00"
        },
        {
          "id": "R3",
          "part_code": "FND-REP-01",
          "description": "Front Fender RH Repair - denting (labour)",
          "part_category": "labour",
          "line_type": "labour",
          "amount_inr": "2800.00"
        },
        {
          "id": "R4",
          "part_code": "PNT-FND-01",
          "description": "Front Fender RH Refinish - paint & material",
          "part_category": "paint",
          "line_type": "paint",
          "amount_inr": "2200.00"
        }
      ]
    },
    "supplementary_lines": [
      {
        "id": "S1",
        "part_code": "PRT-RAD-SUP-01",
        "description": "Radiator Support Panel (metal) - found on dismantling",
        "part_category": "metal",
        "line_type": "part",
        "amount_inr": "6200.00"
      },
      {
        "id": "S2",
        "part_code": "PRT-ACC-01",
        "description": "AC Condenser (metal) - found on dismantling",
        "part_category": "metal",
        "line_type": "part",
        "amount_inr": "5800.00"
      },
      {
        "id": "S3",
        "part_code": "PRT-FSH-01",
        "description": "Radiator Fan Shroud (plastic) - found on dismantling",
        "part_category": "rubber_nylon_plastic_tyres_tubes_batteries_airbags",
        "line_type": "part",
        "amount_inr": "2400.00"
      },
      {
        "id": "S4",
        "part_code": "LABOUR-SUP-01",
        "description": "Dismantling & supplementary labour",
        "part_category": "labour",
        "line_type": "labour",
        "amount_inr": "3400.00"
      }
    ],
    "stress_ctl_line": {
      "part_code": "STRUCT-SHELL-AGG",
      "description": "Structural body-shell & assemblies (aggregate estimate)",
      "part_category": "metal",
      "line_type": "part"
    }
  }
};
  if (typeof module === "object" && module.exports) {
    module.exports = data;
  } else {
    root.SETTLEMENT_WORKBENCH_DATA = data;
  }
})(typeof self !== "undefined" ? self : this);
