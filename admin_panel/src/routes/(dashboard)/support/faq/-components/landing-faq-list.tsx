import { useState, useMemo } from "react";
import { Modal, Skeleton, Loader, Switch } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  Globe,
  Loader2,
  Minus,
  Pencil,
  Plus,
  Search,
  Trash2,
  CheckCircle2,
  EyeOff,
} from "lucide-react";

import {
  useLandingFaqs,
  useCreateLandingFaq,
  useUpdateLandingFaq,
  useDeleteLandingFaq,
} from "@/hooks/api/useFaqApi";
import type { LandingFAQItem } from "@/api/faqApi";

type StatusFilter = "all" | "active" | "inactive";

const LandingFaqList = () => {
  const { data: landingFaqsData, isLoading } = useLandingFaqs({ limit: 100 });
  const createMutation = useCreateLandingFaq();
  const updateMutation = useUpdateLandingFaq();
  const deleteMutation = useDeleteLandingFaq();

  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [openItems, setOpenItems] = useState<Record<string, boolean>>({});

  // Modals state
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [newQuestion, setNewQuestion] = useState("");
  const [newAnswer, setNewAnswer] = useState("");
  const [newIsActive, setNewIsActive] = useState(true);

  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [editingFaq, setEditingFaq] = useState<LandingFAQItem | null>(null);
  const [editQuestion, setEditQuestion] = useState("");
  const [editAnswer, setEditAnswer] = useState("");
  const [editIsActive, setEditIsActive] = useState(true);

  const [faqToDelete, setFaqToDelete] = useState<LandingFAQItem | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [togglingId, setTogglingId] = useState<string | null>(null);

  const rawList: LandingFAQItem[] = useMemo(() => {
    return landingFaqsData?.data || [];
  }, [landingFaqsData]);

  const activeCount = useMemo(() => rawList.filter((f) => f.is_active).length, [rawList]);
  const inactiveCount = useMemo(() => rawList.filter((f) => !f.is_active).length, [rawList]);

  // Filtered List
  const filteredFaqs = useMemo(() => {
    return rawList.filter((item) => {
      if (statusFilter === "active" && !item.is_active) return false;
      if (statusFilter === "inactive" && item.is_active) return false;

      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        return (
          item.question.toLowerCase().includes(q) ||
          item.answer.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [rawList, statusFilter, searchQuery]);

  const toggleItem = (id: string) => {
    setOpenItems((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  const handleOpenAdd = () => {
    setNewQuestion("");
    setNewAnswer("");
    setNewIsActive(true);
    setIsAddModalOpen(true);
  };

  const handleCreateLandingFaq = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newQuestion.trim() || !newAnswer.trim()) {
      notifications.show({
        title: "Validation Error",
        message: "Please fill in both the question and answer.",
        color: "red",
      });
      return;
    }

    try {
      const created = await createMutation.mutateAsync({
        question: newQuestion.trim(),
        answer: newAnswer.trim(),
        is_active: newIsActive,
      });

      setOpenItems((prev) => ({ ...prev, [created.id]: true }));
      notifications.show({
        title: "Landing FAQ Created",
        message: "New Landing FAQ published successfully.",
        color: "green",
      });

      setIsAddModalOpen(false);
      setNewQuestion("");
      setNewAnswer("");
    } catch (err: unknown) {
      notifications.show({
        title: "Creation Failed",
        message: err instanceof Error ? err.message : "Failed to create Landing FAQ.",
        color: "red",
      });
    }
  };

  const handleOpenEdit = (e: React.MouseEvent | React.KeyboardEvent, item: LandingFAQItem) => {
    e.stopPropagation();
    setEditingFaq(item);
    setEditQuestion(item.question);
    setEditAnswer(item.answer);
    setEditIsActive(item.is_active);
    setIsEditModalOpen(true);
  };

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingFaq || !editQuestion.trim() || !editAnswer.trim()) return;

    try {
      await updateMutation.mutateAsync({
        id: editingFaq.id,
        payload: {
          question: editQuestion.trim(),
          answer: editAnswer.trim(),
          is_active: editIsActive,
        },
      });

      notifications.show({
        title: "Landing FAQ Updated",
        message: "Question and answer updated successfully.",
        color: "green",
      });

      setIsEditModalOpen(false);
      setEditingFaq(null);
    } catch (err: unknown) {
      notifications.show({
        title: "Update Failed",
        message: err instanceof Error ? err.message : "Failed to update Landing FAQ.",
        color: "red",
      });
    }
  };

  const handleToggleActive = async (e: React.MouseEvent, item: LandingFAQItem) => {
    e.stopPropagation();
    setTogglingId(item.id);
    try {
      const updatedStatus = !item.is_active;
      await updateMutation.mutateAsync({
        id: item.id,
        payload: {
          is_active: updatedStatus,
        },
      });

      notifications.show({
        title: updatedStatus ? "Published to Landing" : "Hidden from Landing",
        message: updatedStatus
          ? "FAQ is now visible on the public landing page."
          : "FAQ is hidden from the landing page.",
        color: updatedStatus ? "green" : "gray",
        autoClose: 2500,
      });
    } catch (err: unknown) {
      notifications.show({
        title: "Status Update Failed",
        message: err instanceof Error ? err.message : "Failed to update status.",
        color: "red",
      });
    } finally {
      setTogglingId(null);
    }
  };

  const handleDelete = (e: React.MouseEvent | React.KeyboardEvent, item: LandingFAQItem) => {
    e.stopPropagation();
    setFaqToDelete(item);
  };

  const handleConfirmDelete = async () => {
    if (!faqToDelete) return;
    setIsDeleting(true);
    try {
      await deleteMutation.mutateAsync(faqToDelete.id);
      notifications.show({
        title: "Landing FAQ Deleted",
        message: `"${faqToDelete.question}" has been removed.`,
        color: "red",
        autoClose: 3000,
      });
      setFaqToDelete(null);
    } catch (err: unknown) {
      notifications.show({
        title: "Delete Failed",
        message: err instanceof Error ? err.message : "Failed to delete landing question.",
        color: "red",
      });
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Landing Banner & Distinct Header */}
      <div className="p-4 sm:p-5 rounded-16 border border-border-default bg-surface-card relative overflow-hidden shadow-2xs">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 relative z-10">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/10 text-emerald-600 border border-emerald-500/20">
                <Globe size={12} className="animate-pulse" />
                <span>Public Landing Website</span>
              </span>
              <span className="text-[11px] text-text-muted font-medium">
                punkai.io FAQ Section
              </span>
            </div>
            <h2 className="text-xl font-bold text-text-dark tracking-tight">
              Landing Page FAQs
            </h2>
            <p className="text-xs text-text-muted leading-relaxed max-w-xl">
              Manage the public questions displayed to visitors and potential customers on the marketing homepage. These FAQs are independent of support categories.
            </p>
          </div>

          <button
            type="button"
            onClick={handleOpenAdd}
            className="px-4 py-2.5 rounded-8 btn-gradient-black text-xs font-semibold cursor-pointer flex items-center justify-center gap-2 shrink-0 shadow-xs hover:opacity-95 transition-opacity"
          >
            <Plus size={15} strokeWidth={2.2} />
            <span>Add Landing FAQ</span>
          </button>
        </div>
      </div>

      {/* Pill Search Input */}
      <div
        className="w-full h-11 px-4 rounded-full border border-border-default bg-surface-card flex items-center gap-3 transition-colors shadow-2xs hover:border-text-muted/40 focus-within:border-text-dark"
        style={{ borderRadius: "9999px" }}
      >
        <Search size={16} className="text-text-muted shrink-0 pointer-events-none" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search landing questions & answers..."
          className="w-full bg-transparent text-[13px] text-text-dark placeholder:text-text-muted focus:outline-none border-none p-0"
        />
      </div>

      {/* Status Filter Pills */}
      <div className="flex items-center gap-2 overflow-x-auto custom-scrollbar pb-1">
        <button
          type="button"
          onClick={() => setStatusFilter("all")}
          className={`px-3.5 py-1.5 rounded-full text-xs font-medium transition-all cursor-pointer shrink-0 border flex items-center gap-1.5 ${
            statusFilter === "all"
              ? "btn-gradient-black border-transparent shadow-2xs font-semibold"
              : "bg-surface-card text-text-muted border-border-default hover:text-text-dark hover:border-text-muted/40"
          }`}
          style={{ borderRadius: "9999px" }}
        >
          <span>All Landing FAQs</span>
          <span className="text-[11px] opacity-75">{rawList.length}</span>
        </button>

        <button
          type="button"
          onClick={() => setStatusFilter("active")}
          className={`px-3.5 py-1.5 rounded-full text-xs font-medium transition-all cursor-pointer shrink-0 border flex items-center gap-1.5 ${
            statusFilter === "active"
              ? "btn-gradient-black border-transparent shadow-2xs font-semibold"
              : "bg-surface-card text-text-muted border-border-default hover:text-text-dark hover:border-text-muted/40"
          }`}
          style={{ borderRadius: "9999px" }}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
          <span>Live on Landing</span>
          <span className="text-[11px] opacity-75">{activeCount}</span>
        </button>

        <button
          type="button"
          onClick={() => setStatusFilter("inactive")}
          className={`px-3.5 py-1.5 rounded-full text-xs font-medium transition-all cursor-pointer shrink-0 border flex items-center gap-1.5 ${
            statusFilter === "inactive"
              ? "btn-gradient-black border-transparent shadow-2xs font-semibold"
              : "bg-surface-card text-text-muted border-border-default hover:text-text-dark hover:border-text-muted/40"
          }`}
          style={{ borderRadius: "9999px" }}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
          <span>Draft / Hidden</span>
          <span className="text-[11px] opacity-75">{inactiveCount}</span>
        </button>
      </div>

      {/* Accordion Questions List */}
      <div className="space-y-3">
        {isLoading && rawList.length === 0 ? (
          <div className="space-y-3">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="p-4 rounded-12 border border-border-default bg-surface-card space-y-3">
                <Skeleton height={20} width="60%" radius="sm" />
                <div className="space-y-1.5">
                  <Skeleton height={14} radius="sm" />
                  <Skeleton height={14} width="85%" radius="sm" />
                </div>
              </div>
            ))}
          </div>
        ) : filteredFaqs.length === 0 ? (
          <div className="py-12 text-center rounded-12 border border-border-default bg-surface-card space-y-3">
            <div className="w-10 h-10 rounded-full bg-surface-primary flex items-center justify-center mx-auto text-text-muted">
              <Globe size={20} />
            </div>
            <div>
              <p className="text-sm font-semibold text-text-dark">
                No Landing FAQs Found
              </p>
              <p className="text-xs text-text-muted mt-0.5">
                {searchQuery.trim()
                  ? "Try searching with different keywords."
                  : "Get started by adding your first public landing page question."}
              </p>
            </div>
            {!searchQuery.trim() && (
              <button
                type="button"
                onClick={handleOpenAdd}
                className="mt-2 inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-8 btn-gradient-black text-xs font-semibold cursor-pointer"
              >
                <Plus size={13} strokeWidth={2.2} />
                <span>Add Landing FAQ</span>
              </button>
            )}
          </div>
        ) : (
          filteredFaqs.map((item, index) => {
            const isOpen = !!openItems[item.id];
            const isToggling = togglingId === item.id;

            return (
              <div
                key={item.id}
                className={`rounded-12 border transition-all duration-150 overflow-hidden shadow-2xs ${
                  item.is_active
                    ? "border-border-default bg-surface-card hover:border-text-muted/40"
                    : "border-dashed border-border-default/80 bg-surface-primary/60 opacity-80"
                }`}
              >
                <button
                  type="button"
                  onClick={() => toggleItem(item.id)}
                  className="w-full px-4 py-3.5 flex items-center justify-between gap-4 text-left cursor-pointer select-none"
                >
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <span className="text-xs font-semibold text-text-muted w-5 shrink-0">
                      #{index + 1}
                    </span>

                    <div className="flex flex-col sm:flex-row sm:items-center gap-1.5 sm:gap-2.5 flex-1 min-w-0">
                      <span
                        className={`text-[13.5px] leading-snug transition-colors truncate ${
                          isOpen
                            ? "font-bold text-text-dark"
                            : "font-medium text-text-dark"
                        }`}
                      >
                        {item.question}
                      </span>

                      {/* Status Badge */}
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold shrink-0 ${
                          item.is_active
                            ? "bg-emerald-500/10 text-emerald-600 border border-emerald-500/20"
                            : "bg-amber-500/10 text-amber-600 border border-amber-500/20"
                        }`}
                      >
                        {item.is_active ? (
                          <>
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                            <span>Live</span>
                          </>
                        ) : (
                          <>
                            <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                            <span>Hidden</span>
                          </>
                        )}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {/* Toggle Active Switch / Button */}
                    <button
                      type="button"
                      disabled={isToggling}
                      onClick={(e) => handleToggleActive(e, item)}
                      className={`px-2 py-1 rounded-6 text-[11px] font-medium border transition-colors cursor-pointer flex items-center gap-1 ${
                        item.is_active
                          ? "border-border-default text-text-muted hover:text-amber-600 hover:border-amber-500/30"
                          : "border-emerald-500/30 text-emerald-600 bg-emerald-500/5 hover:bg-emerald-500/10"
                      }`}
                      title={item.is_active ? "Click to hide from landing page" : "Click to publish on landing page"}
                    >
                      {isToggling ? (
                        <Loader2 size={11} className="animate-spin" />
                      ) : item.is_active ? (
                        <>
                          <EyeOff size={11} />
                          <span className="hidden sm:inline">Hide</span>
                        </>
                      ) : (
                        <>
                          <CheckCircle2 size={11} />
                          <span className="hidden sm:inline">Publish</span>
                        </>
                      )}
                    </button>

                    {/* Edit Landing Question */}
                    <span
                      role="button"
                      tabIndex={0}
                      onClick={(e) => handleOpenEdit(e, item)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          handleOpenEdit(e, item);
                        }
                      }}
                      className="p-1.5 rounded-6 hover:bg-surface-primary text-text-muted hover:text-text-dark transition-colors cursor-pointer"
                      title="Edit landing question"
                      aria-label="Edit landing question"
                    >
                      <Pencil size={13} />
                    </span>

                    {/* Delete Landing Question */}
                    <span
                      role="button"
                      tabIndex={0}
                      onClick={(e) => handleDelete(e, item)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          handleDelete(e, item);
                        }
                      }}
                      className="p-1.5 rounded-6 hover:bg-red-50 text-text-muted hover:text-[#D80027] transition-colors cursor-pointer"
                      title="Delete landing question"
                      aria-label="Delete landing question"
                    >
                      <Trash2 size={13} />
                    </span>

                    <div className="text-text-muted shrink-0 flex items-center justify-center w-5 h-5 ml-0.5">
                      {isOpen ? (
                        <Minus size={15} strokeWidth={2} />
                      ) : (
                        <Plus size={15} strokeWidth={2} />
                      )}
                    </div>
                  </div>
                </button>

                {isOpen && (
                  <div className="px-4 pb-4 pt-1 border-t border-border-default/60">
                    <p className="text-[13px] text-text-muted leading-relaxed whitespace-pre-wrap">
                      {item.answer}
                    </p>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Add Landing FAQ Modal */}
      <Modal
        opened={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        title={
          <div className="flex items-center gap-2">
            <Globe size={18} className="text-text-dark" />
            <span className="font-bold text-sm text-text-dark">
              Add Landing Page FAQ
            </span>
          </div>
        }
        centered
        radius="md"
        padding="lg"
      >
        <form onSubmit={handleCreateLandingFaq} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-text-dark mb-1">
              Question Title
            </label>
            <input
              type="text"
              required
              placeholder="e.g. Can I connect multiple ad platforms simultaneously?"
              value={newQuestion}
              onChange={(e) => setNewQuestion(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-text-dark mb-1">
              Answer Content
            </label>
            <textarea
              rows={4}
              required
              placeholder="Provide a clear, engaging explanation for prospective landing page visitors..."
              value={newAnswer}
              onChange={(e) => setNewAnswer(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark resize-none"
            />
          </div>

          <div className="pt-1 flex items-center justify-between">
            <div className="space-y-0.5">
              <span className="text-xs font-semibold text-text-dark block">
                Publish Status
              </span>
              <span className="text-[11px] text-text-muted block">
                Make visible on the landing page immediately
              </span>
            </div>
            <Switch
              checked={newIsActive}
              onChange={(e) => setNewIsActive(e.currentTarget.checked)}
              color="dark"
              size="sm"
            />
          </div>

          <div className="pt-2 flex items-center justify-end gap-2 border-t border-border-default">
            <button
              type="button"
              onClick={() => setIsAddModalOpen(false)}
              className="px-4 py-2 rounded-8 border border-border-default text-xs font-semibold text-text-muted hover:text-text-dark hover:bg-surface-primary transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="px-4 py-2 rounded-8 btn-gradient-black text-xs font-semibold cursor-pointer flex items-center gap-1.5"
            >
              {createMutation.isPending && <Loader size={12} color="white" />}
              <span>Publish to Landing</span>
            </button>
          </div>
        </form>
      </Modal>

      {/* Edit Landing FAQ Modal */}
      <Modal
        opened={isEditModalOpen}
        onClose={() => setIsEditModalOpen(false)}
        title={
          <div className="flex items-center gap-2">
            <Pencil size={17} className="text-text-dark" />
            <span className="font-bold text-sm text-text-dark">
              Edit Landing Page FAQ
            </span>
          </div>
        }
        centered
        radius="md"
        padding="lg"
      >
        <form onSubmit={handleSaveEdit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-text-dark mb-1">
              Question Title
            </label>
            <input
              type="text"
              required
              value={editQuestion}
              onChange={(e) => setEditQuestion(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-text-dark mb-1">
              Answer Content
            </label>
            <textarea
              rows={4}
              required
              value={editAnswer}
              onChange={(e) => setEditAnswer(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark resize-none"
            />
          </div>

          <div className="pt-1 flex items-center justify-between">
            <div className="space-y-0.5">
              <span className="text-xs font-semibold text-text-dark block">
                Live on Landing Page
              </span>
              <span className="text-[11px] text-text-muted block">
                Visible to public visitors on punkai.io
              </span>
            </div>
            <Switch
              checked={editIsActive}
              onChange={(e) => setEditIsActive(e.currentTarget.checked)}
              color="dark"
              size="sm"
            />
          </div>

          <div className="pt-2 flex items-center justify-end gap-2 border-t border-border-default">
            <button
              type="button"
              onClick={() => setIsEditModalOpen(false)}
              className="px-4 py-2 rounded-8 border border-border-default text-xs font-semibold text-text-muted hover:text-text-dark hover:bg-surface-primary transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={updateMutation.isPending}
              className="px-4 py-2 rounded-8 btn-gradient-black text-xs font-semibold cursor-pointer flex items-center gap-1.5"
            >
              {updateMutation.isPending && <Loader size={12} color="white" />}
              <span>Save Changes</span>
            </button>
          </div>
        </form>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal
        opened={!!faqToDelete}
        onClose={() => {
          if (!isDeleting) setFaqToDelete(null);
        }}
        title={
          <div className="flex items-center gap-2 text-text-dark font-bold text-sm">
            <Trash2 size={16} className="text-[#D80027]" />
            <span>Delete Landing FAQ</span>
          </div>
        }
        centered
        radius="md"
        size="sm"
        closeOnClickOutside={!isDeleting}
        closeOnEscape={!isDeleting}
        withCloseButton={!isDeleting}
      >
        <div className="relative space-y-4 pt-1">
          {isDeleting && (
            <div className="absolute inset-0 -m-4 bg-surface-card/90 backdrop-blur-xs z-50 flex flex-col items-center justify-center gap-2 rounded-8">
              <Loader2 size={24} className="animate-spin text-[#D80027]" />
              <span className="text-xs font-semibold text-text-dark">Deleting question...</span>
            </div>
          )}

          <p className="text-xs text-text-muted leading-relaxed">
            Are you sure you want to delete{" "}
            <span className="text-text-dark font-semibold">
              &quot;{faqToDelete?.question}&quot;
            </span>
            ? This will remove the question from the landing page.
          </p>

          <div className="pt-2 flex items-center justify-end gap-2 border-t border-border-default">
            <button
              type="button"
              disabled={isDeleting}
              onClick={() => setFaqToDelete(null)}
              className="px-4 py-2 rounded-8 border border-border-default text-xs font-semibold text-text-muted hover:text-text-dark hover:bg-surface-primary transition-colors cursor-pointer disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={isDeleting}
              onClick={handleConfirmDelete}
              className="px-4 py-2 rounded-8 bg-[#D80027] hover:bg-[#b50020] text-white text-xs font-semibold cursor-pointer flex items-center gap-1.5 transition-colors disabled:opacity-50"
            >
              {isDeleting ? (
                <>
                  <Loader2 size={13} className="animate-spin" />
                  <span>Deleting...</span>
                </>
              ) : (
                <span>Delete Question</span>
              )}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
};

export default LandingFaqList;
