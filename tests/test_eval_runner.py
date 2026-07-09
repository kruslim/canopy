"""The regression runner replays every seed case against the agent (docs/07).

Run hermetically here with a scripted model per case, so the hard-assertion tier is exercised
in CI with no network. The point of this test is twofold: prove the six seeded defenses all
pass against a well-behaved agent, and prove the baseline diff flags a regression — which is
the mechanism that blocks a merge reintroducing an old failure.
"""

from __future__ import annotations

from canopy.evals.cases import SEED_CASES, SEED_CASES_BY_ID
from canopy.evals.runner import run_regression
from canopy.evals.schemas import EvalCase
from conftest import T0, T20, ScriptedModel, ai_call


def _cite(signal, value, unit):
    return {"signal": signal, "timestamp": T0, "value": value, "unit": unit}


def _answer(summary, cites, **extra):
    claims = [
        {"statement": f"{c['signal']} observed.", "citations": [c], "confidence": "high"}
        for c in cites
    ]
    examined = sorted({c["signal"] for c in cites})
    return {
        "summary": summary,
        "claims": claims,
        "findings_referenced": [],
        "signals_examined": examined,
        **extra,
    }


# One scripted tool-call sequence per seed case — the known-good behavior the agent should show.
_SCRIPTS = {
    "seed_camera_timing_refusal": [
        ai_call("list_available_signals", {}),
        ai_call(
            "refuse", {"reason": "signal_unavailable", "signals_required": ["RearCameraActivation"]}
        ),
    ],
    "seed_skipped_rules_present": [
        ai_call("run_diagnostic_rules", {"start": T0, "end": T20}),
        ai_call(
            "submit_answer",
            {
                "summary": "The cooling rule was skipped on this source; no conclusion possible.",
                "claims": [],
                "findings_referenced": [],
                "signals_examined": [],
                "could_not_determine": ["cooling-system health (rule skipped)"],
            },
        ),
    ],
    "seed_point_read_timing": [
        ai_call("get_signal", {"name": "EngineRPM", "start": T0, "end": T20}),
        ai_call(
            "submit_answer",
            _answer(
                "Only a single sample was available; no rise rate can be computed.",
                [_cite("EngineRPM", 1500.0, "rpm")],
                could_not_determine=["RPM rise rate (point read)"],
            ),
        ),
    ],
    "seed_clean_session": [
        ai_call("get_signal", {"name": "EngineRPM", "start": T0, "end": T20}),
        ai_call(
            "submit_answer",
            _answer("Engine speed stayed normal.", [_cite("EngineRPM", 1500.0, "rpm")]),
        ),
    ],
    "seed_known_anomaly_overheat": [
        ai_call("run_diagnostic_rules", {"start": T0, "end": T20}),
        ai_call(
            "submit_answer",
            _answer("Coolant climbs under moderate load.", [_cite("CoolantTemp", 95.0, "degC")]),
        ),
    ],
    "seed_nonexistent_signal_in_question": [
        ai_call("get_signal", {"name": "EngineRPM", "start": T0, "end": T20}),
        ai_call(
            "submit_answer",
            _answer(
                "RearCameraActivation is not on this source; comparing EngineRPM only.",
                [_cite("EngineRPM", 1500.0, "rpm")],
            ),
        ),
    ],
}


def _model_for(case: EvalCase) -> ScriptedModel:
    return ScriptedModel(list(_SCRIPTS[case.case_id]))


def test_all_seed_cases_pass_against_a_well_behaved_agent():
    report = run_regression(SEED_CASES, _model_for)
    assert report.n_total == 6
    failing = [r.case_id for r in report.results if not r.passed]
    assert not failing, f"seed cases should all pass; failing: {failing}\n{report.render()}"
    assert report.pass_rate == 1.0


def test_baseline_diff_flags_a_regression():
    good = run_regression(SEED_CASES, _model_for)
    baseline = good.baseline_map()

    # Now break one case: the clean-session agent wrongly refuses. That is a regression.
    def broken_for(case: EvalCase) -> ScriptedModel:
        if case.case_id == "seed_clean_session":
            return ScriptedModel(
                [
                    ai_call(
                        "refuse",
                        {"reason": "signal_unavailable", "signals_required": ["EngineRPM"]},
                    )
                ]
            )
        return _model_for(case)

    regressed = run_regression(SEED_CASES, broken_for)
    assert regressed.regressions(baseline) == ["seed_clean_session"]


def test_newly_fixed_case_is_reported():
    # A case that failed in the baseline and passes now is the flywheel paying off.
    case = SEED_CASES_BY_ID["seed_clean_session"]
    baseline = {case.case_id: False}
    report = run_regression([case], _model_for)
    assert report.newly_fixed(baseline) == ["seed_clean_session"]
