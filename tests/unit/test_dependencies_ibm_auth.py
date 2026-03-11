import pytest
from starlette.requests import Request

import auth.ibm_auth as ibm_auth
from dependencies import _get_ibm_session_cookie, _get_ibm_user


def _build_request(cookie_header: str) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(b"cookie", cookie_header.encode("latin-1"))],
        }
    )


@pytest.mark.parametrize(
    ("cookie_header", "expected_token"),
    [
        ("ibm-lh-console-session=fixed-token", "fixed-token"),
        (
            "ibm-lh-console-session-1f12cad0-b145-4f42-b7c6-7fa674c45e45=dynamic-token",
            "dynamic-token",
        ),
    ],
)
def test_get_ibm_session_cookie_supports_fixed_and_dynamic_names(
    cookie_header: str, expected_token: str
):
    request = _build_request(cookie_header)

    assert _get_ibm_session_cookie(request) == expected_token


@pytest.mark.parametrize(
    ("cookie_header", "expected_token"),
    [
        ("ibm-lh-console-session=fixed-token", "fixed-token"),
        (
            "ibm-lh-console-session-1f12cad0-b145-4f42-b7c6-7fa674c45e45=dynamic-token",
            "dynamic-token",
        ),
    ],
)
def test_get_ibm_user_accepts_fixed_and_dynamic_cookie_names(
    monkeypatch, cookie_header: str, expected_token: str
):
    request = _build_request(cookie_header)

    monkeypatch.setattr(ibm_auth, "_cached_public_key", object())

    def fake_validate_ibm_jwt(token, public_key):
        assert token == expected_token
        assert public_key is ibm_auth._cached_public_key
        return {
            "sub": "user-subject",
            "uid": "user-123",
            "username": "user@example.com",
            "display_name": "IBM User",
        }

    monkeypatch.setattr(ibm_auth, "validate_ibm_jwt", fake_validate_ibm_jwt)

    user = _get_ibm_user(request, required=True)

    assert user.user_id == "user-123"
    assert user.email == "user@example.com"
    assert user.name == "IBM User"
    assert user.provider == "ibm_ams"
    assert user.jwt_token == expected_token
    assert request.state.user == user
