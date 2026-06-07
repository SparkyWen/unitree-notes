"""Additive DORMANT state for fleet sleep — must not disturb existing transitions."""
import pytest

from g1_brain.safety.state_machine import (
    RobotFsm, RobotFsmState, IllegalTransitionError,
)


def test_dormant_state_exists():
    assert RobotFsmState.DORMANT.value == "DORMANT"


def test_standing_to_dormant_and_back():
    fsm = RobotFsm(initial=RobotFsmState.STANDING)
    assert fsm.transition(RobotFsmState.DORMANT, "sleep") == RobotFsmState.DORMANT
    assert fsm.transition(RobotFsmState.STANDING, "wake") == RobotFsmState.STANDING


def test_dormant_can_escape_to_estop():
    fsm = RobotFsm(initial=RobotFsmState.STANDING)
    fsm.transition(RobotFsmState.DORMANT, "sleep")
    assert fsm.transition(RobotFsmState.EMERGENCY_STOP, "trip") == RobotFsmState.EMERGENCY_STOP


def test_dormant_can_escape_to_fault():
    fsm = RobotFsm(initial=RobotFsmState.STANDING)
    fsm.transition(RobotFsmState.DORMANT, "sleep")
    assert fsm.transition(RobotFsmState.FAULT, "fault") == RobotFsmState.FAULT


def test_dormant_cannot_go_directly_to_acting():
    fsm = RobotFsm(initial=RobotFsmState.STANDING)
    fsm.transition(RobotFsmState.DORMANT, "sleep")
    with pytest.raises(IllegalTransitionError):
        fsm.transition(RobotFsmState.ACTING, "x")  # must wake to STANDING first


def test_preexisting_illegal_transition_still_illegal():
    fsm = RobotFsm(initial=RobotFsmState.BOOT)
    with pytest.raises(IllegalTransitionError):
        fsm.transition(RobotFsmState.ENGAGED, "x")  # BOOT->ENGAGED was/stays illegal
