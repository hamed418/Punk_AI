import React, { useState } from "react";
import { Plus, CheckCircle2, AlertCircle } from "lucide-react";
import {
  usePlans,
  useCreatePlan,
  useUpdatePlan,
  useDeletePlan,
} from "@/hooks/api/useSubscriptionApi";
import type { Plan } from "@/types/subscription";
import DeleteConfirmationModal from "@/components/shared/DeleteConfirmationModal";
import OverviewCard from "./overview-card";
import SubscriptionPlanList from "./subscription-plan-list";
import SubscriptionFormModal from "./subscription-form-modal";

const Subscription: React.FC = () => {
  const { data: plans = [], isLoading, isError, error: queryError } = usePlans();
  const createPlanMutation = useCreatePlan();
  const updatePlanMutation = useUpdatePlan();
  const deletePlanMutation = useDeletePlan();

  // Modal / Drawer state
  const [isFormOpen, setIsFormOpen] = useState<boolean>(false);
  const [editingPlan, setEditingPlan] = useState<Plan | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  // Delete state
  const [deletingPlan, setDeletingPlan] = useState<Plan | null>(null);

  // Success toast message
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const showSuccess = (msg: string) => {
    setSuccessMessage(msg);
    setTimeout(() => {
      setSuccessMessage(null);
    }, 4000);
  };

  const openCreateForm = () => {
    setEditingPlan(null);
    setIsFormOpen(true);
  };

  const openEditForm = (plan: Plan) => {
    setEditingPlan(plan);
    setIsFormOpen(true);
  };

  const handleFormSubmit = async (data: any, submitStatus?: "draft" | "published") => {
    try {
      if (editingPlan) {
        await updatePlanMutation.mutateAsync({
          id: editingPlan.id,
          data,
        });
        showSuccess("Plan updated successfully.");
      } else {
        await createPlanMutation.mutateAsync(data);
        showSuccess("New plan created successfully.");
      }
      setIsFormOpen(false);
    } catch (err: any) {
      console.error(err);
      setFormError(err?.message || "Error occurred while saving the plan.");
    }
  };

  const handleDeleteConfirm = async () => {
    if (!deletingPlan) return;
    try {
      await deletePlanMutation.mutateAsync(deletingPlan.id);
      showSuccess("Plan deleted successfully.");
      setDeletingPlan(null);
    } catch (err: any) {
      console.error(err);
      setFormError(err?.message || "Failed to delete the plan.");
    }
  };

  const isFormLoading = createPlanMutation.isPending || updatePlanMutation.isPending;

  return (
    <div className="flex flex-col gap-6">
      {/* Toast Notification */}
      {successMessage && (
        <div className="fixed bottom-5 right-5 z-50 flex items-center gap-2.5 bg-surface-card border border-border-default text-text-dark px-4 py-3 rounded-10 shadow-lg animate-slide-in">
          <CheckCircle2 size={16} className="text-highlight-cyan" />
          <span className="text-[13px] font-medium">{successMessage}</span>
        </div>
      )}

      {/* Top Overview Section */}
      <div className="flex flex-col gap-3.5">
        <div className="flex items-center justify-between">
          <h2 className="text-[15px] font-bold text-text-dark">Overview</h2>
          <button
            type="button"
            onClick={openCreateForm}
            className="btn-gradient-black text-[13px] font-medium transition-all cursor-pointer flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-8"
          >
            <Plus size={14} className="text-white" />
            <span>New Plan</span>
          </button>
        </div>

        <OverviewCard />
      </div>

      {/* Error state */}
      {isError && (
        <div className="flex items-center gap-2.5 p-3 rounded-10 bg-state-danger/10 border border-state-danger/20 text-state-danger text-[13px]">
          <AlertCircle size={16} className="shrink-0" />
          <span>{(queryError as any)?.message || "Failed to load subscription plans from backend."}</span>
        </div>
      )}

      {/* Plans Section */}
      <SubscriptionPlanList
        plans={plans}
        isLoading={isLoading}
        openCreateForm={openCreateForm}
        openEditForm={openEditForm}
        onDeleteRequest={setDeletingPlan}
      />

      {/* CREATE / EDIT MODAL */}
      <SubscriptionFormModal
        isOpen={isFormOpen}
        onClose={() => setIsFormOpen(false)}
        editingPlan={editingPlan}
        onSubmit={handleFormSubmit}
        isFormLoading={isFormLoading}
        formError={formError}
        setFormError={setFormError}
      />

      {/* DELETE CONFIRMATION MODAL */}
      <DeleteConfirmationModal
        isOpen={!!deletingPlan}
        onClose={() => setDeletingPlan(null)}
        onConfirm={handleDeleteConfirm}
        title="Delete Plan"
        message={`Are you sure you want to delete the plan "${deletingPlan?.name || "Selected Plan"}"? Users subscribed will retain their tokens until renewal.`}
        isLoading={deletePlanMutation.isPending}
      />
    </div>
  );
};

export default Subscription;
