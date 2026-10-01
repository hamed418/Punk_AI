import { Modal } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  Calendar,
  Check,
  Copy,
  FileText,
  Globe,
  Pencil,
  Shield,
  Tag,
  User,
} from "lucide-react";
import { useState } from "react";
import type { LegalDocumentResponse } from "@/api/legalDoc";

interface LegalDocPreviewModalProps {
  opened: boolean;
  onClose: () => void;
  document: LegalDocumentResponse | null;
  onEdit?: (doc: LegalDocumentResponse) => void;
}

export const LegalDocPreviewModal = ({
  opened,
  onClose,
  document,
  onEdit,
}: LegalDocPreviewModalProps) => {
  const [copied, setCopied] = useState(false);

  if (!document) return null;

  const handleCopyContent = async () => {
    try {
      await navigator.clipboard.writeText(document.content);
      setCopied(true);
      notifications.show({
        title: "Copied to Clipboard",
        message: "Document content HTML copied to clipboard.",
        color: "green",
      });
      setTimeout(() => setCopied(false), 2000);
    } catch {
      notifications.show({
        title: "Error",
        message: "Failed to copy content.",
        color: "red",
      });
    }
  };

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return "N/A";
    try {
      return new Date(dateStr).toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return dateStr;
    }
  };

  const isTerms = document.doc_type === "Terms of Service";

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2">
          <FileText size={17} className="text-text-dark" />
          <span className="font-bold text-sm text-text-dark">
            Legal Document Preview
          </span>
        </div>
      }
      size="xl"
      centered
      radius="md"
      padding="lg"
      styles={{
        body: {
          maxHeight: "85vh",
          overflowY: "auto",
        },
      }}
    >
      <div className="space-y-4">
        {/* Document Header Card */}
        <div className="p-4 rounded-10 border border-border-default bg-surface-primary space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${
                  isTerms
                    ? "bg-highlight-teal/10 text-highlight-teal border border-highlight-teal/20"
                    : "bg-highlight-orange/10 text-highlight-orange border border-highlight-orange/20"
                }`}
              >
                <Shield size={12} />
                <span>{document.doc_type}</span>
              </span>

              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-surface-card text-text-dark border border-border-default shadow-2xs">
                <Tag size={12} className="text-text-muted" />
                <span>{document.version}</span>
              </span>

              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-surface-card text-text-muted border border-border-default shadow-2xs">
                <Globe size={12} />
                <span>{document.language}</span>
              </span>

              <span
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${
                  document.is_active
                    ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20"
                    : "bg-surface-card text-text-muted border border-border-default shadow-2xs"
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    document.is_active ? "bg-emerald-500 animate-pulse" : "bg-text-muted"
                  }`}
                />
                <span>{document.is_active ? "Active" : "Inactive (Draft)"}</span>
              </span>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleCopyContent}
                className="px-2.5 py-1.5 rounded-8 border border-border-default bg-surface-card hover:bg-surface-primary text-text-muted hover:text-text-dark text-xs font-medium transition-colors cursor-pointer flex items-center gap-1.5 shadow-2xs"
                title="Copy HTML content"
              >
                {copied ? <Check size={13} className="text-state-success" /> : <Copy size={13} />}
                <span>{copied ? "Copied" : "Copy HTML"}</span>
              </button>

              {onEdit && (
                <button
                  type="button"
                  onClick={() => {
                    onClose();
                    onEdit(document);
                  }}
                  className="px-2.5 py-1.5 rounded-8 btn-gradient-black text-xs font-medium cursor-pointer flex items-center gap-1.5 shadow-2xs"
                >
                  <Pencil size={13} />
                  <span>Edit</span>
                </button>
              )}
            </div>
          </div>

          {/* Metadata Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs text-text-muted pt-2 border-t border-border-default/60">
            <div className="flex items-center gap-1.5">
              <User size={13} className="shrink-0 text-text-muted" />
              <span>Author / Updated By:</span>
              <span className="font-medium text-text-dark">{document.updated_by || "Admin"}</span>
            </div>

            <div className="flex items-center gap-1.5">
              <Calendar size={13} className="shrink-0 text-text-muted" />
              <span>Last Modified:</span>
              <span className="font-medium text-text-dark">{formatDate(document.updated_at || document.created_at)}</span>
            </div>
          </div>
        </div>

        {/* Rendered HTML Content */}
        <div className="rounded-10 border border-border-default bg-surface-card p-5 sm:p-6 overflow-hidden shadow-2xs">
          <div
            className="text-text-dark leading-relaxed text-[13.5px] [&_h1]:text-lg [&_h1]:font-bold [&_h1]:text-text-dark [&_h1]:mb-3 [&_h1]:mt-1 [&_h2]:text-base [&_h2]:font-bold [&_h2]:text-text-dark [&_h2]:mt-4 [&_h2]:mb-2 [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:text-text-dark [&_h3]:mt-3 [&_h3]:mb-1.5 [&_p]:mb-3 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-3 [&_blockquote]:border-l-3 [&_blockquote]:border-border-default [&_blockquote]:pl-3.5 [&_blockquote]:italic [&_blockquote]:text-text-muted [&_blockquote]:my-3.5 [&_hr]:my-4 [&_hr]:border-border-default [&_code]:bg-surface-primary [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded-4 [&_code]:text-xs [&_code]:font-mono [&_pre]:bg-surface-primary [&_pre]:border [&_pre]:border-border-default [&_pre]:rounded-8 [&_pre]:p-3.5 [&_pre]:my-3 [&_pre]:font-mono [&_pre]:text-xs [&_a]:text-blue-500 [&_a]:underline [&_a]:underline-offset-2 hover:[&_a]:text-blue-600"
            dangerouslySetInnerHTML={{ __html: document.content }}
          />
        </div>

        {/* Modal Footer */}
        <div className="pt-2 flex items-center justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-8 border border-border-default bg-surface-card hover:bg-surface-primary text-text-muted hover:text-text-dark text-xs font-semibold transition-colors cursor-pointer"
          >
            Close Preview
          </button>
        </div>
      </div>
    </Modal>
  );
};

export default LegalDocPreviewModal;
