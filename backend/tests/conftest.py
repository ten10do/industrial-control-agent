import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    """Reset the global rate limiter before every test to avoid state pollution."""
    from backend.traffic_control import reset_rate_limiter
    reset_rate_limiter()
