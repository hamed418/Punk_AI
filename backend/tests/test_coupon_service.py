import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import HTTPException
import app.db.model_registry

from app.modules.coupon.models import Coupons, CouponRedemptions
from app.modules.coupon.schemas import (
    CreateCoupon,
    UpdateCoupon,
    CouponValidateRequest,
    RedeemRequest,
    DiscountType,
    RedemptionStatus,
    CouponStatus,
)
from app.modules.coupon.service import CouponService
from app.modules.user.models import User
from app.shared.enums import UserRole


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.admin_create_coupon = AsyncMock()
    repo.admin_get_coupon_by_id = AsyncMock()
    repo.admin_get_by_coupon_code = AsyncMock()
    repo.admin_update_coupon = AsyncMock()
    repo.admin_delete_coupon = AsyncMock()
    repo.admin_get_all_coupons = AsyncMock()
    repo.admin_get_redemptions = AsyncMock()
    repo.user_make_redemption = AsyncMock()
    repo.get_user_redemptions = AsyncMock()
    repo.get_user_coupon_redemptions_count = AsyncMock()
    repo.get_user_total_redemptions_count = AsyncMock()
    return repo


@pytest.fixture
def coupon_service(mock_repo):
    return CouponService(coupon_repository=mock_repo)


@pytest.fixture
def admin_user():
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "admin@example.com"
    user.role = UserRole.admin
    return user


@pytest.fixture
def normal_user():
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "user@example.com"
    user.role = UserRole.user
    return user


def test_calculate_discount_percentage(coupon_service):
    coupon = Coupons(
        code="SAVE20",
        discount_type=DiscountType.PERCENTAGE,
        discount_value=Decimal("20.0"),
        max_discount_amount=Decimal("50.0"),
    )
    # 20% of 100 is 20
    discount, final = coupon_service.calculate_discount(coupon, 100.0)
    assert discount == 20.0
    assert final == 80.0

    # 20% of 500 is 100, but capped at max_discount_amount 50
    discount, final = coupon_service.calculate_discount(coupon, 500.0)
    assert discount == 50.0
    assert final == 450.0


def test_calculate_discount_fixed_amount(coupon_service):
    coupon = Coupons(
        code="SAVE15",
        discount_type=DiscountType.FIXED_AMOUNT,
        discount_value=Decimal("15.0"),
    )
    # Order 50 - 15 = 35
    discount, final = coupon_service.calculate_discount(coupon, 50.0)
    assert discount == 15.0
    assert final == 35.0

    # Order 10 - 15 = capped at 10 discount, 0 final
    discount, final = coupon_service.calculate_discount(coupon, 10.0)
    assert discount == 10.0
    assert final == 0.0


def test_calculate_discount_full_free(coupon_service):
    coupon = Coupons(
        code="FREEBIE",
        discount_type=DiscountType.FULL_FREE,
    )
    discount, final = coupon_service.calculate_discount(coupon, 150.0)
    assert discount == 150.0
    assert final == 0.0


@pytest.mark.asyncio
async def test_admin_create_coupon_non_admin_forbidden(coupon_service, normal_user):
    db = AsyncMock()
    payload = CreateCoupon(
        code="SUMMER20",
        discount_type=DiscountType.PERCENTAGE,
        discount_value=20,
    )
    with pytest.raises(HTTPException) as exc:
        await coupon_service.create_coupon(db, normal_user, payload)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_create_coupon_success(coupon_service, admin_user, mock_repo):
    db = AsyncMock()
    mock_repo.admin_get_by_coupon_code.return_value = None

    def create_side_effect(db_sess, coupon_obj):
        coupon_obj.id = uuid.uuid4()
        coupon_obj.created_at = datetime.now(timezone.utc)
        return coupon_obj

    mock_repo.admin_create_coupon.side_effect = create_side_effect

    payload = CreateCoupon(
        code="summer20",
        discount_type=DiscountType.PERCENTAGE,
        discount_value=20,
        max_discount_amount=50,
        max_uses=100,
        usage_limit_per_user=1,
    )
    res = await coupon_service.create_coupon(db, admin_user, payload)
    assert res.code == "SUMMER20"
    assert res.discount_value == 20.0
    assert res.max_discount_amount == 50.0
    assert res.max_uses == 100


@pytest.mark.asyncio
async def test_admin_create_coupon_duplicate_code(coupon_service, admin_user, mock_repo):
    db = AsyncMock()
    mock_repo.admin_get_by_coupon_code.return_value = Coupons(code="EXISTING")

    payload = CreateCoupon(
        code="EXISTING",
        discount_type=DiscountType.FIXED_AMOUNT,
        discount_value=10,
    )
    with pytest.raises(HTTPException) as exc:
        await coupon_service.create_coupon(db, admin_user, payload)
    assert exc.value.status_code == 400
    assert "already exists" in exc.value.detail


@pytest.mark.asyncio
async def test_validate_coupon_expired(coupon_service, normal_user, mock_repo):
    db = AsyncMock()
    expired_coupon = Coupons(
        id=uuid.uuid4(),
        code="EXPIRED10",
        discount_type=DiscountType.PERCENTAGE,
        discount_value=Decimal("10.0"),
        is_active=True,
        valid_from=datetime.now(timezone.utc) - timedelta(days=10),
        valid_till=datetime.now(timezone.utc) - timedelta(days=1),
        current_uses=0,
    )
    mock_repo.admin_get_by_coupon_code.return_value = expired_coupon

    req = CouponValidateRequest(code="EXPIRED10", original_amount=100.0)
    res = await coupon_service.validate_coupon(db, normal_user, req)
    assert res.is_valid is False
    assert "expired" in res.message


@pytest.mark.asyncio
async def test_redeem_coupon_success(coupon_service, normal_user, mock_repo):
    db = AsyncMock()
    coupon = Coupons(
        id=uuid.uuid4(),
        code="SAVE30",
        discount_type=DiscountType.PERCENTAGE,
        discount_value=Decimal("30.0"),
        currency="USD",
        is_active=True,
        valid_from=datetime.now(timezone.utc) - timedelta(days=1),
        valid_till=datetime.now(timezone.utc) + timedelta(days=5),
        max_uses=10,
        current_uses=0,
        usage_limit_per_user=1,
        new_users_only=False,
    )
    mock_repo.admin_get_by_coupon_code.return_value = coupon
    mock_repo.get_user_coupon_redemptions_count.return_value = 0

    def mock_make_redemption(db_sess, redemption):
        redemption.id = uuid.uuid4()
        redemption.redeemed_at = datetime.now(timezone.utc)
        return redemption

    mock_repo.user_make_redemption.side_effect = mock_make_redemption

    req = RedeemRequest(code="save30", original_amount=100.0)
    res = await coupon_service.redeem_coupon(db, normal_user, req)

    assert res.success is True
    assert res.coupon_code == "SAVE30"
    assert res.original_amount == 100.0
    assert res.discounted_amount == 30.0
    assert res.final_amount == 70.0
    assert coupon.current_uses == 1
    mock_repo.admin_update_coupon.assert_called_once()


@pytest.mark.asyncio
async def test_redeem_coupon_limit_exceeded(coupon_service, normal_user, mock_repo):
    db = AsyncMock()
    coupon = Coupons(
        id=uuid.uuid4(),
        code="LIMITED",
        discount_type=DiscountType.FIXED_AMOUNT,
        discount_value=Decimal("10.0"),
        is_active=True,
        max_uses=5,
        current_uses=5,
    )
    mock_repo.admin_get_by_coupon_code.return_value = coupon

    req = RedeemRequest(code="LIMITED", original_amount=50.0)
    with pytest.raises(HTTPException) as exc:
        await coupon_service.redeem_coupon(db, normal_user, req)
    assert exc.value.status_code == 400
    assert "maximum total redemptions limit" in exc.value.detail


@pytest.mark.asyncio
async def test_revert_redemption(coupon_service, admin_user, mock_repo):
    db = AsyncMock()
    redemption_id = uuid.uuid4()
    coupon_id = uuid.uuid4()

    redemption = CouponRedemptions(
        id=redemption_id,
        coupon_id=coupon_id,
        user_id=uuid.uuid4(),
        original_amount=Decimal("100"),
        discounted_amount=Decimal("20"),
        final_amount=Decimal("80"),
        status=RedemptionStatus.APPLIED,
        redeemed_at=datetime.now(timezone.utc),
    )

    coupon = Coupons(
        id=coupon_id,
        code="REVERTME",
        current_uses=2,
        is_active=True,
        discount_type=DiscountType.PERCENTAGE,
    )

    db_execute_result = MagicMock()
    db_execute_result.scalar_one_or_none.return_value = redemption
    db.execute.return_value = db_execute_result

    mock_repo.admin_get_coupon_by_id.return_value = coupon

    res = await coupon_service.revert_redemption(db, redemption_id, admin_user)
    assert res["success"] is True
    assert redemption.status == RedemptionStatus.REVERTED
    assert coupon.current_uses == 1


@pytest.mark.asyncio
async def test_delete_coupon_non_admin_forbidden(coupon_service, normal_user):
    db = AsyncMock()
    coupon_id = uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        await coupon_service.delete_coupon(db, coupon_id, normal_user)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_delete_coupon_not_found(coupon_service, admin_user, mock_repo):
    db = AsyncMock()
    coupon_id = uuid.uuid4()
    mock_repo.admin_get_coupon_by_id.return_value = None

    with pytest.raises(HTTPException) as exc:
        await coupon_service.delete_coupon(db, coupon_id, admin_user)
    assert exc.value.status_code == 404
    assert f"Coupon with id '{coupon_id}' was not found." in exc.value.detail


@pytest.mark.asyncio
async def test_delete_coupon_success(coupon_service, admin_user, mock_repo):
    db = AsyncMock()
    coupon_id = uuid.uuid4()
    coupon = Coupons(
        id=coupon_id,
        code="DELETEME",
        discount_type=DiscountType.PERCENTAGE,
        discount_value=Decimal("10"),
    )
    mock_repo.admin_get_coupon_by_id.return_value = coupon
    mock_repo.admin_delete_coupon.return_value = True

    res = await coupon_service.delete_coupon(db, coupon_id, admin_user)
    assert res["success"] is True
    assert "DELETEME" in res["message"]
    mock_repo.admin_delete_coupon.assert_called_once_with(db, coupon_id)

