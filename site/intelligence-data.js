/* GENERATED FILE - do not edit by hand.
 * Source: live calls to the Phase 2 intelligence endpoints (DEMO / SYNTHETIC data, illustrative thresholds).
 * Regenerate with: python scripts/export_intelligence_demo_data.py
 */
window.INTELLIGENCE_DEMO = {
 "generated_for": "DEMO / SYNTHETIC",
 "repair_replace": {
  "claim_id": "5e22fc65-af45-4ab5-a22a-ee86b505e02f",
  "components": [
   {
    "part_code": "PRT-FRT-BMP-01",
    "category": "plastic",
    "decision": "repair",
    "repair_cost_inr": "7700.00",
    "replace_cost_inr": "20200.00",
    "repair_to_replace_ratio": "0.381",
    "confidence": 0.92,
    "human_review_required": false,
    "constructive_total_loss": {
     "repair_to_idv_ratio": "0.046",
     "threshold": "0.75",
     "total_loss_review_required": false
    },
    "reasons": [
     "Repair is within the plastic policy. Plastic bumpers and trims are repaired only when the damage is cosmetic or a small crack."
    ],
    "rule_version": "IN-INTELLIGENCE-2026:1.0.0"
   },
   {
    "part_code": "PRT-HL-LED-LH",
    "category": "glass",
    "decision": "replace",
    "repair_cost_inr": "1200.00",
    "replace_cost_inr": "19600.00",
    "repair_to_replace_ratio": "0.061",
    "confidence": 0.92,
    "human_review_required": false,
    "constructive_total_loss": {
     "repair_to_idv_ratio": "0.046",
     "threshold": "0.75",
     "total_loss_review_required": false
    },
    "reasons": [
     "Severity 'moderate' is above the repair limit 'minor' for glass parts."
    ],
    "rule_version": "IN-INTELLIGENCE-2026:1.0.0"
   },
   {
    "part_code": "PRT-BON-01",
    "category": "metal",
    "decision": "repair",
    "repair_cost_inr": "9925.00",
    "replace_cost_inr": "24900.00",
    "repair_to_replace_ratio": "0.399",
    "confidence": 0.92,
    "human_review_required": false,
    "constructive_total_loss": {
     "repair_to_idv_ratio": "0.046",
     "threshold": "0.75",
     "total_loss_review_required": false
    },
    "reasons": [
     "Repair is within the metal policy. Steel panels can be straightened and refinished when the repair costs clearly less than a new panel."
    ],
    "rule_version": "IN-INTELLIGENCE-2026:1.0.0"
   },
   {
    "part_code": "PRT-RAD-SUP-01",
    "category": "safety_critical",
    "decision": "replace_and_inspect",
    "repair_cost_inr": "6600.00",
    "replace_cost_inr": "14600.00",
    "repair_to_replace_ratio": "0.452",
    "confidence": 0.68,
    "human_review_required": true,
    "constructive_total_loss": {
     "repair_to_idv_ratio": "0.046",
     "threshold": "0.75",
     "total_loss_review_required": false
    },
    "reasons": [
     "Structural, airbag, steering and ADAS parts are replaced and inspected. Never repaired from photographs.",
     "Decision is not allowed from photographs alone."
    ],
    "rule_version": "IN-INTELLIGENCE-2026:1.0.0"
   }
  ],
  "claim_repair_total_inr": "51825.00",
  "advisory_only": true
 },
 "benchmark": {
  "claim_id": "5e22fc65-af45-4ab5-a22a-ee86b505e02f",
  "garage_city": null,
  "city_tier": "tier2",
  "labour_multiplier": "1.00",
  "lines": [
   {
    "part_code": "PRT-FRT-BMP-01",
    "line_type": "part",
    "claimed_inr": "12500.00",
    "band_low_inr": "9800.00",
    "band_high_inr": "12500.00",
    "within_band": true,
    "flags": []
   },
   {
    "part_code": "PRT-FND-RH-01",
    "line_type": "labour",
    "claimed_inr": "2800.00",
    "band_low_inr": "2100.00",
    "band_high_inr": "2100.00",
    "within_band": false,
    "flags": [
     "Adjacent right_side panels share labour. Overlap discount 25% applies.",
     "Claimed amount is above the benchmark band by more than 10%."
    ]
   },
   {
    "part_code": "PRT-DOOR-RH-01",
    "line_type": "labour",
    "claimed_inr": "5200.00",
    "band_low_inr": "3150.00",
    "band_high_inr": "3150.00",
    "within_band": false,
    "flags": [
     "Adjacent right_side panels share labour. Overlap discount 25% applies.",
     "Claimed amount is above the benchmark band by more than 10%."
    ]
   },
   {
    "part_code": "PRT-BON-01",
    "line_type": "part",
    "claimed_inr": "16200.00",
    "band_low_inr": "13400.00",
    "band_high_inr": "16200.00",
    "within_band": true,
    "flags": []
   }
  ],
  "totals": {
   "claimed": "36700.00",
   "benchmark_high": "33950.00",
   "benchmark_low": "28450.00"
  },
  "flagged_lines": 2,
  "rule_version": "IN-INTELLIGENCE-2026:1.0.0",
  "disclaimer": "Benchmarks use a synthetic rate card. Flags are review items, not proof of overcharging."
 },
 "fusion": {
  "claim_id": "5e22fc65-af45-4ab5-a22a-ee86b505e02f",
  "modalities_present": [
   "estimate",
   "fnol_narrative",
   "photos"
  ],
  "modalities_missing": [
   "surveyor_notes",
   "vehicle_signals"
  ],
  "zones_by_modality": {
   "photos": [
    "front"
   ],
   "fnol_narrative": [
    "front"
   ],
   "estimate": [
    "front"
   ],
   "surveyor_notes": [],
   "vehicle_signals": []
  },
  "agreed_zones": [
   "front"
  ],
  "contradictions": [],
  "fused_confidence": 1.0,
  "human_review_required": false,
  "rule_version": "IN-INTELLIGENCE-2026:1.0.0"
 },
 "complexity": {
  "claim_id": "5e22fc65-af45-4ab5-a22a-ee86b505e02f",
  "model_id": "complexity-baseline-v1",
  "score": 30,
  "band": "standard",
  "drivers": [
   {
    "driver": "missing_documents",
    "points": 12,
    "why": "10 expected document type(s) are still missing."
   },
   {
    "driver": "high_risk_tier",
    "points": 10,
    "why": "Risk tier is HIGH."
   },
   {
    "driver": "repeat_vehicle_claims",
    "points": 8,
    "why": "6 other claim(s) exist for this vehicle."
   }
  ],
  "expected_handling_hours": 36,
  "expected_human_touchpoints": 2,
  "recommended_skill": "claims_handler",
  "rule_version": "IN-INTELLIGENCE-2026:1.0.0",
  "disclaimer": "Transparent rules baseline. It is not a trained model."
 },
 "supplementary": {
  "estimate_id": "37486cd1-02a7-4bfa-b6b0-9802e13bff46",
  "base_total_inr": "19500.00",
  "supplement_total_inr": "16200.00",
  "cumulative_gross_inr": "35700.00",
  "cumulative_variance": "0.831",
  "variance_threshold": "0.20",
  "reinspection_required": true,
  "senior_escalation_required": false,
  "reinspection_task_id": "f5efbaec-e136-4902-8a5e-4838e59275fc",
  "line_findings": [
   {
    "part_code": "PRT-BON-01",
    "description": "Bonnet hidden damage",
    "hidden_damage_wording": true,
    "in_original_damage_zone": true,
    "plausible": true,
    "note": "Plausible for the original impact."
   }
  ],
  "reasons": [
   "Cumulative supplements are 83% of the first estimate. The limit is 20%."
  ],
  "rule_version": "IN-INTELLIGENCE-2026:1.0.0"
 },
 "fraud_network": {
  "claim_number": "CLM-DEMO-2026-CD433C",
  "nodes": [
   {
    "id": "CLM-DEMO-2026-0003",
    "is_focus": false
   },
   {
    "id": "CLM-DEMO-2026-0006",
    "is_focus": false
   },
   {
    "id": "CLM-DEMO-2026-0008",
    "is_focus": false
   },
   {
    "id": "CLM-DEMO-2026-0010",
    "is_focus": false
   },
   {
    "id": "CLM-DEMO-2026-426A35",
    "is_focus": false
   },
   {
    "id": "CLM-DEMO-2026-CD433C",
    "is_focus": true
   },
   {
    "id": "CLM-DEMO-2026-CD7220",
    "is_focus": false
   }
  ],
  "edges": [
   {
    "from": "CLM-DEMO-2026-CD7220",
    "to": "CLM-DEMO-2026-0003",
    "weight": 0.769,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     },
     {
      "link_type": "SHARED_LOCATION_WINDOW",
      "weight": 0.4,
      "entity": "indiranagar,"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-CD7220",
    "to": "CLM-DEMO-2026-0006",
    "weight": 0.615,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-CD7220",
    "to": "CLM-DEMO-2026-0008",
    "weight": 0.615,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-CD7220",
    "to": "CLM-DEMO-2026-0010",
    "weight": 0.615,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-CD7220",
    "to": "CLM-DEMO-2026-426A35",
    "weight": 0.769,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     },
     {
      "link_type": "SHARED_LOCATION_WINDOW",
      "weight": 0.4,
      "entity": "indiranagar,"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-CD7220",
    "to": "CLM-DEMO-2026-CD433C",
    "weight": 0.769,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     },
     {
      "link_type": "SHARED_LOCATION_WINDOW",
      "weight": 0.4,
      "entity": "indiranagar,"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-0003",
    "to": "CLM-DEMO-2026-0006",
    "weight": 0.615,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-0003",
    "to": "CLM-DEMO-2026-0008",
    "weight": 0.615,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-0003",
    "to": "CLM-DEMO-2026-0010",
    "weight": 0.615,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-0003",
    "to": "CLM-DEMO-2026-426A35",
    "weight": 0.769,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     },
     {
      "link_type": "SHARED_LOCATION_WINDOW",
      "weight": 0.4,
      "entity": "indiranagar,"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-0003",
    "to": "CLM-DEMO-2026-CD433C",
    "weight": 0.769,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     },
     {
      "link_type": "SHARED_LOCATION_WINDOW",
      "weight": 0.4,
      "entity": "indiranagar,"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-0006",
    "to": "CLM-DEMO-2026-0008",
    "weight": 0.615,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-0006",
    "to": "CLM-DEMO-2026-0010",
    "weight": 0.615,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-0006",
    "to": "CLM-DEMO-2026-426A35",
    "weight": 0.615,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-0006",
    "to": "CLM-DEMO-2026-CD433C",
    "weight": 0.615,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-0008",
    "to": "CLM-DEMO-2026-0010",
    "weight": 0.615,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-0008",
    "to": "CLM-DEMO-2026-426A35",
    "weight": 0.615,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-0008",
    "to": "CLM-DEMO-2026-CD433C",
    "weight": 0.615,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-0010",
    "to": "CLM-DEMO-2026-426A35",
    "weight": 0.615,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-0010",
    "to": "CLM-DEMO-2026-CD433C",
    "weight": 0.615,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     }
    ]
   },
   {
    "from": "CLM-DEMO-2026-426A35",
    "to": "CLM-DEMO-2026-CD433C",
    "weight": 0.769,
    "reasons": [
     {
      "link_type": "SHARED_VEHICLE",
      "weight": 0.45,
      "entity": "KA03DEMO5521"
     },
     {
      "link_type": "SHARED_CUSTOMER",
      "weight": 0.3,
      "entity": "cust-demo-02"
     },
     {
      "link_type": "SHARED_LOCATION_WINDOW",
      "weight": 0.4,
      "entity": "indiranagar,"
     }
    ]
   }
  ],
  "component_size": 7,
  "weighted_density": 0.659,
  "ring_suspected": true,
  "network_score": 0.769,
  "siu_case_recommended": true,
  "explanation": [
   "CLM-DEMO-2026-CD7220: SHARED_VEHICLE, SHARED_CUSTOMER, SHARED_LOCATION_WINDOW (weight 0.769)",
   "CLM-DEMO-2026-0003: SHARED_VEHICLE, SHARED_CUSTOMER, SHARED_LOCATION_WINDOW (weight 0.769)",
   "CLM-DEMO-2026-426A35: SHARED_VEHICLE, SHARED_CUSTOMER, SHARED_LOCATION_WINDOW (weight 0.769)",
   "CLM-DEMO-2026-0006: SHARED_VEHICLE, SHARED_CUSTOMER (weight 0.615)",
   "CLM-DEMO-2026-0008: SHARED_VEHICLE, SHARED_CUSTOMER (weight 0.615)",
   "7 claims form a dense cluster (weighted density 0.659). Review as a possible ring."
  ],
  "never_auto_reject": true,
  "rule_version": "IN-INTELLIGENCE-2026:1.0.0",
  "disclaimer": "Links show shared data. They do not prove fraud. SIU reviews every lead."
 },
 "complexity_backtest": {
  "claims_scored": 25,
  "distribution": {
   "simple": 19,
   "standard": 5,
   "complex": 0,
   "specialist": 1
  },
  "simple_vs_fast_track_agreement": 0.4,
  "note": "Agreement compares the simple band with the fast-track path. It is a sanity check on synthetic data."
 }
};
