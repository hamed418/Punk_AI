import { useState } from "react";
import { Modal, Loader, Switch } from "@mantine/core";
import { DateTimePicker } from "@mantine/dates";
import dayjs from "dayjs";
import { notifications } from "@mantine/notifications";
import {
  KeyRound,
  Hash,
  Clock,
  AlertCircle,
  CheckCircle2,
  Shield,
} from "lucide-react";
import {
  useCreateRedeemCode,
  useUpdateRedeemCode,
} from "@/hooks/api/useRedeem";
import type {
  RedeemCodesResponse,
  RedeemCodesCreate,
  RedeemCodesUpdate,
} from "@/api/redeem";

interface CodeModalProps {
  opened: boolean;
  onClose: () => void;
  codeToEdit?: RedeemCodesResponse | null;
}

interface CodeModalFormProps {
  codeToEdit?: RedeemCodesResponse | null;
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
      borderColor: "var(--color-border-default)",
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
      borderColor: "var(--color-border-default)",
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

const CodeModalForm = ({ codeToEdit, onClose }: CodeModalFormProps) => {
  const isEditing = !!codeToEdit;
  const createMutation = useCreateRedeemCode();
  const updateMutation = useUpdateRedeemCode();

  const [isSingle, setIsSingle] = useState(
    codeToEdit ? codeToEdit.is_single : true,
  );
  const [maxRedemptions, setMaxRedemptions] = useState(
    codeToEdit ? String(codeToEdit.max_redemptions) : "1",
  );
  const [isActive, setIsActive] = useState(
    codeToEdit ? codeToEdit.is_active : true,
  );
  const [expiresAt, setExpiresAt] = useState<string | null>(
    codeToEdit?.expires_at
      ? dayjs(codeToEdit.expires_at).format("YYYY-MM-DD HH:mm:ss")
      : null,
  );
  const [formError, setFormError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    const redemptionsNum = isSingle ? 1 : Number(maxRedemptions);
    if (!isSingle && (isNaN(redemptionsNum) || redemptionsNum < 1)) {
      setFormError("Max redemptions must be at least 1");
      return;
    }

    try {
      if (isEditing && codeToEdit) {
        const payload: RedeemCodesUpdate = {
          is_active: isActive,
          is_single: isSingle,
          max_redemptions: redemptionsNum,
          expires_at: expiresAt ? dayjs(expiresAt).toISOString() : undefined,
        };

        await updateMutation.mutateAsync({ codeId: codeToEdit.id, payload });
        notifications.show({
          title: "Code Updated",
          message: `Redeem code ${codeToEdit.code} updated successfully.`,
          color: "green",
        });
      } else {
        const payload: RedeemCodesCreate = {
          is_active: isActive,
          is_single: isSingle,
          max_redemptions: redemptionsNum,
        };

        const res = await createMutation.mutateAsync(payload);
        notifications.show({
          title: "Code Generated",
          message: `New redeem code '${res.code}' created successfully.`,
          color: "green",
        });
      }
      onClose();
    } catch (err: unknown) {
      const errorObj = err as { message?: string; data?: { detail?: string } };
      const msg =
        errorObj?.data?.detail ||
        errorObj?.message ||
        "Failed to save redeem code.";
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

      {!isEditing && (
        <div className="p-3 rounded-8 bg-surface-primary border border-border-default text-xs text-text-muted">
          <p>
            An 8-character unique alphanumeric code will be automatically
            generated upon creation.
          </p>
        </div>
      )}

      {/* Single Use Switch */}
      <div className="p-3.5 rounded-8 bg-surface-primary border border-border-default flex items-center justify-between">
        <div className="space-y-0.5 pr-3">
          <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark">
            <Shield size={13} className="text-text-muted" />
            <span>Single Use Only</span>
          </label>
          <p className="text-[11px] text-text-muted">
            {isSingle
              ? "Code can be claimed by exactly one user"
              : "Code can be claimed multiple times"}
          </p>
        </div>
        <Switch
          checked={isSingle}
          onChange={(e) => {
            const val = e.currentTarget.checked;
            setIsSingle(val);
            if (val) setMaxRedemptions("1");
          }}
          color="teal"
          size="sm"
        />
      </div>

      {/* Max Redemptions (if multi use) */}
      {!isSingle && (
        <div>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark mb-1.5">
            <Hash size={13} className="text-text-muted" />
            <span>Maximum Redemptions</span>
            <span className="text-state-danger">*</span>
          </label>
          <input
            type="number"
            min="1"
            required
            placeholder="e.g. 10"
            value={maxRedemptions}
            onChange={(e) => setMaxRedemptions(e.target.value)}
            className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark placeholder:text-text-muted/60 focus:outline-none focus:border-text-dark transition-colors"
          />
        </div>
      )}

      {/* Active Switch */}
      <div className="p-3.5 rounded-8 bg-surface-primary border border-border-default flex items-center justify-between">
        <div className="space-y-0.5 pr-3">
          <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark">
            <CheckCircle2
              size={13}
              className={isActive ? "text-emerald-500" : "text-text-muted"}
            />
            <span>Active Status</span>
          </label>
          <p className="text-[11px] text-text-muted">
            {isActive ? "Code is active and claimable" : "Code is deactivated"}
          </p>
        </div>
        <Switch
          checked={isActive}
          onChange={(e) => setIsActive(e.currentTarget.checked)}
          color="teal"
          size="sm"
        />
      </div>

      {/* Expiry Date (optional when editing) */}
      {isEditing && (
        <div>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark mb-1.5">
            <Clock size={13} className="text-text-muted" />
            <span>Expiration Date</span>
          </label>
          <DateTimePicker
            value={expiresAt}
            onChange={(val) =>
              setExpiresAt(
                val ? dayjs(val).format("YYYY-MM-DD HH:mm:ss") : null,
              )
            }
            valueFormat="YYYY-MM-DD hh:mm A"
            placeholder="Select expiration date & time"
            clearable
            leftSection={<Clock size={14} className="text-text-muted" />}
            size="xs"
            radius="md"
            popoverProps={dateTimePickerPopoverProps}
            styles={dateTimePickerStyles}
            timePickerProps={dateTimePickerTimePickerProps}
            submitButtonProps={dateTimePickerSubmitButtonProps}
          />
        </div>
      )}

      {/* Action Buttons */}
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
          <span>{isEditing ? "Save Changes" : "Generate Code"}</span>
        </button>
      </div>
    </form>
  );
};

export const CodeModal = ({ opened, onClose, codeToEdit }: CodeModalProps) => {
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2">
          <KeyRound size={17} className="text-text-dark" />
          <span className="font-bold text-sm text-text-dark">
            {codeToEdit
              ? `Edit Redeem Code: ${codeToEdit.code}`
              : "Generate New Redeem Code"}
          </span>
        </div>
      }
      size="md"
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
        <CodeModalForm
          key={codeToEdit ? codeToEdit.id : "create"}
          codeToEdit={codeToEdit}
          onClose={onClose}
        />
      )}
    </Modal>
  );
};

export default CodeModal;
