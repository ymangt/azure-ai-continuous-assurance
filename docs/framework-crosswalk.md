# Framework crosswalk

This crosswalk is informative. Similar concepts do not make controls equivalent, and a passing AICA objective does not establish conformity with NIST CSF, the Microsoft Cloud Security Benchmark, NIST AI RMF, OWASP, or any certification scheme.

The machine-readable mapping is in `assurance/controls/informative-crosswalk.json`. It maps all 25 controls to the smallest defensible set of framework categories and records a rationale for every relationship.

## Framework roles

- NIST CSF 2.0 structures governance, posture, ownership, communication, and improvement outcomes.
- NIST SP 800-53 Rev. 5 supplies the 20 selected source controls; SP 800-53A supplies examine, interview, and test concepts.
- Microsoft Cloud Security Benchmark supplies Azure-oriented implementation guidance.
- NIST AI RMF and its Generative AI Profile inform governance, mapping, measurement, monitoring, and risk treatment for the five local AI controls.
- OWASP Agentic Top 10 supplies an adversarial-test taxonomy. It is not treated as a compliance framework.

Primary references: [NIST CSF 2.0](https://www.nist.gov/cyberframework), [NIST SP 800-53](https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final), [NIST SP 800-53A](https://csrc.nist.gov/pubs/sp/800/53/a/r5/final), [Microsoft Cloud Security Benchmark](https://learn.microsoft.com/security/benchmark/azure/overview), [NIST AI 600-1](https://doi.org/10.6028/NIST.AI.600-1), and [OWASP Agentic Top 10](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/).

The local AI control prefix (`AI-*`) deliberately prevents readers from mistaking project controls for NIST controls.
