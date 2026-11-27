"""MotorClaim AI evaluation framework and AI release gate.

This package measures whether the 11 bounded claim agents are *reliable, safe and measurable*:

* ``datasets/``   curated golden cases (JSON) covering the 17 scenario categories in ``taxonomy.py``
* ``synthetic.py`` seeded generators for boundary / robustness cases
* ``evaluators/`` per-agent metric computation (FNOL ... QA)
* ``safety/``     the hard release-gate checks (tool permissions, grounding, money, injection, PII, escalation)
* ``gate.py``     orchestrates everything against ``thresholds.json`` and ``baseline.json``

Run the gate locally with ``python -m evals.gate``.
"""

EVAL_FRAMEWORK_VERSION = "1.0.0"
