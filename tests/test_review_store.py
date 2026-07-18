from aica.review_store import overlay_review_events


def test_review_overlay_projects_latest_decision_and_exception_without_mutating_package() -> None:
    package = {
        "run": {"id": "run-1", "manifest_digest": "a" * 64},
        "assessments": [
            {
                "objective_id": "AC-3.1",
                "conclusion": "PARTIALLY_EFFECTIVE",
                "review_state": "SUGGESTED",
                "reviewer": None,
            }
        ],
        "findings": [{"id": "FND-001", "status": "READY_FOR_RETEST"}],
        "retests": [{"id": "RET-001", "finding_id": "FND-001", "decision": "CLOSE"}],
        "decisions": [],
        "exceptions": [],
    }
    events = [
        {
            "_event_type": "REVIEW_DECISION",
            "id": "decision-1",
            "subject_type": "CONTROL",
            "subject_id": "AC-3.1",
            "decision": "EFFECTIVE",
            "rationale": "Fresh evidence supports the reviewer conclusion.",
            "reviewer": "reviewer-1",
            "version": 2,
            "artifact_hash": "a" * 64,
        },
        {
            "_event_type": "REVIEW_DECISION",
            "id": "decision-2",
            "subject_type": "FINDING",
            "subject_id": "FND-001",
            "decision": "CLOSED",
            "reviewer": "reviewer-1",
            "version": 2,
            "artifact_hash": "a" * 64,
        },
        {
            "_event_type": "EXCEPTION",
            "id": "exception-1",
            "finding_id": "FND-001",
            "artifact_hash": "a" * 64,
        },
    ]

    projected = overlay_review_events(package, events)

    assert package["assessments"][0]["review_state"] == "SUGGESTED"
    assert projected["assessments"][0]["review_state"] == "ACCEPTED"
    assert projected["assessments"][0]["reviewer"] == "reviewer-1"
    assert projected["assessments"][0]["conclusion"] == "PARTIALLY_EFFECTIVE"
    assert projected["assessments"][0]["reviewer_conclusion"] == "EFFECTIVE"
    assert projected["assessments"][0]["reviewer_rationale"].startswith("Fresh evidence")
    assert projected["findings"][0]["status"] == "CLOSED"
    assert projected["retests"][0]["review_state"] == "ACCEPTED"
    assert projected["retests"][0]["review_decision_id"] == "decision-2"
    assert projected["exceptions"][0]["id"] == "exception-1"
    assert projected["assessments"][0]["review_version"] == 2


def test_review_overlay_does_not_rewrite_a_different_signed_run() -> None:
    package = {
        "run": {"id": "baseline", "manifest_digest": "b" * 64},
        "assessments": [{"objective_id": "SC-7.1", "review_state": "SUGGESTED", "reviewer": None}],
        "findings": [{"id": "FND-001", "status": "OPEN"}],
    }
    later_decision = {
        "_event_type": "REVIEW_DECISION",
        "id": "decision-retest",
        "subject_type": "FINDING",
        "subject_id": "FND-001",
        "decision": "CLOSED",
        "artifact_hash": "c" * 64,
        "version": 2,
    }
    projected = overlay_review_events(package, [later_decision])
    assert projected["findings"][0]["status"] == "OPEN"
    assert projected["decisions"] == []
    assert projected["findings"][0]["review_version"] == 2


def test_review_overlay_projects_ready_for_retest_without_closing() -> None:
    package = {
        "run": {"id": "run-1", "manifest_digest": "a" * 64},
        "assessments": [],
        "findings": [{"id": "FND-001", "status": "OPEN"}],
    }
    event = {
        "_event_type": "REVIEW_DECISION",
        "id": "decision-ready",
        "subject_type": "FINDING",
        "subject_id": "FND-001",
        "decision": "READY_FOR_RETEST",
        "artifact_hash": "a" * 64,
        "version": 2,
    }
    projected = overlay_review_events(package, [event])
    assert projected["findings"][0]["status"] == "READY_FOR_RETEST"


def test_review_overlay_appends_bound_remediation_and_carries_it_into_retest_trace() -> None:
    baseline = {
        "run": {"id": "run-1", "manifest_digest": "a" * 64},
        "findings": [{"id": "FND-001", "run_id": "run-1", "status": "OPEN"}],
        "remediations": [],
    }
    event = {
        "_event_type": "REMEDIATION",
        "id": "remediation-1",
        "finding_id": "FND-001",
        "owner": "Cloud Owner",
        "action": "Remove the broad ingress rule through reviewed infrastructure code.",
        "target_date": "2026-08-01T00:00:00Z",
        "commit_or_pr": "PR-101",
        "evidence_refs": ["EVD-001"],
        "status": "READY_FOR_RETEST",
        "recorded_by": "reviewer-1",
        "recorded_at": "2026-07-17T12:00:00Z",
        "artifact_run_id": "run-1",
        "artifact_hash": "a" * 64,
        "expected_version": 1,
        "version": 2,
    }

    projected = overlay_review_events(baseline, [event])

    assert baseline["findings"][0]["status"] == "OPEN"
    assert baseline["remediations"] == []
    assert projected["findings"][0]["status"] == "READY_FOR_RETEST"
    assert projected["findings"][0]["review_version"] == 2
    assert projected["remediations"][0]["evidence_refs"] == ["EVD-001"]

    retest = {
        "run": {
            "id": "run-2",
            "prior_run_id": "run-1",
            "manifest_digest": "b" * 64,
        },
        "findings": [{"id": "FND-001", "run_id": "run-1", "status": "CLOSED"}],
        "remediations": [],
        "retests": [
            {
                "finding_id": "FND-001",
                "before_run_id": "run-1",
                "after_run_id": "run-2",
                "decision": "CLOSE",
                "review_state": "ACCEPTED",
            }
        ],
    }
    projected_retest = overlay_review_events(retest, [event])
    assert projected_retest["findings"][0]["status"] == "CLOSED"
    assert projected_retest["remediations"][0]["artifact_run_id"] == "run-1"
