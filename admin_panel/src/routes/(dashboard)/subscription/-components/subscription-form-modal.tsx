import React, { useState, useRef, useEffect } from "react";
import { Plus, Trash2, Loader2, AlertCircle } from "lucide-react";
import { Modal } from "@mantine/core";
import type { Plan } from "@/types/subscription";
import { parsePlanData } from "./subscription-utils";

interface SubscriptionFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  editingPlan: Plan | null;
  onSubmit: (
    data: any,
    submitStatus?: "draft" | "published"
  ) => Promise<void>;
  isFormLoading: boolean;
  formError: string | null;
  setFormError: (error: string | null) => void;
}

const SubscriptionFormModal: React.FC<SubscriptionFormModalProps> = ({
  isOpen,
  onClose,
  editingPlan,
  onSubmit,
  isFormLoading,
  formError,
  setFormError,
}) => {
  const [priceId, setPriceId] = useState<string>("");
  const [planName, setPlanName] = useState<string>("");
  const [shortDescription, setShortDescription] = useState<string>("");
  const [amount, setAmount] = useState<string>("");
  const [totalTokens, setTotalTokens] = useState<string>("");
  const [interval, setInterval] = useState<string>("month");
  const [type, setType] = useState<"SUBSCRIPTION" | "TOKEN_PACK">("SUBSCRIPTION");
  const [features, setFeatures] = useState<string[]>([""]);
  const [status, setStatus] = useState<"draft" | "published">("published");

  const featureInputRefs = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    if (isOpen) {
      if (editingPlan) {
        setPriceId(editingPlan.price_id || "");
        const parsed = parsePlanData(editingPlan);
        setPlanName(editingPlan.name || parsed.name);
        setShortDescription(parsed.shortDescription);
        setFeatures(parsed.features.length > 0 ? parsed.features : [""]);
        setStatus(parsed.status);
        setInterval(editingPlan.interval || "month");
        setType(editingPlan.type || "SUBSCRIPTION");
        const numericAmount = typeof editingPlan.amount === "number" ? editingPlan.amount : parseFloat(editingPlan.amount) || 0;
        setAmount(numericAmount.toString());
        setTotalTokens(editingPlan.total_token_can_use?.toString() || "0");
      } else {
        setPriceId("");
        setPlanName("");
        setShortDescription("");
        setAmount("");
        setTotalTokens("");
        setInterval("month");
        setType("SUBSCRIPTION");
        setFeatures([""]);
        setStatus("published");
      }
      setFormError(null);
    }
  }, [isOpen, editingPlan, setFormError]);

  const handleAddFeature = () => {
    setFeatures((prev) => {
      const updated = [...prev, ""];
      setTimeout(() => {
        const lastIdx = updated.length - 1;
        featureInputRefs.current[lastIdx]?.focus();
      }, 50);
      return updated;
    });
  };

  const handleFeatureChange = (index: number, value: string) => {
    setFeatures((prev) => {
      const updated = [...prev];
      updated[index] = value;
      return updated;
    });
  };

  const handleFeatureKeyDown = (index: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAddFeature();
    }
  };

  const handleRemoveFeature = (index: number) => {
    setFeatures((prev) => {
      if (prev.length <= 1) return [""];
      return prev.filter((_, i) => i !== index);
    });
  };

  const handleFormSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    if (!planName.trim()) {
      setFormError("Plan name is required.");
      return;
    }
    const parsedAmount = parseFloat(amount);
    if (isNaN(parsedAmount) || parsedAmount < 0) {
      setFormError("Amount must be a valid positive number.");
      return;
    }
    const parsedTokens = parseInt(totalTokens);
    if (isNaN(parsedTokens) || parsedTokens < 0) {
      setFormError("Tokens allocation must be a valid number.");
      return;
    }

    const cleanFeatures = features.map((f) => f.trim()).filter(Boolean);
    const slug = planName.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-");

    const encodedDescription = JSON.stringify({
      shortDescription: shortDescription.trim(),
      features: cleanFeatures,
      name: planName.trim(),
      status: status,
    });

    const data = {
      name: planName.trim(),
      slug: editingPlan?.slug || slug,
      price_id: priceId.trim() || undefined,
      description: encodedDescription,
      features: cleanFeatures,
      amount: parsedAmount,
      currency: "usd",
      interval,
      type,
      total_token_can_use: parsedTokens,
    };

    await onSubmit(data);
  };

  return (
    <Modal
      opened={isOpen}
      onClose={() => !isFormLoading && onClose()}
      title={
        <span className="text-sm font-bold text-text-dark">
          {editingPlan ? "Edit Plan" : "New Subscription Plan"}
        </span>
      }
      centered
      radius="md"
      size="lg"
    >
      <form onSubmit={handleFormSubmit} className="space-y-4 pt-2 relative">
        {/* Centered modal loading overlay */}
        {isFormLoading && (
          <div className="absolute -inset-4 bg-surface-card/85 backdrop-blur-xs z-30 flex flex-col items-center justify-center gap-2.5 rounded-12">
            <Loader2 size={28} className="animate-spin text-text-dark" />
            <span className="text-[13px] font-semibold text-text-dark">
              {editingPlan ? "Saving plan changes..." : "Creating new plan..."}
            </span>
          </div>
        )}

        {formError && (
          <div className="p-2.5 rounded-8 bg-state-danger/10 border border-state-danger/20 text-state-danger text-xs flex items-center gap-2">
            <AlertCircle size={14} className="shrink-0" />
            <span>{formError}</span>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-[12px] font-medium text-text-dark mb-1">
              Plan Name <span className="text-state-danger">*</span>
            </label>
            <input
              type="text"
              disabled={isFormLoading}
              value={planName}
              onChange={(e) => setPlanName(e.target.value)}
              className="w-full h-9 px-3 rounded-8 border border-border-default bg-surface-card text-[13px] text-text-dark focus:outline-none focus:border-text-dark disabled:opacity-50"
              placeholder="Pro / Starter / Enterprise"
              required
            />
          </div>
          <div>
            <label className="block text-[12px] font-medium text-text-dark mb-1">
              Price (USD) <span className="text-state-danger">*</span>
            </label>
            <input
              type="number"
              step="0.01"
              disabled={isFormLoading}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="w-full h-9 px-3 rounded-8 border border-border-default bg-surface-card text-[13px] text-text-dark focus:outline-none focus:border-text-dark disabled:opacity-50"
              placeholder="29"
              required
            />
          </div>
        </div>

        <div className="grid grid-cols-4 gap-3">
          <div>
            <label className="block text-[12px] font-medium text-text-dark mb-1">
              Tokens Can Use <span className="text-state-danger">*</span>
            </label>
            <input
              type="number"
              disabled={isFormLoading}
              value={totalTokens}
              onChange={(e) => setTotalTokens(e.target.value)}
              className="w-full h-9 px-3 rounded-8 border border-border-default bg-surface-card text-[13px] text-text-dark focus:outline-none focus:border-text-dark disabled:opacity-50"
              placeholder="50000"
              required
            />
          </div>
          <div>
            <label className="block text-[12px] font-medium text-text-dark mb-1">
              Billing Interval
            </label>
            <select
              disabled={isFormLoading}
              value={interval}
              onChange={(e) => setInterval(e.target.value)}
              className="w-full h-9 px-3 rounded-8 border border-border-default bg-surface-card text-[13px] text-text-dark focus:outline-none focus:border-text-dark disabled:opacity-50"
            >
              <option value="month">Monthly</option>
              <option value="year">Yearly</option>
              <option value="one-time">One-time</option>
            </select>
          </div>
          <div>
            <label className="block text-[12px] font-medium text-text-dark mb-1">
              Plan Type
            </label>
            <select
              disabled={isFormLoading}
              value={type}
              onChange={(e) => setType(e.target.value as "SUBSCRIPTION" | "TOKEN_PACK")}
              className="w-full h-9 px-3 rounded-8 border border-border-default bg-surface-card text-[13px] text-text-dark focus:outline-none focus:border-text-dark disabled:opacity-50"
            >
              <option value="SUBSCRIPTION">Subscription</option>
              <option value="TOKEN_PACK">Token Pack</option>
            </select>
          </div>
          <div>
            <label className="block text-[12px] font-medium text-text-dark mb-1">
              Stripe Price ID
            </label>
            <input
              type="text"
              disabled={isFormLoading}
              value={priceId}
              onChange={(e) => setPriceId(e.target.value)}
              className="w-full h-9 px-3 rounded-8 border border-border-default bg-surface-card text-[13px] text-text-dark focus:outline-none focus:border-text-dark disabled:opacity-50"
              placeholder="price_xxx (optional)"
            />
          </div>
        </div>

        <div>
          <label className="block text-[12px] font-medium text-text-dark mb-1">
            Short Description
          </label>
          <textarea
            rows={2}
            disabled={isFormLoading}
            value={shortDescription}
            onChange={(e) => setShortDescription(e.target.value)}
            className="w-full p-2.5 rounded-8 border border-border-default bg-surface-card text-[13px] text-text-dark focus:outline-none focus:border-text-dark resize-none disabled:opacity-50"
            placeholder="Great for individuals running campaigns at scale..."
          />
        </div>

        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="block text-[12px] font-medium text-text-dark">
              Plan Features ({features.filter((f) => f.trim()).length})
            </label>
            <button
              type="button"
              disabled={isFormLoading}
              onClick={handleAddFeature}
              className="text-[11px] text-highlight-cyan hover:underline font-medium cursor-pointer flex items-center gap-1"
            >
              <Plus size={12} />
              <span>Add feature</span>
            </button>
          </div>
          <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
            {features.map((feat, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <input
                  ref={(el) => {
                    featureInputRefs.current[idx] = el;
                  }}
                  type="text"
                  disabled={isFormLoading}
                  value={feat}
                  onKeyDown={(e) => handleFeatureKeyDown(idx, e)}
                  onChange={(e) => handleFeatureChange(idx, e.target.value)}
                  className="flex-1 h-8 px-2.5 rounded-6 border border-border-default bg-surface-card text-[12px] text-text-dark focus:outline-none focus:border-text-dark disabled:opacity-50"
                  placeholder={`e.g. 50,000 tokens (Press Enter to add next)`}
                />
                <button
                  type="button"
                  disabled={isFormLoading}
                  onClick={() => handleRemoveFeature(idx)}
                  className="p-1.5 text-text-muted hover:text-state-danger transition-colors cursor-pointer rounded-4 hover:bg-surface-primary"
                  title="Remove feature"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="flex justify-end gap-2.5 pt-3 border-t border-border-default">
          <button
            type="button"
            disabled={isFormLoading}
            onClick={onClose}
            className="h-9 px-3.5 rounded-8 border border-border-default bg-surface-card hover:bg-surface-primary text-[13px] font-medium text-text-dark transition-colors cursor-pointer disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={isFormLoading}
            className="h-9 px-4 rounded-8 btn-gradient-black text-[13px] font-semibold transition-all cursor-pointer flex items-center gap-1.5 disabled:opacity-50"
          >
            <span>{editingPlan ? "Save Changes" : "Create Plan"}</span>
          </button>
        </div>
      </form>
    </Modal>
  );
};

export default SubscriptionFormModal;
