import { useState } from "react";
import { Modal, Loader, Switch } from "@mantine/core";
import { DateTimePicker } from "@mantine/dates";
import dayjs from "dayjs";
import { notifications } from "@mantine/notifications";
import {
  Tag,
  Calendar,
  Clock,
  DollarSign,
  Percent,
  AlertCircle,
  Hash,
  Users,
  Sparkles,
  CheckCircle2,
} from "lucide-react";
import { useCreateCoupon, useUpdateCoupon } from "@/hooks/api/useRedeem";
import type {
  CouponDetailResponse,
  DiscountType,
  CreateCouponPayload,
  UpdateCouponPayload,
} from "@/api/redeem";

interface CouponModalProps {
  opened: boolean;
  onClose: () => void;
  couponToEdit?: CouponDetailResponse | null;
}

interface CouponModalFormProps {
  couponToEdit?: CouponDetailResponse | null;
  onClose: () => void;
}

const dateTimePickerStyles = {
  input: {
    backgroundColor: "var(--color-surface-card)",
    borderColor: "var(--color-border-default)",
    color: "var(--color-text-dark)",
    fontSize: "12px",
    borderRadius: "8px",
    height: "34px",
  },
  calendarHeader: {
    color: "var(--color-text-dark)",
    maxWidth: "100%",
  },
  calendarHeaderControl: {
    color: "var(--color-text-dark)",
    borderRadius: "8px",
  },
  calendarHeaderLevel: {
    color: "var(--color-text-dark)",
    fontWeight: 600,
    fontSize: "13px",
    borderRadius: "8px",
  },
  weekday: {
    color: "var(--color-text-muted)",
    fontSize: "11px",
    fontWeight: 600,
  },
  day: {
    color: "var(--color-text-dark)",
    borderRadius: "8px",
    fontSize: "12px",
  },
  pickerControl: {
    color: "var(--color-text-dark)",
    borderRadius: "8px",
    fontSize: "12px",
  },
  timeWrapper: {
    borderTop: "1px solid var(--color-border-default)",
    paddingTop: "10px",
    marginTop: "10px",
    display: "flex",
    alignItems: "center",
    gap: "8px",
  },
  timeInput: {
    flex: 1,
    backgroundColor: "var(--color-surface-primary)",
    borderColor: "var(--color-border-default)",
    color: "var(--color-text-dark)",
    borderRadius: "8px",
    fontSize: "12px",
    height: "34px",
    marginInlineEnd: 0,
  },
  submitButton: {
    backgroundColor: "var(--color-text-dark)",
    color: "var(--color-surface-card)",
    borderRadius: "8px",
    width: "34px",
    height: "34px",
    border: "none",
  },
};

const dateTimePickerPopoverProps = {
  withinPortal: true,
  zIndex: 1000,
  classNames: {
    dropdown: "admin-datetime-picker-dropdown",
  },
  styles: {
    dropdown: {
      backgroundColor: "var(--color-surface-card)",
      borderRadius: "14px",
      boxShadow:
        "0 12px 30px -4px rgba(0, 0, 0, 0.12), 0 4px 12px -2px rgba(0, 0, 0, 0.08)",
      padding: "14px",
    },
  },
};

const dateTimePickerTimePickerProps = {
  format: "12h" as const,
  size: "xs" as const,
  styles: {
    input: {
      backgroundColor: "var(--color-surface-primary)",
      color: "var(--color-text-dark)",
      borderRadius: "8px",
      height: "34px",
    },
    field: {
      color: "var(--color-text-dark)",
      fontWeight: 600,
    },
  },
};

const dateTimePickerSubmitButtonProps = {
  variant: "filled" as const,
  style: {
    backgroundColor: "var(--color-text-dark)",
    color: "var(--color-surface-card)",
    borderRadius: "8px",
    width: "34px",
    height: "34px",
    border: "none",
    cursor: "pointer",
  },
};

const CouponModalForm = ({ couponToEdit, onClose }: CouponModalFormProps) => {
  const isEditing = !!couponToEdit;
  const createMutation = useCreateCoupon();
  const updateMutation = useUpdateCoupon();

  const [code, setCode] = useState(couponToEdit?.code ?? "");
  const [description, setDescription] = useState(
    couponToEdit?.description ?? "",
  );
  const [discountType, setDiscountType] = useState<DiscountType>(
    couponToEdit?.discount_type ?? "percentage",
  );
  const [discountValue, setDiscountValue] = useState<string>(
    couponToEdit?.discount_value !== null &&
      couponToEdit?.discount_value !== undefined
      ? String(couponToEdit.discount_value)
      : "",
  );
  const [currency, setCurrency] = useState(couponToEdit?.currency ?? "USD");
  const [maxDiscountAmount, setMaxDiscountAmount] = useState<string>(
    couponToEdit?.max_discount_amount !== null &&
      couponToEdit?.max_discount_amount !== undefined
      ? String(couponToEdit.max_discount_amount)
      : "",
  );
  const [maxUses, setMaxUses] = useState<string>(
    couponToEdit?.max_uses !== null && couponToEdit?.max_uses !== undefined
      ? String(couponToEdit.max_uses)
      : "",
  );
  const [usageLimitPerUser, setUsageLimitPerUser] = useState<string>(
    couponToEdit?.usage_limit_per_user !== null &&
      couponToEdit?.usage_limit_per_user !== undefined
      ? String(couponToEdit.usage_limit_per_user)
      : "1",
  );
  const [validFrom, setValidFrom] = useState<string | null>(
    couponToEdit?.valid_from
      ? dayjs(couponToEdit.valid_from).format("YYYY-MM-DD HH:mm:ss")
      : null,
  );
  const [validTill, setValidTill] = useState<string | null>(
    couponToEdit?.valid_till
      ? dayjs(couponToEdit.valid_till).format("YYYY-MM-DD HH:mm:ss")
      : null,
  );
  const [newUsersOnly, setNewUsersOnly] = useState(
    couponToEdit?.new_users_only ?? false,
  );
  const [isActive, setIsActive] = useState(couponToEdit?.is_active ?? true);
  const [formError, setFormError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    const trimmedCode = code.trim().toUpperCase();
    if (!trimmedCode) {
      setFormError("Coupon code is required");
      return;
    }

    if (
      discountType !== "full_free" &&
      (!discountValue || Number(discountValue) <= 0)
    ) {
      setFormError("Please provide a valid discount value greater than 0");
      return;
    }

    if (discountType === "percentage" && Number(discountValue) > 100) {
      setFormError("Percentage discount cannot exceed 100%");
      return;
    }

    try {
      if (isEditing && couponToEdit) {
        const payload: UpdateCouponPayload = {
          code: trimmedCode,
          description: description.trim() || undefined,
          discount_type: discountType,
          discount_value:
            discountType === "full_free" ? undefined : Number(discountValue),
          currency: currency.trim() || "USD",
          max_discount_amount: maxDiscountAmount
            ? Number(maxDiscountAmount)
            : undefined,
          max_uses: maxUses ? Number(maxUses) : undefined,
          usage_limit_per_user: usageLimitPerUser
            ? Number(usageLimitPerUser)
            : undefined,
          valid_from: validFrom ? dayjs(validFrom).toISOString() : undefined,
          valid_till: validTill ? dayjs(validTill).toISOString() : undefined,
          new_users_only: newUsersOnly,
          is_active: isActive,
        };

        await updateMutation.mutateAsync({
          couponId: couponToEdit.id,
          payload,
        });
        notifications.show({
          title: "Coupon Updated",
          message: `Coupon ${trimmedCode} updated successfully.`,
          color: "green",
        });
      } else {
        const payload: CreateCouponPayload = {
          code: trimmedCode,
          description: description.trim() || undefined,
          discount_type: discountType,
          discount_value:
            discountType === "full_free" ? undefined : Number(discountValue),
          currency: currency.trim() || "USD",
          max_discount_amount: maxDiscountAmount
            ? Number(maxDiscountAmount)
            : undefined,
          max_uses: maxUses ? Number(maxUses) : undefined,
          usage_limit_per_user: usageLimitPerUser
            ? Number(usageLimitPerUser)
            : 1,
          valid_from: validFrom ? dayjs(validFrom).toISOString() : undefined,
          valid_till: validTill ? dayjs(validTill).toISOString() : undefined,
          new_users_only: newUsersOnly,
          is_active: isActive,
        };

        await createMutation.mutateAsync(payload);
        notifications.show({
          title: "Coupon Created",
          message: `Coupon ${trimmedCode} created successfully.`,
          color: "green",
        });
      }
      onClose();
    } catch (err: unknown) {
      const errorObj = err as { message?: string; data?: { detail?: string } };
      const msg =
        errorObj?.data?.detail || errorObj?.message || "Failed to save coupon.";
      setFormError(msg);
      notifications.show({
        title: "Error",
        message: msg,
        color: "red",
      });
    }
  };

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {formError && (
        <div className="p-3 rounded-8 bg-state-danger/10 border border-state-danger/20 text-state-danger text-xs flex items-center gap-2">
          <AlertCircle size={15} className="shrink-0" />
          <span>{formError}</span>
        </div>
      )}

      {/* Row 1: Code and Discount Type */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
        <div>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark mb-1.5">
            <Tag size={13} className="text-text-muted" />
            <span>Coupon Promo Code</span>
            <span className="text-state-danger">*</span>
          </label>
          <input
            type="text"
            required
            placeholder="e.g. SUMMER50"
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark font-mono uppercase placeholder:text-text-muted/60 focus:outline-none focus:border-text-dark transition-colors"
          />
        </div>

        <div>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark mb-1.5">
            <Percent size={13} className="text-text-muted" />
            <span>Discount Type</span>
            <span className="text-state-danger">*</span>
          </label>
          <select
            value={discountType}
            onChange={(e) => setDiscountType(e.target.value as DiscountType)}
            className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark transition-colors cursor-pointer"
          >
            <option value="percentage">Percentage (%)</option>
            <option value="fixed_amount">Fixed Amount ($)</option>
            <option value="full_free">100% Full Free</option>
          </select>
        </div>
      </div>

      {/* Row 2: Discount Value, Currency & Max Discount Amount */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3.5">
        {discountType !== "full_free" ? (
          <div>
            <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark mb-1.5">
              {discountType === "percentage" ? (
                <Percent size={13} className="text-text-muted" />
              ) : (
                <DollarSign size={13} className="text-text-muted" />
              )}
              <span>
                {discountType === "percentage"
                  ? "Discount (%)"
                  : "Discount Amount"}
              </span>
              <span className="text-state-danger">*</span>
            </label>
            <input
              type="number"
              step="any"
              min="0"
              max={discountType === "percentage" ? 100 : undefined}
              required
              placeholder={
                discountType === "percentage" ? "e.g. 20" : "e.g. 15.00"
              }
              value={discountValue}
              onChange={(e) => setDiscountValue(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark placeholder:text-text-muted/60 focus:outline-none focus:border-text-dark transition-colors"
            />
          </div>
        ) : (
          <div className="p-2 rounded-8 bg-surface-primary border border-border-default flex items-center gap-2">
            <Sparkles size={14} className="text-emerald-500 shrink-0" />
            <span className="text-[11px] text-text-muted font-medium">
              100% Free checkout grant
            </span>
          </div>
        )}

        <div>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark mb-1.5">
            <DollarSign size={13} className="text-text-muted" />
            <span>Currency</span>
          </label>
          <input
            type="text"
            maxLength={3}
            placeholder="USD"
            value={currency}
            onChange={(e) => setCurrency(e.target.value.toUpperCase())}
            className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark uppercase placeholder:text-text-muted/60 focus:outline-none focus:border-text-dark transition-colors"
          />
        </div>

        <div>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark mb-1.5">
            <DollarSign size={13} className="text-text-muted" />
            <span>Max Discount Cap</span>
          </label>
          <input
            type="number"
            step="any"
            min="0"
            placeholder="Optional limit ($)"
            value={maxDiscountAmount}
            onChange={(e) => setMaxDiscountAmount(e.target.value)}
            className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark placeholder:text-text-muted/60 focus:outline-none focus:border-text-dark transition-colors"
          />
        </div>
      </div>

      {/* Row 3: Description */}
      <div>
        <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark mb-1.5">
          <span>Description / Campaign Note</span>
        </label>
        <input
          type="text"
          placeholder="e.g. Black Friday 2026 early bird discount"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark placeholder:text-text-muted/60 focus:outline-none focus:border-text-dark transition-colors"
        />
      </div>

      {/* Row 4: Usage Limits */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
        <div>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark mb-1.5">
            <Hash size={13} className="text-text-muted" />
            <span>Global Max Redemptions</span>
          </label>
          <input
            type="number"
            min="1"
            placeholder="Leave empty for unlimited"
            value={maxUses}
            onChange={(e) => setMaxUses(e.target.value)}
            className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark placeholder:text-text-muted/60 focus:outline-none focus:border-text-dark transition-colors"
          />
        </div>

        <div>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark mb-1.5">
            <Users size={13} className="text-text-muted" />
            <span>Usage Limit Per User</span>
          </label>
          <input
            type="number"
            min="1"
            placeholder="1"
            value={usageLimitPerUser}
            onChange={(e) => setUsageLimitPerUser(e.target.value)}
            className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark placeholder:text-text-muted/60 focus:outline-none focus:border-text-dark transition-colors"
          />
        </div>
      </div>

      {/* Row 5: Validity Dates */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
        <div>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark mb-1.5">
            <Calendar size={13} className="text-text-muted" />
            <span>Valid From</span>
          </label>
          <DateTimePicker
            value={validFrom}
            onChange={(val) =>
              setValidFrom(
                val ? dayjs(val).format("YYYY-MM-DD HH:mm:ss") : null,
              )
            }
            valueFormat="YYYY-MM-DD hh:mm A"
            placeholder="Select start date & time"
            clearable
            leftSection={<Calendar size={14} className="text-text-muted" />}
            size="xs"
            radius="md"
            popoverProps={dateTimePickerPopoverProps}
            styles={dateTimePickerStyles}
            timePickerProps={dateTimePickerTimePickerProps}
            submitButtonProps={dateTimePickerSubmitButtonProps}
          />
          <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
            <span className="text-[10px] text-text-muted">Quick:</span>
            <button
              type="button"
              onClick={() =>
                setValidFrom(dayjs().format("YYYY-MM-DD HH:mm:ss"))
              }
              className="px-2 py-0.5 rounded-full text-xs! font-medium bg-surface-primary border border-border-default text-text-muted hover:text-text-dark hover:border-text-muted/40 transition-colors cursor-pointer"
            >
              Now
            </button>
            <button
              type="button"
              onClick={() =>
                setValidFrom(
                  dayjs()
                    .add(1, "day")
                    .startOf("day")
                    .format("YYYY-MM-DD HH:mm:ss"),
                )
              }
              className="px-2 py-0.5 rounded-full text-xs! font-medium bg-surface-primary border border-border-default text-text-muted hover:text-text-dark hover:border-text-muted/40 transition-colors cursor-pointer"
            >
              Tomorrow
            </button>
          </div>
        </div>

        <div>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark mb-1.5">
            <Clock size={13} className="text-text-muted" />
            <span>Valid Till (Expiry)</span>
          </label>
          <DateTimePicker
            value={validTill}
            onChange={(val) =>
              setValidTill(
                val ? dayjs(val).format("YYYY-MM-DD HH:mm:ss") : null,
              )
            }
            minDate={validFrom ? new Date(validFrom) : undefined}
            valueFormat="YYYY-MM-DD hh:mm A"
            placeholder="Select expiry date & time (or leave blank)"
            clearable
            leftSection={<Clock size={14} className="text-text-muted" />}
            size="xs"
            radius="md"
            popoverProps={dateTimePickerPopoverProps}
            styles={dateTimePickerStyles}
            timePickerProps={dateTimePickerTimePickerProps}
            submitButtonProps={dateTimePickerSubmitButtonProps}
          />
          <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
            <span className="text-[10px] text-text-muted">Presets:</span>
            {[
              { label: "+7 Days", days: 7 },
              { label: "+30 Days", days: 30 },
              { label: "+90 Days", days: 90 },
            ].map((p) => (
              <button
                key={p.label}
                type="button"
                onClick={() => {
                  const base = validFrom ? dayjs(validFrom) : dayjs();
                  setValidTill(
                    base.add(p.days, "day").format("YYYY-MM-DD HH:mm:ss"),
                  );
                }}
                className="px-2 py-0.5 rounded-full text-xs! font-medium bg-surface-primary border border-border-default text-text-muted hover:text-text-dark hover:border-text-muted/40 transition-colors cursor-pointer"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Row 6: Switches (Active Status & New Users Only) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5 pt-1">
        <div className="p-3 rounded-8 bg-surface-primary border border-border-default flex items-center justify-between">
          <div className="space-y-0.5 pr-2">
            <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark">
              <CheckCircle2
                size={13}
                className={isActive ? "text-emerald-500" : "text-text-muted"}
              />
              <span>Active Status</span>
            </label>
            <p className="text-[11px] text-text-muted">
              Enabled for redemption
            </p>
          </div>
          <Switch
            checked={isActive}
            onChange={(e) => setIsActive(e.currentTarget.checked)}
            color="teal"
            size="sm"
          />
        </div>

        <div className="p-3 rounded-8 bg-surface-primary border border-border-default flex items-center justify-between">
          <div className="space-y-0.5 pr-2">
            <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark">
              <Users
                size={13}
                className={newUsersOnly ? "text-amber-500" : "text-text-muted"}
              />
              <span>New Users Only</span>
            </label>
            <p className="text-[11px] text-text-muted">
              First-time customers only
            </p>
          </div>
          <Switch
            checked={newUsersOnly}
            onChange={(e) => setNewUsersOnly(e.currentTarget.checked)}
            color="orange"
            size="sm"
          />
        </div>
      </div>

      {/* Modal Action Buttons */}
      <div className="flex items-center justify-end gap-2.5 pt-3 border-t border-border-default">
        <button
          type="button"
          onClick={onClose}
          disabled={isPending}
          className="px-3.5 py-1.5 rounded-8 border border-border-default text-xs font-medium text-text-muted hover:text-text-dark hover:bg-surface-primary transition-colors cursor-pointer"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={isPending}
          className="px-4 py-1.5 rounded-8 btn-gradient-black text-xs font-semibold cursor-pointer flex items-center gap-1.5 shadow-2xs disabled:opacity-50"
        >
          {isPending && <Loader size={12} color="white" />}
          <span>{isEditing ? "Save Changes" : "Create Coupon"}</span>
        </button>
      </div>
    </form>
  );
};

export const CouponModal = ({
  opened,
  onClose,
  couponToEdit,
}: CouponModalProps) => {
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2">
          <Tag size={17} className="text-text-dark" />
          <span className="font-bold text-sm text-text-dark">
            {couponToEdit
              ? `Edit Coupon: ${couponToEdit.code}`
              : "Create New Coupon"}
          </span>
        </div>
      }
      size="lg"
      centered
      radius="md"
      overlayProps={{ backgroundOpacity: 0.55, blur: 3 }}
      styles={{
        header: {
          backgroundColor: "var(--color-surface-card)",
          borderBottom: "1px solid var(--color-border-default)",
          padding: "16px 20px",
        },
        body: {
          backgroundColor: "var(--color-surface-card)",
          padding: "20px",
        },
      }}
    >
      {opened && (
        <CouponModalForm
          key={couponToEdit ? couponToEdit.id : "create"}
          couponToEdit={couponToEdit}
          onClose={onClose}
        />
      )}
    </Modal>
  );
};

export default CouponModal;
