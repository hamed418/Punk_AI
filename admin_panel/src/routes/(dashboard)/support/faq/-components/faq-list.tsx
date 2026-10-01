import { useState, useMemo } from "react";
import { Modal, Skeleton, Loader } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { Loader2, Minus, Pencil, Plus, PlusCircle, Search, Trash2 } from "lucide-react";

import { DESIGN_TOKENS } from "@/constant/design-system";
import {
  useFaqCategories,
  useFaqs,
  useCreateFaqCategory,
  useCreateFaq,
  useUpdateFaq,
  useDeleteFaq,
} from "@/hooks/api/useFaqApi";
import type { FAQCategoryItem, FAQItem } from "@/api/faqApi";


export interface FaqQuestion {
  id: string;
  category_id: string;
  question: string;
  answer: string;
}

export interface FaqCategoryGroup {
  id: string;
  title: string;
  dotColor: string;
  pillLabel: string;
  count: number;
  questions: FaqQuestion[];
}

const PRESET_DOT_COLORS = [
  { label: "Orange", value: DESIGN_TOKENS.colors.highlightOrange },
  { label: "Pink", value: DESIGN_TOKENS.colors.highlightPink },
  { label: "Cyan", value: DESIGN_TOKENS.colors.highlightCyan },
  { label: "Teal", value: DESIGN_TOKENS.colors.highlightTeal },
  { label: "Purple", value: DESIGN_TOKENS.colors.graphMarker },
  { label: "Green", value: DESIGN_TOKENS.colors.stateSuccess },
];

const fallbackColors = [
  DESIGN_TOKENS.colors.highlightOrange,
  DESIGN_TOKENS.colors.highlightPink,
  DESIGN_TOKENS.colors.highlightCyan,
  DESIGN_TOKENS.colors.graphMarker,
  DESIGN_TOKENS.colors.highlightTeal,
  DESIGN_TOKENS.colors.stateSuccess,
];

const FaqList = () => {
  const { data: categoriesData, isLoading: isCategoriesLoading } = useFaqCategories();
  const { data: faqsData, isLoading: isFaqsLoading } = useFaqs({ limit: 100 });

  const createCategoryMutation = useCreateFaqCategory();
  const createFaqMutation = useCreateFaq();
  const updateFaqMutation = useUpdateFaq();
  const deleteFaqMutation = useDeleteFaq();

  const [activeFilter, setActiveFilter] = useState<string>("popular");
  const [searchQuery, setSearchQuery] = useState("");
  const [openItems, setOpenItems] = useState<Record<string, boolean>>({});

  // Delete Question Modal State
  const [questionToDelete, setQuestionToDelete] = useState<FaqQuestion | null>(null);
  const [isDeletingQuestion, setIsDeletingQuestion] = useState(false);

  // Add Category Modal State
  const [isAddCategoryModalOpen, setIsAddCategoryModalOpen] = useState(false);
  const [newCategoryTitle, setNewCategoryTitle] = useState("");
  const [newCategoryColor, setNewCategoryColor] = useState<string>(
    DESIGN_TOKENS.colors.highlightOrange
  );
  const [firstQuestion, setFirstQuestion] = useState("");
  const [firstAnswer, setFirstAnswer] = useState("");

  // Add Question Modal State
  const [isAddQuestionModalOpen, setIsAddQuestionModalOpen] = useState(false);
  const [targetCategoryId, setTargetCategoryId] = useState<string>("");
  const [newQuestionTitle, setNewQuestionTitle] = useState("");
  const [newQuestionAnswer, setNewQuestionAnswer] = useState("");

  // Edit Question Modal State
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [editingQuestionId, setEditingQuestionId] = useState<string | null>(null);
  const [editCategoryId, setEditCategoryId] = useState<string>("");
  const [editQuestionTitle, setEditQuestionTitle] = useState("");
  const [editQuestionAnswer, setEditQuestionAnswer] = useState("");

  // Build combined FAQ groups dynamically from backend
  const faqCategories = useMemo<FaqCategoryGroup[]>(() => {
    const rawCategories: FAQCategoryItem[] = categoriesData?.data || [];
    const rawFaqs: FAQItem[] = faqsData?.data || [];

    if (rawCategories.length === 0) {
      return [];
    }

    return rawCategories.map((cat, idx) => {
      const catQuestions = rawFaqs
        .filter((f) => f.category_id === cat.id)
        .map((f) => ({
          id: f.id,
          category_id: f.category_id,
          question: f.question,
          answer: f.answer,
        }));

      return {
        id: cat.id,
        title: cat.name.toUpperCase(),
        dotColor: fallbackColors[idx % fallbackColors.length],
        pillLabel: cat.name,
        count: catQuestions.length,
        questions: catQuestions,
      };
    });
  }, [categoriesData, faqsData]);


  const toggleItem = (id: string) => {
    setOpenItems((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  const handleOpenEdit = (e: React.MouseEvent | React.KeyboardEvent, item: FaqQuestion) => {
    e.stopPropagation();
    setEditingQuestionId(item.id);
    setEditCategoryId(item.category_id);
    setEditQuestionTitle(item.question);
    setEditQuestionAnswer(item.answer);
    setIsEditModalOpen(true);
  };

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingQuestionId || !editQuestionTitle.trim()) return;

    try {
      await updateFaqMutation.mutateAsync({
        id: editingQuestionId,
        payload: {
          category_id: editCategoryId || undefined,
          question: editQuestionTitle.trim(),
          answer: editQuestionAnswer.trim(),
        },
      });

      notifications.show({
        title: "FAQ Updated",
        message: "Question and answer updated successfully.",
        color: "green",
      });
      setIsEditModalOpen(false);
      setEditingQuestionId(null);
    } catch (err: unknown) {
      notifications.show({
        title: "Update Failed",
        message: err instanceof Error ? err.message : "Failed to update FAQ question.",
        color: "red",
      });
    }
  };

  const handleDeleteQuestion = (
    e: React.MouseEvent | React.KeyboardEvent,
    question: FaqQuestion
  ) => {
    e.stopPropagation();
    setQuestionToDelete(question);
  };

  const handleConfirmDelete = async () => {
    if (!questionToDelete) return;
    setIsDeletingQuestion(true);
    try {
      await deleteFaqMutation.mutateAsync(questionToDelete.id);
      notifications.show({
        title: "FAQ Question Deleted",
        message: `"${questionToDelete.question}" has been removed.`,
        color: "red",
        autoClose: 3000,
      });
      setQuestionToDelete(null);
    } catch (err: unknown) {
      notifications.show({
        title: "Delete Failed",
        message: err instanceof Error ? err.message : "Failed to delete question.",
        color: "red",
      });
    } finally {
      setIsDeletingQuestion(false);
    }
  };


  const handleOpenAddQuestionModal = (categoryId?: string) => {
    setTargetCategoryId(categoryId || faqCategories[0]?.id || "");
    setNewQuestionTitle("");
    setNewQuestionAnswer("");
    setIsAddQuestionModalOpen(true);
  };

  const handleCreateCategory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCategoryTitle.trim()) return;

    try {
      const createdCategory = await createCategoryMutation.mutateAsync({
        name: newCategoryTitle.trim(),
        type: "both",
        is_active: true,
      });

      if (firstQuestion.trim() && firstAnswer.trim() && createdCategory.id) {
        await createFaqMutation.mutateAsync({
          category_id: createdCategory.id,
          question: firstQuestion.trim(),
          answer: firstAnswer.trim(),
          is_active: true,
        });
      }

      notifications.show({
        title: "Category Created",
        message: `Category "${newCategoryTitle}" created successfully.`,
        color: "green",
      });

      setActiveFilter(createdCategory.id);
      setNewCategoryTitle("");
      setFirstQuestion("");
      setFirstAnswer("");
      setIsAddCategoryModalOpen(false);
    } catch (err: unknown) {
      notifications.show({
        title: "Creation Failed",
        message: err instanceof Error ? err.message : "Failed to create category.",
        color: "red",
      });
    }
  };

  const handleCreateQuestion = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newQuestionTitle.trim() || !newQuestionAnswer.trim() || !targetCategoryId) {
      notifications.show({
        title: "Validation Error",
        message: "Please select a category and fill in all fields.",
        color: "red",
      });
      return;
    }

    try {
      const created = await createFaqMutation.mutateAsync({
        category_id: targetCategoryId,
        question: newQuestionTitle.trim(),
        answer: newQuestionAnswer.trim(),
        is_active: true,
      });

      setOpenItems((prev) => ({ ...prev, [created.id]: true }));
      notifications.show({
        title: "Question Published",
        message: "New FAQ question published successfully.",
        color: "green",
      });

      setNewQuestionTitle("");
      setNewQuestionAnswer("");
      setIsAddQuestionModalOpen(false);
    } catch (err: unknown) {
      notifications.show({
        title: "Creation Failed",
        message: err instanceof Error ? err.message : "Failed to publish question.",
        color: "red",
      });
    }
  };

  // Filter groups based on search & active filter pill
  const filteredGroups = faqCategories
    .map((group) => {
      if (
        activeFilter !== "popular" &&
        activeFilter !== "all" &&
        group.id !== activeFilter
      ) {
        return null;
      }

      const matchingQuestions = group.questions.filter((q) => {
        if (!searchQuery.trim()) return true;
        const query = searchQuery.toLowerCase();
        return (
          q.question.toLowerCase().includes(query) ||
          q.answer.toLowerCase().includes(query) ||
          group.title.toLowerCase().includes(query)
        );
      });

      if (matchingQuestions.length === 0 && searchQuery.trim()) return null;

      return {
        ...group,
        questions: matchingQuestions,
      };
    })
    .filter(Boolean) as FaqCategoryGroup[];

  const isInitialLoading = (isCategoriesLoading || isFaqsLoading) && faqCategories.length === 0;

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Header with Title */}
      <div className="pt-2">
        <h1 className="text-2xl font-bold tracking-tight text-text-dark">
          Frequently asked
        </h1>
      </div>


      {/* Pill-shaped Full-width Search Input */}
      <div
        className="w-full h-11 px-4 rounded-full border border-border-default bg-surface-card flex items-center gap-3 transition-colors shadow-2xs hover:border-text-muted/40 focus-within:border-text-dark"
        style={{ borderRadius: "9999px" }}
      >
        <Search
          size={16}
          className="text-text-muted shrink-0 pointer-events-none"
        />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search these questions — tokens, billing, refunds..."
          className="w-full bg-transparent text-[13px] text-text-dark placeholder:text-text-muted focus:outline-none border-none p-0"
        />
      </div>

      {/* Category Filter Pills with Add Sign at right end */}
      <div className="flex items-center gap-2 overflow-x-auto custom-scrollbar pb-1">
        {/* Popular pill */}
        <button
          type="button"
          onClick={() => setActiveFilter("popular")}
          className={`px-3.5 py-1.5 rounded-full text-xs font-medium transition-all cursor-pointer shrink-0 border flex items-center gap-1.5 ${
            activeFilter === "popular"
              ? "btn-gradient-black border-transparent shadow-2xs font-semibold"
              : "bg-surface-card text-text-muted border-border-default hover:text-text-dark hover:border-text-muted/40"
          }`}
          style={{ borderRadius: "9999px" }}
        >
          <span>Popular</span>
          <span className="text-[11px] opacity-75">
            {faqCategories.reduce((sum, g) => sum + g.questions.length, 0)}
          </span>
        </button>

        {/* Dynamic Category Pills */}
        {faqCategories.map((group) => {
          const isActive = activeFilter === group.id;
          return (
            <button
              key={group.id}
              type="button"
              onClick={() => setActiveFilter(group.id)}
              className={`px-3.5 py-1.5 rounded-full text-xs font-medium transition-all cursor-pointer shrink-0 border flex items-center gap-1.5 ${
                isActive
                  ? "btn-gradient-black border-transparent shadow-2xs font-semibold"
                  : "bg-surface-card text-text-muted border-border-default hover:text-text-dark hover:border-text-muted/40"
              }`}
              style={{ borderRadius: "9999px" }}
            >
              <span>{group.pillLabel}</span>
              <span className="text-[11px] opacity-75">{group.count}</span>
            </button>
          );
        })}

        {/* Add Sign at the right end of Categories */}
        <button
          type="button"
          onClick={() => setIsAddCategoryModalOpen(true)}
          title="Add new category"
          aria-label="Add new category"
          className="h-7 w-7 rounded-full border border-dashed border-border-default hover:border-text-dark bg-surface-card hover:bg-surface-primary text-text-muted hover:text-text-dark transition-all cursor-pointer shrink-0 flex items-center justify-center shadow-2xs group"
          style={{ borderRadius: "9999px" }}
        >
          <Plus
            size={14}
            strokeWidth={2.2}
            className="group-hover:scale-110 transition-transform text-text-muted group-hover:text-text-dark"
          />
        </button>
      </div>

      {/* Grouped Category Sections */}
      <div className="space-y-6 pt-1">
        {isInitialLoading ? (
          <div className="space-y-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="p-4 rounded-12 border border-border-default bg-surface-card space-y-3">
                <Skeleton height={20} width="40%" radius="sm" />
                <div className="space-y-1.5">
                  <Skeleton height={14} radius="sm" />
                  <Skeleton height={14} width="80%" radius="sm" />
                </div>
              </div>
            ))}
          </div>
        ) : filteredGroups.length === 0 ? (
          <div className="py-12 text-center rounded-12 border border-border-default bg-surface-card">
            <p className="text-sm font-semibold text-text-dark">
              No matching questions found
            </p>
            <p className="text-xs text-text-muted mt-1">
              Try searching with different keywords or reset the category filter.
            </p>
          </div>
        ) : (
          <>
            {filteredGroups.map((group) => (
              <div key={group.id} className="space-y-2.5">
                {/* Category Header with Colored Dot, Divider, and Count */}
                <div className="flex items-center justify-between gap-3 px-1">
                  <div className="flex items-center gap-2">
                    <span
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{ backgroundColor: group.dotColor }}
                    />
                    <span className="text-[11px] font-bold tracking-wider text-text-muted uppercase">
                      {group.title}
                    </span>
                  </div>

                  <div className="flex-1 h-px bg-border-default mx-1" />

                  <span className="text-[11px] font-medium text-text-muted shrink-0">
                    {group.questions.length}
                  </span>
                </div>

                {/* Questions Accordion in Category */}
                <div className="space-y-2">
                  {group.questions.map((item) => {
                    const isOpen = !!openItems[item.id];
                    return (
                      <div
                        key={item.id}
                        className="rounded-12 border border-border-default bg-surface-card transition-all duration-150 overflow-hidden hover:border-text-muted/40 shadow-2xs"
                      >
                        <button
                          type="button"
                          onClick={() => toggleItem(item.id)}
                          className="w-full px-4 py-3.5 flex items-center justify-between gap-4 text-left cursor-pointer select-none"
                        >
                          <span
                            className={`text-[13.5px] leading-snug transition-colors ${
                              isOpen
                                ? "font-bold text-text-dark"
                                : "font-medium text-text-dark"
                            }`}
                          >
                            {item.question}
                          </span>

                          <div className="flex items-center gap-2 shrink-0">
                            {/* Edit Question */}
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
                              title="Edit question"
                              aria-label="Edit question"
                            >
                              <Pencil size={13} />
                            </span>

                            {/* Delete Question */}
                            <span
                              role="button"
                              tabIndex={0}
                              onClick={(e) => handleDeleteQuestion(e, item)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter" || e.key === " ") {
                                  handleDeleteQuestion(e, item);
                                }
                              }}
                              className="p-1.5 rounded-6 hover:bg-red-50 text-text-muted hover:text-[#D80027] transition-colors cursor-pointer"
                              title="Delete question"
                              aria-label="Delete question"
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
                          <div className="px-4 pb-4 pt-1 text-[13px] text-text-muted leading-relaxed">
                            {item.answer}
                          </div>
                        )}
                      </div>
                    );
                  })}

                  {/* When viewing a specific category filter, show the add question button for that category */}
                  {activeFilter !== "popular" && (
                    <button
                      type="button"
                      onClick={() => handleOpenAddQuestionModal(group.id)}
                      className="w-full py-2.5 px-4 rounded-12 border border-dashed border-border-default hover:border-text-dark bg-surface-card hover:bg-surface-primary text-text-muted hover:text-text-dark text-xs font-medium transition-all cursor-pointer flex items-center justify-center gap-1.5 shadow-2xs group"
                    >
                      <Plus
                        size={13}
                        strokeWidth={2.2}
                        className="group-hover:scale-110 transition-transform text-text-muted group-hover:text-text-dark"
                      />
                      <span>Add question to {group.pillLabel}</span>
                    </button>
                  )}
                </div>
              </div>
            ))}

            {/* In Popular section: Keep a single add button at the bottom with category selection */}
            {activeFilter === "popular" && (
              <button
                type="button"
                onClick={() => handleOpenAddQuestionModal()}
                className="w-full py-3 px-4 rounded-12 border border-dashed border-border-default hover:border-text-dark bg-surface-card hover:bg-surface-primary text-text-muted hover:text-text-dark text-xs font-medium transition-all cursor-pointer flex items-center justify-center gap-2 shadow-2xs group"
              >
                <Plus
                  size={14}
                  strokeWidth={2.2}
                  className="group-hover:scale-110 transition-transform text-text-muted group-hover:text-text-dark"
                />
                <span>Add Question & Answer Query</span>
              </button>
            )}
          </>
        )}
      </div>

      {/* Edit Question Modal */}
      <Modal
        opened={isEditModalOpen}
        onClose={() => setIsEditModalOpen(false)}
        title={
          <div className="flex items-center gap-2">
            <Pencil size={17} className="text-text-dark" />
            <span className="font-bold text-sm text-text-dark">
              Edit Question & Answer
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
              Category
            </label>
            <select
              value={editCategoryId}
              onChange={(e) => setEditCategoryId(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark"
            >
              {faqCategories.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.pillLabel}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold text-text-dark mb-1">
              Question Title
            </label>
            <input
              type="text"
              required
              value={editQuestionTitle}
              onChange={(e) => setEditQuestionTitle(e.target.value)}
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
              value={editQuestionAnswer}
              onChange={(e) => setEditQuestionAnswer(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark resize-none"
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
              disabled={updateFaqMutation.isPending}
              className="px-4 py-2 rounded-8 btn-gradient-black text-xs font-semibold cursor-pointer flex items-center gap-1.5"
            >
              {updateFaqMutation.isPending && <Loader size={12} color="white" />}
              <span>Save Changes</span>
            </button>
          </div>
        </form>
      </Modal>

      {/* Add New Category Modal */}
      <Modal
        opened={isAddCategoryModalOpen}
        onClose={() => setIsAddCategoryModalOpen(false)}
        title={
          <div className="flex items-center gap-2">
            <PlusCircle size={18} className="text-text-dark" />
            <span className="font-bold text-sm text-text-dark">
              Add New Category
            </span>
          </div>
        }
        centered
        radius="md"
        padding="lg"
      >
        <form onSubmit={handleCreateCategory} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-text-dark mb-1">
              Category Name
            </label>
            <input
              type="text"
              required
              placeholder="e.g. AI Creative Models, Security & API"
              value={newCategoryTitle}
              onChange={(e) => setNewCategoryTitle(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-text-dark mb-1.5">
              Accent Dot Color
            </label>
            <div className="flex items-center gap-2.5">
              {PRESET_DOT_COLORS.map((col) => (
                <button
                  key={col.value}
                  type="button"
                  onClick={() => setNewCategoryColor(col.value)}
                  className={`w-6 h-6 rounded-full transition-transform cursor-pointer border flex items-center justify-center ${
                    newCategoryColor === col.value
                      ? "scale-125 border-text-dark shadow-xs"
                      : "border-transparent opacity-70 hover:opacity-100"
                  }`}
                  style={{ backgroundColor: col.value }}
                  title={col.label}
                />
              ))}
            </div>
          </div>

          <div className="border-t border-border-default/70 pt-3 space-y-3">
            <span className="text-[11px] font-semibold text-text-muted uppercase tracking-wider block">
              First Question (Optional)
            </span>
            <div>
              <input
                type="text"
                placeholder="Question title..."
                value={firstQuestion}
                onChange={(e) => setFirstQuestion(e.target.value)}
                className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark"
              />
            </div>
            <div>
              <textarea
                rows={2}
                placeholder="Answer explanation..."
                value={firstAnswer}
                onChange={(e) => setFirstAnswer(e.target.value)}
                className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark resize-none"
              />
            </div>
          </div>

          <div className="pt-2 flex items-center justify-end gap-2 border-t border-border-default">
            <button
              type="button"
              onClick={() => setIsAddCategoryModalOpen(false)}
              className="px-4 py-2 rounded-8 border border-border-default text-xs font-semibold text-text-muted hover:text-text-dark hover:bg-surface-primary transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createCategoryMutation.isPending || createFaqMutation.isPending}
              className="px-4 py-2 rounded-8 btn-gradient-black text-xs font-semibold cursor-pointer flex items-center gap-1.5"
            >
              {(createCategoryMutation.isPending || createFaqMutation.isPending) && (
                <Loader size={12} color="white" />
              )}
              <span>Create Category</span>
            </button>
          </div>
        </form>
      </Modal>

      {/* Add New Question & Answer Modal */}
      <Modal
        opened={isAddQuestionModalOpen}
        onClose={() => setIsAddQuestionModalOpen(false)}
        title={
          <div className="flex items-center gap-2">
            <PlusCircle size={18} className="text-text-dark" />
            <span className="font-bold text-sm text-text-dark">
              Add Question & Answer Query
            </span>
          </div>
        }
        centered
        radius="md"
        padding="lg"
      >
        <form onSubmit={handleCreateQuestion} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-text-dark mb-1">
              Select Category
            </label>
            <select
              value={targetCategoryId}
              onChange={(e) => setTargetCategoryId(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark"
            >
              {faqCategories.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.pillLabel}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold text-text-dark mb-1">
              Question Title
            </label>
            <input
              type="text"
              required
              placeholder="e.g. How do I configure webhook notifications?"
              value={newQuestionTitle}
              onChange={(e) => setNewQuestionTitle(e.target.value)}
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
              placeholder="Provide the comprehensive answer or explanation..."
              value={newQuestionAnswer}
              onChange={(e) => setNewQuestionAnswer(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark resize-none"
            />
          </div>

          <div className="pt-2 flex items-center justify-end gap-2 border-t border-border-default">
            <button
              type="button"
              onClick={() => setIsAddQuestionModalOpen(false)}
              className="px-4 py-2 rounded-8 border border-border-default text-xs font-semibold text-text-muted hover:text-text-dark hover:bg-surface-primary transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createFaqMutation.isPending}
              className="px-4 py-2 rounded-8 btn-gradient-black text-xs font-semibold cursor-pointer flex items-center gap-1.5"
            >
              {createFaqMutation.isPending && <Loader size={12} color="white" />}
              <span>Publish Question</span>
            </button>
          </div>
        </form>
      </Modal>

      {/* Dedicated Delete Confirmation Modal */}
      <Modal
        opened={!!questionToDelete}
        onClose={() => {
          if (!isDeletingQuestion) setQuestionToDelete(null);
        }}
        title={
          <div className="flex items-center gap-2 text-text-dark font-bold text-sm">
            <Trash2 size={16} className="text-[#D80027]" />
            <span>Delete FAQ Question</span>
          </div>
        }
        centered
        radius="md"
        size="sm"
        closeOnClickOutside={!isDeletingQuestion}
        closeOnEscape={!isDeletingQuestion}
        withCloseButton={!isDeletingQuestion}
      >
        <div className="relative space-y-4 pt-1">
          {/* Centered Loading Overlay while deleting */}
          {isDeletingQuestion && (
            <div className="absolute inset-0 -m-4 bg-surface-card/90 backdrop-blur-xs z-50 flex flex-col items-center justify-center gap-2 rounded-8">
              <Loader2 size={24} className="animate-spin text-[#D80027]" />
              <span className="text-xs font-semibold text-text-dark">Deleting question...</span>
            </div>
          )}

          <p className="text-xs text-text-muted leading-relaxed">
            Are you sure you want to delete{" "}
            <span className="text-text-dark font-semibold">
              &quot;{questionToDelete?.question}&quot;
            </span>
            ? This action cannot be undone.
          </p>

          <div className="pt-2 flex items-center justify-end gap-2 border-t border-border-default">
            <button
              type="button"
              disabled={isDeletingQuestion}
              onClick={() => setQuestionToDelete(null)}
              className="px-4 py-2 rounded-8 border border-border-default text-xs font-semibold text-text-muted hover:text-text-dark hover:bg-surface-primary transition-colors cursor-pointer disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={isDeletingQuestion}
              onClick={handleConfirmDelete}
              className="px-4 py-2 rounded-8 bg-[#D80027] hover:bg-[#b50020] text-white text-xs font-semibold cursor-pointer flex items-center gap-1.5 transition-colors disabled:opacity-50"
            >
              {isDeletingQuestion ? (
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

export default FaqList;

