from src.frontline.sentiment_review import (
    SENTIMENT_REVISIT_N,
    disagreement_count,
    log_sentiment_disagreement,
    revisit_ready,
)


def test_sentiment_disagreement_log(reset_ops_db):
    assert SENTIMENT_REVISIT_N == 300
    assert revisit_ready() is False
    log_sentiment_disagreement(
        interaction_id="int_x",
        human_decision="no_handoff",
        system_sentiment_score=0.9,
        system_handoff_decision=True,
        reviewer_comment="customer was calm",
    )
    assert disagreement_count() == 1
    assert revisit_ready() is False
