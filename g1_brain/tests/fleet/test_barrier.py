from g1_brain.fleet.coordinator.barrier import RendezvousBarrier


def test_releases_when_all_arrived():
    b = RendezvousBarrier({"g1_a", "g1_b"})
    assert not b.is_released()
    b.mark_arrived("g1_a")
    assert not b.is_released()
    b.mark_arrived("g1_b")
    assert b.is_released()


def test_arrived_by_position_within_radius():
    b = RendezvousBarrier({"g1_a", "g1_b"}, point=(0.0, 0.0), radius=0.6)
    b.update_position("g1_a", (0.4, 0.0))   # within 0.6
    b.update_position("g1_b", (2.0, 0.0))   # too far
    assert not b.is_released()
    b.update_position("g1_b", (-0.5, 0.0))  # now within
    assert b.is_released()
