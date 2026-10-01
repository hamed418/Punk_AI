import pytest
from pydantic import ValidationError
from app.core.security import validate_password_complexity
from app.modules.auth.schemas import (
    SignupCompleteRequest,
    ResetPasswordRequest,
    UserRegisterRequest,
)
from app.modules.user.schemas import ChangePasswordRequest, UserUpdateRequest


def test_validate_password_complexity_success():
    valid_passwords = [
        "StrongP@ssw0rd",
        "Abcd1234#$!",
        "Secure.Pass.999",
        "P@ssw0rd1234567890123456789012345678901234567890", # within 72 bytes
    ]
    for pw in valid_passwords:
        assert validate_password_complexity(pw) == pw


def test_validate_password_complexity_failures():
    # Empty
    with pytest.raises(ValueError, match="Password is required"):
        validate_password_complexity("")

    # Too short (< 8 chars)
    with pytest.raises(ValueError, match="at least 8 characters long"):
        validate_password_complexity("Aa1!xyz")

    # Exceeds 72 bytes
    with pytest.raises(ValueError, match="cannot exceed 72 bytes"):
        validate_password_complexity("A" * 70 + "a1!xyz" * 5)

    # Missing uppercase
    with pytest.raises(ValueError, match="uppercase letter"):
        validate_password_complexity("lowercase123!")

    # Missing lowercase
    with pytest.raises(ValueError, match="lowercase letter"):
        validate_password_complexity("UPPERCASE123!")

    # Missing digit
    with pytest.raises(ValueError, match="number"):
        validate_password_complexity("NoDigitsHere!")

    # Missing special character
    with pytest.raises(ValueError, match="special character"):
        validate_password_complexity("NoSpecialChars123")


def test_schema_validators():
    # ResetPasswordRequest schema rejects weak password
    with pytest.raises(ValidationError):
        ResetPasswordRequest(
            email="test@example.com",
            code="12345",
            new_password="weakpassword",
        )

    # ResetPasswordRequest schema accepts strong password
    valid_reset = ResetPasswordRequest(
        email="test@example.com",
        code="12345",
        new_password="StrongPassword123!",
    )
    assert valid_reset.new_password == "StrongPassword123!"

    # ChangePasswordRequest schema rejects weak password
    with pytest.raises(ValidationError):
        ChangePasswordRequest(
            current_password="old",
            new_password="weak",
        )

    # ChangePasswordRequest schema accepts strong password
    valid_change = ChangePasswordRequest(
        current_password="OldPassword123!",
        new_password="NewSecureP@ss123",
    )
    assert valid_change.new_password == "NewSecureP@ss123"

    # ChangePasswordRequest schema rejects when new password equals current password
    with pytest.raises(ValidationError, match="New password cannot be the same as your current password"):
        ChangePasswordRequest(
            current_password="SamePassword123!",
            new_password="SamePassword123!",
        )
