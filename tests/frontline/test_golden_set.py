import pytest
from src.eval.golden_set import (
    evaluate_extraction,
    compute_inter_annotator_agreement,
    drift_check,
    EvalResult,
    SlotMetrics
)

def get_sample_golden_set():
    return [
        {
            "turn_id": "1",
            "text": "My 2019 Toyota Camry has a broken bumper.",
            "expected_slots": {"YEAR": "2019", "MAKE": "TOYOTA", "MODEL": "CAMRY"},
            "tags": ["easy"]
        },
        {
            "turn_id": "2",
            "text": "I drive a Honda but it's not a Civic, it's an Accord.",
            "expected_slots": {"MAKE": "HONDA", "MODEL": "ACCORD"},
            "tags": ["negation"]
        }
    ]

def test_perfect_extraction_scores_1():
    gs = get_sample_golden_set()
    def perfect_extractor(text):
        if "Toyota" in text:
            return {"YEAR": "2019", "MAKE": "TOYOTA", "MODEL": "CAMRY"}
        else:
            return {"MAKE": "HONDA", "MODEL": "ACCORD"}
            
    res = evaluate_extraction(gs, perfect_extractor)
    assert res.overall_slot_f1 == 1.0
    assert res.overall_slot_precision == 1.0
    assert res.overall_slot_recall == 1.0

def test_empty_extraction_scores_0():
    gs = get_sample_golden_set()
    def empty_extractor(text):
        return {}
        
    res = evaluate_extraction(gs, empty_extractor)
    assert res.overall_slot_recall == 0.0

def test_wrong_extraction_precision_0():
    gs = get_sample_golden_set()
    def wrong_extractor(text):
        return {"MAKE": "FORD", "MODEL": "FOCUS", "YEAR": "2000"}
        
    res = evaluate_extraction(gs, wrong_extractor)
    assert res.overall_slot_precision == 0.0

def test_partial_extraction():
    gs = get_sample_golden_set()
    def partial_extractor(text):
        if "Toyota" in text:
            return {"YEAR": "2019", "MAKE": "TOYOTA"} # missed MODEL
        else:
            return {"MAKE": "HONDA"} # missed MODEL
            
    res = evaluate_extraction(gs, partial_extractor)
    assert 0.0 < res.overall_slot_f1 < 1.0

def test_per_tag_metrics():
    gs = get_sample_golden_set()
    def perfect_extractor(text):
        if "Toyota" in text:
            return {"YEAR": "2019", "MAKE": "TOYOTA", "MODEL": "CAMRY"}
        else:
            return {"MAKE": "HONDA", "MODEL": "ACCORD"}
            
    res = evaluate_extraction(gs, perfect_extractor)
    assert "negation" in res.per_tag_metrics
    assert res.per_tag_metrics["negation"]["MAKE"].true_positives == 1

def test_inter_annotator_agreement_perfect():
    ann1 = [{"expected_slots": {"A": "1"}}, {"expected_slots": {"A": "2"}}]
    ann2 = [{"expected_slots": {"A": "1"}}, {"expected_slots": {"A": "2"}}]
    res = compute_inter_annotator_agreement(ann1, ann2)
    assert res["overall_kappa"] == 1.0

def test_inter_annotator_agreement_random():
    ann1 = [{"expected_slots": {"A": "1"}}, {"expected_slots": {"A": "2"}}]
    ann2 = [{"expected_slots": {"A": "3"}}, {"expected_slots": {"A": "4"}}]
    res = compute_inter_annotator_agreement(ann1, ann2)
    assert res["overall_kappa"] < 1.0

def test_drift_check_detects_regression():
    baseline = EvalResult(
        slot_metrics={"A": SlotMetrics(slot_name="A", true_positives=10, false_positives=0, false_negatives=0, true_negatives=0)}
    )
    current = EvalResult(
        slot_metrics={"A": SlotMetrics(slot_name="A", true_positives=1, false_positives=9, false_negatives=9, true_negatives=0)}
    )
    res = drift_check(current, baseline)
    assert res["drifted"] is True
    assert len(res["regressions"]) == 1

def test_drift_check_no_regression():
    baseline = EvalResult(
        slot_metrics={"A": SlotMetrics(slot_name="A", true_positives=10, false_positives=0, false_negatives=0, true_negatives=0)}
    )
    current = EvalResult(
        slot_metrics={"A": SlotMetrics(slot_name="A", true_positives=10, false_positives=0, false_negatives=0, true_negatives=0)}
    )
    res = drift_check(current, baseline)
    assert res["drifted"] is False

def test_extractor_exception_counted_as_error():
    gs = get_sample_golden_set()
    def failing_extractor(text):
        raise ValueError("Oops")
        
    res = evaluate_extraction(gs, failing_extractor)
    assert len(res.errors) == 2
