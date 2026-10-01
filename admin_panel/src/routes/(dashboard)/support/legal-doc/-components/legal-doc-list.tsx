import { useState, useMemo } from "react";
import { Skeleton, Switch } from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import {
  Calendar,
  Eye,
  FileText,
  Globe,
  Pencil,
  Plus,
  Search,
  Shield,
  Tag,
  Trash2,
  User,
} from "lucide-react";
import { useLegalDocs, useDeleteLegalDoc, useUpdateLegalDoc } from "@/hooks/api/useLegalDoc";
import type { LegalDocumentResponse, DocumentType, DocumentLanguage } from "@/api/legalDoc";
import LegalDocModal from "./legal-doc-modal";
import LegalDocPreviewModal from "./legal-doc-preview-modal";

type FilterType = "all" | "active" | "inactive" | DocumentType | DocumentLanguage;

export const LegalDocList = () => {
  const { data: legalDocs = [], isLoading } = useLegalDocs();
  const deleteMutation = useDeleteLegalDoc();
  const updateMutation = useUpdateLegalDoc();

  const [togglingDocId, setTogglingDocId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState<FilterType>("all");

  // Modals state
  const [isCreateEditModalOpen, setIsCreateEditModalOpen] = useState(false);
  const [documentToEdit, setDocumentToEdit] = useState<LegalDocumentResponse | null>(null);

  const [isPreviewModalOpen, setIsPreviewModalOpen] = useState(false);
  const [previewDocument, setPreviewDocument] = useState<LegalDocumentResponse | null>(null);

  // Filtered documents
  const filteredDocs = useMemo(() => {
    return legalDocs.filter((doc) => {
      // Filter by status, type or language
      if (activeFilter !== "all") {
        if (activeFilter === "active") {
          if (!doc.is_active) return false;
        } else if (activeFilter === "inactive") {
          if (doc.is_active) return false;
        } else if (activeFilter === "Terms of Service" || activeFilter === "Privacy Policy") {
          if (doc.doc_type !== activeFilter) return false;
        } else if (activeFilter === "English" || activeFilter === "French") {
          if (doc.language !== activeFilter) return false;
        }
      }

      // Filter by search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesVersion = doc.version.toLowerCase().includes(q);
        const matchesType = doc.doc_type.toLowerCase().includes(q);
        const matchesAuthor = (doc.updated_by || "").toLowerCase().includes(q);
        const matchesContent = doc.content.toLowerCase().includes(q);
        const matchesLanguage = doc.language.toLowerCase().includes(q);
        const matchesStatus = doc.is_active
          ? "active published".includes(q)
          : "inactive draft hidden".includes(q);
        return (
          matchesVersion ||
          matchesType ||
          matchesAuthor ||
          matchesContent ||
          matchesLanguage ||
          matchesStatus
        );
      }

      return true;
    });
  }, [legalDocs, activeFilter, searchQuery]);

  const handleOpenCreate = () => {
    setDocumentToEdit(null);
    setIsCreateEditModalOpen(true);
  };

  const handleOpenEdit = (doc: LegalDocumentResponse) => {
    setDocumentToEdit(doc);
    setIsCreateEditModalOpen(true);
  };

  const handleOpenPreview = (doc: LegalDocumentResponse) => {
    setPreviewDocument(doc);
    setIsPreviewModalOpen(true);
  };

  const handleDelete = (doc: LegalDocumentResponse) => {
    modals.openConfirmModal({
      title: (
        <div className="flex items-center gap-2">
          <Trash2 size={16} className="text-red-500" />
          <span className="font-bold text-sm text-text-dark">Delete Legal Document</span>
        </div>
      ),
      children: (
        <p className="text-xs text-text-muted leading-relaxed">
          Are you sure you want to delete <span className="font-semibold text-text-dark">{doc.doc_type}</span> version{" "}
          <span className="font-semibold text-text-dark">{doc.version}</span> ({doc.language})? This action cannot be undone.
        </p>
      ),
      labels: { confirm: "Delete Document", cancel: "Cancel" },
      confirmProps: { color: "red" },
      centered: true,
      onConfirm: async () => {
        try {
          await deleteMutation.mutateAsync(doc.id);
          notifications.show({
            title: "Document Deleted",
            message: `${doc.doc_type} (${doc.version}) has been deleted successfully.`,
            color: "green",
          });
        } catch (err: unknown) {
          const errorObj = err as { message?: string; data?: { detail?: string } };
          notifications.show({
            title: "Failed to delete",
            message: errorObj?.data?.detail || errorObj?.message || "Could not delete legal document.",
            color: "red",
          });
        }
      },
    });
  };

  const handleToggleActive = async (doc: LegalDocumentResponse, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      setTogglingDocId(doc.id);
      const nextActive = !doc.is_active;
      await updateMutation.mutateAsync({
        id: doc.id,
        payload: {
          is_active: nextActive,
        },
      });
      notifications.show({
        title: nextActive ? "Document Activated" : "Document Deactivated",
        message: `${doc.doc_type} (${doc.version}) is now ${
          nextActive ? "active and visible in public API" : "inactive and hidden from public API"
        }.`,
        color: nextActive ? "teal" : "orange",
      });
    } catch (err: unknown) {
      const errorObj = err as { message?: string; data?: { detail?: string } };
      notifications.show({
        title: "Failed to update status",
        message: errorObj?.data?.detail || errorObj?.message || "Could not change active status.",
        color: "red",
      });
    } finally {
      setTogglingDocId(null);
    }
  };

  const stripHtml = (html: string) => {
    const tmp = document.createElement("div");
    tmp.innerHTML = html;
    return tmp.textContent || tmp.innerText || "";
  };

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return "N/A";
    try {
      return new Date(dateStr).toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    } catch {
      return dateStr;
    }
  };

  const filterTabs: { id: FilterType; label: string; count: number }[] = [
    { id: "all", label: "All Documents", count: legalDocs.length },
    {
      id: "active",
      label: "Active",
      count: legalDocs.filter((d) => d.is_active).length,
    },
    {
      id: "inactive",
      label: "Inactive",
      count: legalDocs.filter((d) => !d.is_active).length,
    },
    {
      id: "Terms of Service",
      label: "Terms of Service",
      count: legalDocs.filter((d) => d.doc_type === "Terms of Service").length,
    },
    {
      id: "Privacy Policy",
      label: "Privacy Policy",
      count: legalDocs.filter((d) => d.doc_type === "Privacy Policy").length,
    },
    {
      id: "English",
      label: "English",
      count: legalDocs.filter((d) => d.language === "English").length,
    },
    {
      id: "French",
      label: "French",
      count: legalDocs.filter((d) => d.language === "French").length,
    },
  ];

  return (
    <div className="space-y-5 mx-auto">
      {/* Top Header & Actions */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-text-dark">
            Legal Documents
          </h1>
          <p className="text-xs text-text-muted mt-0.5">
            Manage Terms of Service, Privacy Policies, versioning, and multilingual legal agreements.
          </p>
        </div>

        <button
          type="button"
          onClick={handleOpenCreate}
          className="px-4 py-2 rounded-8 btn-gradient-black text-xs font-semibold cursor-pointer flex items-center gap-2 shadow-2xs group"
        >
          <Plus size={15} strokeWidth={2.5} className="group-hover:scale-110 transition-transform" />
          <span>New Legal Document</span>
        </button>
      </div>

      {/* Pill-shaped Search Bar */}
      <div
        className="w-full h-11 px-4 rounded-full border border-border-default bg-surface-card flex items-center gap-3 transition-colors shadow-2xs hover:border-text-muted/40 focus-within:border-text-dark"
        style={{ borderRadius: "9999px" }}
      >
        <Search size={16} className="text-text-muted shrink-0 pointer-events-none" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search by version (v1.0.0), document type, author, active status, or clauses..."
          className="w-full bg-transparent text-[13px] text-text-dark placeholder:text-text-muted focus:outline-none border-none p-0"
        />
      </div>

      {/* Filter Pills */}
      <div className="flex items-center gap-2 overflow-x-auto custom-scrollbar pb-1">
        {filterTabs.map((tab) => {
          const isActive = activeFilter === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveFilter(tab.id)}
              className={`px-3.5 py-1.5 rounded-full text-xs font-medium transition-all cursor-pointer shrink-0 border flex items-center gap-1.5 ${
                isActive
                  ? "btn-gradient-black border-transparent shadow-2xs font-semibold"
                  : "bg-surface-card text-text-muted border-border-default hover:text-text-dark hover:border-text-muted/40"
              }`}
              style={{ borderRadius: "9999px" }}
            >
              <span>{tab.label}</span>
              <span className="text-[11px] opacity-75">{tab.count}</span>
            </button>
          );
        })}
      </div>

      {/* Document Cards List */}
      <div className="space-y-3">
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="p-4.5 rounded-12 border border-border-default bg-surface-card space-y-3 shadow-2xs"
              >
                <div className="flex justify-between items-center">
                  <Skeleton height={20} width="30%" radius="sm" />
                  <Skeleton height={20} width="15%" radius="sm" />
                </div>
                <div className="space-y-1.5">
                  <Skeleton height={14} radius="sm" />
                  <Skeleton height={14} width="80%" radius="sm" />
                </div>
                <div className="flex gap-4 pt-2">
                  <Skeleton height={12} width="20%" radius="sm" />
                  <Skeleton height={12} width="20%" radius="sm" />
                </div>
              </div>
            ))}
          </div>
        ) : filteredDocs.length === 0 ? (
          <div className="py-14 text-center rounded-12 border border-border-default bg-surface-card shadow-2xs space-y-3">
            <div className="w-12 h-12 rounded-full bg-surface-primary border border-border-default flex items-center justify-center mx-auto text-text-muted">
              <FileText size={22} />
            </div>
            <div>
              <p className="text-sm font-semibold text-text-dark">
                No legal documents found
              </p>
              <p className="text-xs text-text-muted mt-1 max-w-sm mx-auto">
                {searchQuery || activeFilter !== "all"
                  ? "Try adjusting your search terms or filters to find what you're looking for."
                  : "Get started by creating the first Terms of Service or Privacy Policy document for your platform."}
              </p>
            </div>
            {!searchQuery && activeFilter === "all" && (
              <button
                type="button"
                onClick={handleOpenCreate}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-8 btn-gradient-black text-xs font-medium cursor-pointer shadow-2xs"
              >
                <Plus size={14} />
                <span>Create Legal Document</span>
              </button>
            )}
          </div>
        ) : (
          filteredDocs.map((doc) => {
            const isTerms = doc.doc_type === "Terms of Service";
            const plainText = stripHtml(doc.content);

            return (
              <div
                key={doc.id}
                className="p-4.5 rounded-12 border border-border-default bg-surface-card hover:border-text-muted/40 transition-all duration-150 shadow-2xs space-y-3"
              >
                {/* Card Top: Badges & Actions */}
                <div className="flex flex-wrap items-center justify-between gap-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${
                        isTerms
                          ? "bg-teal-500/10 text-teal-600 dark:text-teal-400 border border-teal-500/20"
                          : "bg-orange-500/10 text-orange-600 dark:text-orange-400 border border-orange-500/20"
                      }`}
                    >
                      <Shield size={12} />
                      <span>{doc.doc_type}</span>
                    </span>

                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-surface-primary text-text-dark border border-border-default">
                      <Tag size={11} className="text-text-muted" />
                      <span>{doc.version}</span>
                    </span>

                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-surface-primary text-text-muted border border-border-default">
                      <Globe size={11} />
                      <span>{doc.language}</span>
                    </span>

                    <span
                      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                        doc.is_active
                          ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20"
                          : "bg-surface-primary text-text-muted border border-border-default"
                      }`}
                    >
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${
                          doc.is_active ? "bg-emerald-500 animate-pulse" : "bg-text-muted"
                        }`}
                      />
                      <span>{doc.is_active ? "Active" : "Inactive"}</span>
                    </span>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2">
                    {/* Quick Active Toggle */}
                    <div
                      role="button"
                      tabIndex={0}
                      onClick={(e) => handleToggleActive(doc, e)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          handleToggleActive(doc, e as unknown as React.MouseEvent);
                        }
                      }}
                      className="flex items-center gap-1.5 px-2.5 py-1 rounded-8 border border-border-default bg-surface-primary hover:bg-surface-card transition-colors cursor-pointer shadow-2xs select-none"
                      title={doc.is_active ? "Click to deactivate document" : "Click to activate document"}
                    >
                      <Switch
                        checked={doc.is_active}
                        onChange={() => {}}
                        size="xs"
                        color="teal"
                        disabled={togglingDocId === doc.id}
                        aria-label="Toggle active status"
                        className="pointer-events-none"
                      />
                      <span
                        className={`text-[11px] font-medium ${
                          doc.is_active
                            ? "text-emerald-600 dark:text-emerald-400 font-semibold"
                            : "text-text-muted"
                        }`}
                      >
                        {doc.is_active ? "Active" : "Inactive"}
                      </span>
                    </div>

                    <button
                      type="button"
                      onClick={() => handleOpenPreview(doc)}
                      className="px-2.5 py-1.5 rounded-8 border border-border-default bg-surface-primary hover:bg-surface-card text-text-muted hover:text-text-dark text-xs font-medium transition-colors cursor-pointer flex items-center gap-1 shadow-2xs"
                      title="Preview Document"
                    >
                      <Eye size={13} />
                      <span>Preview</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => handleOpenEdit(doc)}
                      className="p-1.5 rounded-8 border border-border-default bg-surface-primary hover:bg-surface-card text-text-muted hover:text-text-dark transition-colors cursor-pointer shadow-2xs"
                      title="Edit Document"
                      aria-label="Edit Document"
                    >
                      <Pencil size={13} />
                    </button>

                    <button
                      type="button"
                      onClick={() => handleDelete(doc)}
                      className="p-1.5 rounded-8 border border-border-default bg-surface-primary hover:bg-red-50 dark:hover:bg-red-950/30 text-text-muted hover:text-[#D80027] transition-colors cursor-pointer shadow-2xs"
                      title="Delete Document"
                      aria-label="Delete Document"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>

                {/* Content snippet */}
                <div
                  onClick={() => handleOpenPreview(doc)}
                  className="text-xs text-text-muted leading-relaxed line-clamp-2 cursor-pointer hover:text-text-dark transition-colors"
                >
                  {plainText || "No preview available."}
                </div>

                {/* Card Meta: Author and Timestamps */}
                <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-text-muted pt-2 border-t border-border-default/60">
                  <div className="flex items-center gap-1.5">
                    <User size={12} />
                    <span>Author:</span>
                    <span className="font-medium text-text-dark">{doc.updated_by || "Admin"}</span>
                  </div>

                  <div className="flex items-center gap-1.5">
                    <Calendar size={12} />
                    <span>Last Updated:</span>
                    <span className="font-medium text-text-dark">
                      {formatDate(doc.updated_at || doc.created_at)}
                    </span>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Create / Edit Modal */}
      <LegalDocModal
        opened={isCreateEditModalOpen}
        onClose={() => setIsCreateEditModalOpen(false)}
        documentToEdit={documentToEdit}
      />

      {/* Preview Modal */}
      <LegalDocPreviewModal
        opened={isPreviewModalOpen}
        onClose={() => setIsPreviewModalOpen(false)}
        document={previewDocument}
        onEdit={handleOpenEdit}
      />
    </div>
  );
};

export default LegalDocList;
