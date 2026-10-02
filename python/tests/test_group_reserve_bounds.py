import pytest
from pydantic import ValidationError

from power_openapi_models.operations.models import GroupReserve

BOUNDED = {
    "id": 7,
    "name": "R_UP",
    "available": True,
    "requirement": 2129.0,
    "max_requirement": 2129.0,
    "participation_bounds": [[4, 1.0, 1.0], [5, 0.0, 0.2]],
    "reserve_direction": "UP",
}


def test_group_reserve_reads_a_cap_and_bounds():
    group = GroupReserve.model_validate(BOUNDED)
    assert group.max_requirement == 2129.0
    assert group.participation_bounds == [[4.0, 1.0, 1.0], [5.0, 0.0, 0.2]]
    dumped = group.model_dump(mode="json", exclude_none=True)
    assert dumped["participation_bounds"] == [[4.0, 1.0, 1.0], [5.0, 0.0, 0.2]]


def test_group_reserve_without_bounds_writes_neither():
    plain = {
        k: v for k, v in BOUNDED.items() if k not in ("max_requirement", "participation_bounds")
    }
    dumped = GroupReserve.model_validate(plain).model_dump(exclude_none=True)
    assert "max_requirement" not in dumped
    assert "participation_bounds" not in dumped


def test_a_negative_cap_is_rejected():
    with pytest.raises(ValidationError):
        GroupReserve.model_validate(dict(BOUNDED, max_requirement=-1.0))
