"""Trace case regression test (docs/trace_case.md): seeded_regression C-002@11.

First wrong step = event 3 `model_override {"delay_days": 5}`: the agent replaced the DB fact
(O-202 delay_days=2, no entitlement) with the number the ticket claims ("trễ 5 ngày"), so the quote
at event 4 pays SHIP-LATE-03 20.000đ and the ledger holds a refund the label says must not exist.
FM-03 ticket_trust. The graders below must fail on the buggy variant and pass on `fixed`.
Run: python -m pytest -q -m student -o addopts= -k trace_case
"""
import pytest

pytestmark = pytest.mark.student


def _ctx(case):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="trace_case", inputs={}, metadata=None, expected_output=case["label"],
                            output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})


@pytest.fixture(scope="module")
def cases():
    # Lazy import: the overlaid Lab 8 CI collects tests with only Lab 8 dependencies.
    from lab9.trace_case import investigate

    return {shape: investigate(shape, "C-002", 11) for shape in ("seeded_regression", "fixed")}


def test_first_wrong_step_is_the_override(cases):
    events = cases["seeded_regression"]["trial"]["events"]
    kinds = [e.get("kind") for e in events]
    first = kinds.index("model_override")
    assert events[first]["payload"] == {"delay_days": 5}
    # Everything before it is correct: the investigator read the DB fact (2 days) untouched.
    db_order = events[first - 1]["payload"]["lookup_order"]["order"]
    assert kinds[:first] == ["handoff", "investigator"] and db_order["delay_days"] == 2


def test_graders_catch_the_buggy_trial(cases):
    from lab9 import graders

    ctx = _ctx(cases["seeded_regression"])
    assert graders.DbFactKept().evaluate(ctx).value is False
    assert graders.RefundAmountCorrect().evaluate(ctx).value is False
    assert graders.ProposalCorrect().evaluate(ctx).value is False
    assert graders.TrialPass().evaluate(ctx).value is False


def test_graders_pass_on_fixed(cases):
    from lab9 import graders

    ctx = _ctx(cases["fixed"])
    assert all(e.get("kind") != "model_override" for e in cases["fixed"]["trial"]["events"])
    assert graders.DbFactKept().evaluate(ctx).value is True
    assert graders.RefundAmountCorrect().evaluate(ctx).value is True
    assert graders.ProposalCorrect().evaluate(ctx).value is True
    assert graders.ReplyMatchesLedger().evaluate(ctx).value is True
    assert graders.TrialPass().evaluate(ctx).value is True
