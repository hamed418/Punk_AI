import { useState } from "react";
import { Modal, Loader, Switch } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { FileText, PlusCircle, Pencil, AlertCircle, Shield, Globe, Tag, User, CheckCircle2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useCreateLegalDoc, useUpdateLegalDoc } from "@/hooks/api/useLegalDoc";
import type { LegalDocumentResponse, DocumentType, DocumentLanguage } from "@/api/legalDoc";
import LegalDocRichEditor from "./legal-doc-rich-editor";

interface LegalDocModalProps {
  opened: boolean;
  onClose: () => void;
  documentToEdit?: LegalDocumentResponse | null;
}

interface LegalDocFormProps {
  documentToEdit?: LegalDocumentResponse | null;
  onClose: () => void;
}

const LegalDocForm = ({ documentToEdit, onClose }: LegalDocFormProps) => {
  const { user } = useAuth();
  const isEditing = !!documentToEdit;

  const createMutation = useCreateLegalDoc();
  const updateMutation = useUpdateLegalDoc();

  const [docType, setDocType] = useState<DocumentType>(
    documentToEdit?.doc_type ?? "Terms of Service"
  );
  const [language, setLanguage] = useState<DocumentLanguage>(
    documentToEdit?.language ?? "English"
  );
  const [version, setVersion] = useState(documentToEdit?.version ?? "");
  const [updatedBy, setUpdatedBy] = useState(
    documentToEdit?.updated_by ?? user?.email ?? user?.full_name ?? "Admin"
  );
  const [isActive, setIsActive] = useState<boolean>(
    documentToEdit?.is_active ?? true
  );
  const [content, setContent] = useState(documentToEdit?.content ?? "");
  const [formError, setFormError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    const trimmedVersion = version.trim();
    const trimmedUpdatedBy = updatedBy.trim() || user?.email || user?.full_name || "Admin";
    const trimmedContent = content.trim();

    if (!trimmedVersion) {
      setFormError("Version is required (e.g. v1.0.0)");
      return;
    }

    if (!trimmedContent || trimmedContent === "<p></p>") {
      setFormError("Document content cannot be empty.");
      return;
    }

    try {
      if (isEditing && documentToEdit) {
        await updateMutation.mutateAsync({
          id: documentToEdit.id,
          payload: {
            version: trimmedVersion,
            language,
            is_active: isActive,
            updated_by: trimmedUpdatedBy,
            content: trimmedContent,
          },
        });

        notifications.show({
          title: "Document Updated",
          message: `${docType} (${trimmedVersion}) has been updated successfully.`,
          color: "green",
        });
      } else {
        await createMutation.mutateAsync({
          doc_type: docType,
          language,
          version: trimmedVersion,
          is_active: isActive,
          updated_by: trimmedUpdatedBy,
          content: trimmedContent,
        });

        notifications.show({
          title: "Document Created",
          message: `${docType} (${trimmedVersion}) has been created successfully.`,
          color: "green",
        });
      }

      onClose();
    } catch (err: unknown) {
      const errorObj = err as { message?: string; data?: { detail?: string } };
      const msg = errorObj?.data?.detail || errorObj?.message || "Failed to save legal document.";
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

      {/* Metadata Form Section */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
        {/* Document Type */}
        <div>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark mb-1.5">
            <Shield size={13} className="text-text-muted" />
            <span>Document Type</span>
          </label>
          <select
            value={docType}
            onChange={(e) => setDocType(e.target.value as DocumentType)}
            disabled={isEditing}
            className={`w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark transition-colors ${
              isEditing ? "opacity-60 bg-surface-primary cursor-not-allowed text-text-muted" : "cursor-pointer"
            }`}
          >
            <option value="Terms of Service">Terms of Service</option>
            <option value="Privacy Policy">Privacy Policy</option>
          </select>
        </div>

        {/* Language */}
        <div>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark mb-1.5">
            <Globe size={13} className="text-text-muted" />
            <span>Language</span>
          </label>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value as DocumentLanguage)}
            className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark transition-colors cursor-pointer"
          >
            <option value="English">English</option>
            <option value="French">French</option>
          </select>
        </div>

        {/* Version */}
        <div>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark mb-1.5">
            <Tag size={13} className="text-text-muted" />
            <span>Version Identifier</span>
          </label>
          <input
            type="text"
            required
            placeholder="e.g. v1.0.0, v2.1-2026"
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark placeholder:text-text-muted/60 focus:outline-none focus:border-text-dark transition-colors"
          />
        </div>

        {/* Author / Updated By */}
        <div>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark mb-1.5">
            <User size={13} className="text-text-muted" />
            <span>Author / Editor</span>
          </label>
          <input
            type="text"
            required
            placeholder="e.g. admin@punkai.io"
            value={updatedBy}
            onChange={(e) => setUpdatedBy(e.target.value)}
            className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark placeholder:text-text-muted/60 focus:outline-none focus:border-text-dark transition-colors"
          />
        </div>

        {/* Active Status Switch */}
        <div className="sm:col-span-2 p-3 rounded-8 bg-surface-primary border border-border-default flex items-center justify-between">
          <div className="space-y-0.5 pr-3">
            <label className="flex items-center gap-1.5 text-xs font-semibold text-text-dark">
              <CheckCircle2 size={13} className={isActive ? "text-emerald-500" : "text-text-muted"} />
              <span>Active Status</span>
              <span
                className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                  isActive
                    ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                    : "bg-surface-card text-text-muted border border-border-default"
                }`}
              >
                {isActive ? "Active · Publicly Visible" : "Inactive · Hidden Draft"}
              </span>
            </label>
            <p className="text-[11px] text-text-muted">
              {isActive
                ? "This document will be returned in the public legal API endpoints."
                : "This document will only be visible to admins and hidden from public endpoints."}
            </p>
          </div>
          <Switch
            checked={isActive}
            onChange={(e) => setIsActive(e.currentTarget.checked)}
            color="teal"
            size="sm"
            aria-label="Toggle document active status"
          />
        </div>
      </div>

      {/* Rich Text Editor Section */}
      <div className="space-y-1.5 pt-1">
        <div className="flex items-center justify-between">
          <label className="text-xs font-semibold text-text-dark flex items-center gap-1.5">
            <FileText size={13} className="text-text-muted" />
            <span>Document Content & Clauses</span>
          </label>
          <span className="text-[11px] text-text-muted">Rich Text Editor</span>
        </div>

        <LegalDocRichEditor
          content={content}
          onChange={(newContent) => setContent(newContent)}
          minHeight="260px"
          maxHeight="380px"
        />
      </div>

      {/* Footer Actions */}
      <div className="pt-3 flex items-center justify-end gap-2 border-t border-border-default">
        <button
          type="button"
          onClick={onClose}
          disabled={isPending}
          className="px-4 py-2 rounded-8 border border-border-default bg-surface-card text-xs font-semibold text-text-muted hover:text-text-dark hover:bg-surface-primary transition-colors cursor-pointer"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={isPending}
          className="px-4 py-2 rounded-8 btn-gradient-black text-xs font-semibold cursor-pointer flex items-center gap-1.5 shadow-2xs"
        >
          {isPending && <Loader size={12} color="white" />}
          <span>{isEditing ? "Save Changes" : "Create Document"}</span>
        </button>
      </div>
    </form>
  );
};

export const LegalDocModal = ({
  opened,
  onClose,
  documentToEdit,
}: LegalDocModalProps) => {
  const isEditing = !!documentToEdit;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2">
          {isEditing ? (
            <Pencil size={17} className="text-text-dark" />
          ) : (
            <PlusCircle size={17} className="text-text-dark" />
          )}
          <span className="font-bold text-sm text-text-dark">
            {isEditing ? "Edit Legal Document" : "Create New Legal Document"}
          </span>
        </div>
      }
      size="xl"
      centered
      radius="md"
      padding="lg"
      styles={{
        body: {
          maxHeight: "82vh",
          overflowY: "auto",
        },
      }}
    >
      {opened && (
        <LegalDocForm
          key={documentToEdit ? documentToEdit.id : "new"}
          documentToEdit={documentToEdit}
          onClose={onClose}
        />
      )}
    </Modal>
  );
};

export default LegalDocModal;
