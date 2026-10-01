import { useState, useMemo, useEffect } from "react";
import { Avatar, Drawer, Modal, Skeleton } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  FileCode,
  FileIcon,
  FileImage,
  FileText,
  Loader2,
  Mail,
  MessageSquare,
  Search,
  Send,
  Trash2,
  Upload,
  Video,
} from "lucide-react";
import { DESIGN_TOKENS } from "@/constant/design-system";
import {
  useAdminSupportTickets,
  useAdminUpdateTicket,
  useAdminDeleteTicket,
} from "@/hooks/api/useSupportApi";
import { useFaqCategories } from "@/hooks/api/useFaqApi";
import type { SupportTicketItem, SupportStatus } from "@/api/supportApi";

interface TableCheckboxProps {
  checked: boolean;
  onChange: () => void;
  "aria-label"?: string;
}

const TableCheckbox = ({
  checked,
  onChange,
  "aria-label": ariaLabel,
}: TableCheckboxProps) => {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={ariaLabel}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
      className={`w-4 h-4 rounded-[4px] border transition-all cursor-pointer inline-flex items-center justify-center shrink-0 ${
        checked
          ? "bg-text-dark border-text-dark text-surface-card shadow-2xs"
          : "bg-surface-card border-border-default hover:border-text-muted/60"
      }`}
    >
      {checked && (
        <Check size={11} strokeWidth={3} className="text-surface-card" />
      )}
    </button>
  );
};

const formatRelativeTime = (isoDate?: string | null): string => {
  if (!isoDate) return "recently";
  const date = new Date(isoDate);
  const diffMs = Date.now() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins} mins ago`;
  const diffHrs = Math.floor(diffMins / 60);
  if (diffHrs < 24) return `${diffHrs} ${diffHrs === 1 ? "hr" : "hrs"} ago`;
  const diffDays = Math.floor(diffHrs / 24);
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 30) return `${diffDays} days ago`;
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
};

const getInitials = (name?: string | null, email?: string): string => {
  if (name?.trim()) {
    const parts = name.trim().split(" ");
    return parts.map((p) => p[0]).join("").slice(0, 2).toUpperCase();
  }
  return email ? email[0].toUpperCase() : "U";
};

const getTopicBadgeStyle = (topic: string) => {
  const normalized = topic.toLowerCase();
  if (normalized.includes("token") || normalized.includes("usage")) {
    return {
      bg: `${DESIGN_TOKENS.colors.highlightOrange}14`,
      text: DESIGN_TOKENS.colors.highlightOrange,
      dot: DESIGN_TOKENS.colors.highlightOrange,
    };
  }
  if (normalized.includes("bill") || normalized.includes("plan") || normalized.includes("pay")) {
    return {
      bg: `${DESIGN_TOKENS.colors.highlightPink}14`,
      text: DESIGN_TOKENS.colors.highlightPink,
      dot: DESIGN_TOKENS.colors.highlightPink,
    };
  }
  if (normalized.includes("trouble") || normalized.includes("tech") || normalized.includes("bug")) {
    return {
      bg: `${DESIGN_TOKENS.colors.highlightCyan}14`,
      text: DESIGN_TOKENS.colors.highlightCyan,
      dot: DESIGN_TOKENS.colors.highlightCyan,
    };
  }
  if (normalized.includes("account") || normalized.includes("access") || normalized.includes("auth")) {
    return {
      bg: `${DESIGN_TOKENS.colors.graphMarker}14`,
      text: DESIGN_TOKENS.colors.graphMarker,
      dot: DESIGN_TOKENS.colors.graphMarker,
    };
  }
  return {
    bg: "rgba(115, 115, 115, 0.12)",
    text: "var(--secondary-active-dark)",
    dot: "var(--text-primary)",
  };
};

const getStatusBadge = (status: SupportStatus | string) => {
  switch (status) {
    case "OPEN":
      return {
        bg: `${DESIGN_TOKENS.colors.highlightOrange}14`,
        text: DESIGN_TOKENS.colors.highlightOrange,
        label: "Open",
      };
    case "IN_PROGRESS":
      return {
        bg: `${DESIGN_TOKENS.colors.highlightCyan}14`,
        text: DESIGN_TOKENS.colors.highlightCyan,
        label: "In Progress",
      };
    case "RESOLVED":
      return {
        bg: `${DESIGN_TOKENS.colors.stateSuccess}14`,
        text: DESIGN_TOKENS.colors.stateSuccess,
        label: "Resolved",
      };
    case "CLOSED":
      return {
        bg: "rgba(115, 115, 115, 0.12)",
        text: "var(--text-muted)",
        label: "Closed",
      };
    default:
      return {
        bg: `${DESIGN_TOKENS.colors.highlightOrange}14`,
        text: DESIGN_TOKENS.colors.highlightOrange,
        label: status,
      };
  }
};

const getAttachmentInfo = (attachment?: string | null, attachmentType?: string | null) => {
  if (!attachment) return null;
  const filename = attachment.split("/").pop()?.replace(/^[a-f0-9]+_/, "") || "attachment";
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  const mime = attachmentType?.toLowerCase() || "";

  let type: "image" | "pdf" | "document" | "code" | "video" = "document";
  if (mime.includes("image") || ["png", "jpg", "jpeg", "webp", "gif", "svg"].includes(ext)) {
    type = "image";
  } else if (mime.includes("video") || ["mp4", "webm", "mov", "mkv", "avi", "m4v"].includes(ext)) {
    type = "video";
  } else if (mime.includes("pdf") || ext === "pdf") {
    type = "pdf";
  } else if (["json", "xml", "js", "ts", "py", "html", "css", "log", "txt"].includes(ext)) {
    type = "code";
  }

  return { name: filename, type, url: attachment };
};

const getAttachmentIcon = (type?: string) => {
  switch (type) {
    case "video":
      return <Video size={13} className="text-[#F54397] shrink-0" />;
    case "image":
      return <FileImage size={13} className="text-text-muted shrink-0" />;
    case "pdf":
      return <FileText size={13} className="text-text-muted shrink-0" />;
    case "code":
      return <FileCode size={13} className="text-text-muted shrink-0" />;
    default:
      return <FileIcon size={13} className="text-text-muted shrink-0" />;
  }
};

const PAGE_SIZE = 10;

const InquiryTable = () => {
  const [page, setPage] = useState(1);
  const [topicFilter, setTopicFilter] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [selectedInquiry, setSelectedInquiry] = useState<SupportTicketItem | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [replyText, setReplyText] = useState("");
  const [isReplying, setIsReplying] = useState(false);
  const [updatingStatus, setUpdatingStatus] = useState<SupportStatus | null>(null);
  const [ticketToDelete, setTicketToDelete] = useState<SupportTicketItem | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // Debounce search query
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedSearch(searchQuery.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(handler);
  }, [searchQuery]);

  // Categories for filter options
  const { data: categoriesData } = useFaqCategories({ limit: 100 });
  const categories = useMemo(() => categoriesData?.data ?? [], [categoriesData]);

  // Fetch Tickets from API
  const { data: ticketsData, isLoading, isFetching, isPlaceholderData } = useAdminSupportTickets({
    page,
    limit: PAGE_SIZE,
    search: debouncedSearch || undefined,
    category_id: topicFilter !== "all" ? topicFilter : undefined,
  });

  const inquiries = useMemo(() => ticketsData?.data ?? [], [ticketsData]);
  const totalCount = ticketsData?.total ?? 0;
  const totalPages = Math.ceil(totalCount / PAGE_SIZE) || 1;

  // Mutations
  const updateTicketMutation = useAdminUpdateTicket();
  const deleteTicketMutation = useAdminDeleteTicket();

  // Dynamic filter tabs
  const topicFilterOptions = useMemo(() => {
    const opts = [{ label: "All", value: "all" }];
    categories.forEach((cat) => {
      opts.push({ label: cat.name, value: cat.id });
    });
    return opts;
  }, [categories]);

  const handleSelectAll = () => {
    if (selectedIds.length === inquiries.length && inquiries.length > 0) {
      setSelectedIds([]);
    } else {
      setSelectedIds(inquiries.map((i) => i.id));
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    );
  };

  const handleRowClick = (inq: SupportTicketItem) => {
    setSelectedInquiry(inq);
    setReplyText("");
    setIsDrawerOpen(true);
  };

  const handleStatusChange = async (status: SupportStatus) => {
    if (!selectedInquiry) return;
    setUpdatingStatus(status);
    try {
      const updated = await updateTicketMutation.mutateAsync({
        id: selectedInquiry.id,
        payload: { status },
      });
      setSelectedInquiry(updated);
      notifications.show({
        title: "Status Updated",
        message: `Ticket #${selectedInquiry.id.slice(0, 4).toUpperCase()} status changed to ${getStatusBadge(status).label}`,
        color: "green",
      });
    } catch {
      notifications.show({
        title: "Error",
        message: "Failed to update ticket status.",
        color: "red",
      });
    } finally {
      setUpdatingStatus(null);
    }
  };

  const handleConfirmDelete = async () => {
    if (!ticketToDelete) return;
    setIsDeleting(true);
    try {
      await deleteTicketMutation.mutateAsync(ticketToDelete.id);
      if (selectedInquiry?.id === ticketToDelete.id) {
        setIsDrawerOpen(false);
        setSelectedInquiry(null);
      }
      setTicketToDelete(null);
      notifications.show({
        title: "Ticket Deleted",
        message: "Support ticket deleted successfully.",
        color: "gray",
      });
    } catch {
      notifications.show({
        title: "Error",
        message: "Failed to delete support ticket.",
        color: "red",
      });
    } finally {
      setIsDeleting(false);
    }
  };

  const handleSendReply = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!replyText.trim() || !selectedInquiry) return;
    setIsReplying(true);
    try {
      // Update ticket status to IN_PROGRESS if OPEN
      if (selectedInquiry.status === "OPEN") {
        await handleStatusChange("IN_PROGRESS");
      }
      
      // Open default mail client with pre-filled response
      const subject = encodeURIComponent(`Re: Support Ticket #${selectedInquiry.id.slice(0, 4).toUpperCase()} - ${selectedInquiry.category?.name || selectedInquiry.problem_type || "Inquiry"}`);
      const body = encodeURIComponent(replyText.trim());
      window.location.href = `mailto:${selectedInquiry.email}?subject=${subject}&body=${body}`;

      notifications.show({
        title: "Reply Ready",
        message: `Opening email draft to ${selectedInquiry.email}`,
        color: "green",
      });
      setReplyText("");
    } catch {
      notifications.show({
        title: "Error",
        message: "Failed to process reply.",
        color: "red",
      });
    } finally {
      setIsReplying(false);
    }
  };

  const handleExportCSV = () => {
    const headers = [
      "Ticket ID",
      "Name",
      "Email",
      "Topic / Category",
      "Problem Description",
      "Attachment URL",
      "Status",
      "Created At",
    ];
    const rows = inquiries.map((i) => [
      `"#TK-${i.id.slice(0, 4).toUpperCase()}"`,
      `"${i.name}"`,
      `"${i.email}"`,
      `"${i.category?.name || i.problem_type || "General"}"`,
      `"${(i.description || "").replace(/"/g, '""')}"`,
      `"${i.attachment || "None"}"`,
      i.status,
      i.created_at,
    ]);
    const csvContent =
      "data:text/csv;charset=utf-8," +
      [headers.join(","), ...rows.map((e) => e.join(","))].join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute(
      "download",
      `inquiries_export_${new Date().toISOString().slice(0, 10)}.csv`
    );
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="flex flex-col gap-3.5">
      {/* Top Filter Bar & Search Toolbar */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        {/* Filter Buttons */}
        <div className="flex items-center gap-2 overflow-x-auto custom-scrollbar w-full sm:w-auto pb-1 sm:pb-0">
          {topicFilterOptions.map((opt) => {
            const isActive = topicFilter === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => {
                  setTopicFilter(opt.value);
                  setPage(1);
                }}
                className={`px-3.5 py-1.5 rounded-full text-xs font-medium transition-all cursor-pointer shrink-0 border flex items-center gap-1.5 ${
                  isActive
                    ? "btn-gradient-black border-transparent shadow-2xs font-semibold"
                    : "bg-surface-card text-text-muted border-border-default hover:text-text-dark hover:border-text-muted/40"
                }`}
                style={{ borderRadius: "9999px" }}
              >
                <span>{opt.label}</span>
              </button>
            );
          })}
        </div>

        {/* Search and Action Buttons */}
        <div className="flex items-center gap-2.5 w-full sm:w-auto">
          <div
            style={{
              display: "flex",
              width: "288px",
              height: "36px",
              padding: "0 12px",
              alignItems: "center",
              gap: "8px",
              borderRadius: "var(--Radius-8, 8px)",
              border: "1px solid var(--Stroke-Primary, #EBEBEB)",
              background: "var(--Background-Surface-Default, #FFF)",
            }}
          >
            <Search
              size={15}
              className="text-text-muted shrink-0 pointer-events-none"
            />
            <input
              type="text"
              placeholder="Search inquiries"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-full w-full bg-transparent text-[13px] text-text-dark placeholder:text-text-muted focus:outline-none border-none p-0"
            />
          </div>

          {/* Export Button */}
          <button
            type="button"
            onClick={handleExportCSV}
            className="text-[13px] font-medium text-text-dark hover:bg-surface-primary transition-colors cursor-pointer shadow-2xs shrink-0 whitespace-nowrap"
            style={{
              display: "flex",
              height: "36px",
              padding: "0 12px",
              alignItems: "center",
              gap: "8px",
              borderRadius: "var(--Radius-8, 8px)",
              border: "1px solid var(--Stroke-Primary, #EBEBEB)",
              background: "var(--Background-Surface-Default, #FFF)",
            }}
          >
            <Upload size={14} className="text-text-muted shrink-0" />
            <span>Export</span>
          </button>
        </div>
      </div>

      {/* Inquiry Table Card */}
      <div className="rounded-12 border border-border-default bg-surface-card shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-primary/70 border-b border-border-default text-[12px] font-normal text-text-muted">
                <th className="w-12 px-5 py-3 text-center">
                  <div className="flex items-center justify-center">
                    <TableCheckbox
                      checked={
                        inquiries.length > 0 &&
                        selectedIds.length === inquiries.length
                      }
                      onChange={handleSelectAll}
                      aria-label="Select all inquiries"
                    />
                  </div>
                </th>
                <th className="px-4 py-3 font-normal text-text-muted">
                  Your name
                </th>
                <th className="px-4 py-3 font-normal text-text-muted">
                  Email
                </th>
                <th className="px-4 py-3 font-normal text-text-muted">
                  What's this about?
                </th>
                <th className="px-4 py-3 font-normal text-text-muted max-w-xs">
                  Describe the problem
                </th>
                <th className="px-4 py-3 font-normal text-text-muted">
                  Attachments
                </th>
                <th className="px-4 py-3 font-normal text-text-muted">
                  Status
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-default">
              {isLoading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i}>
                    <td className="px-5 py-3.5 text-center">
                      <Skeleton height={16} width={16} radius="sm" mx="auto" />
                    </td>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-2.5">
                        <Skeleton circle height={26} width={26} />
                        <div className="space-y-1">
                          <Skeleton height={12} width={90} radius="sm" />
                          <Skeleton height={9} width={50} radius="sm" />
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3.5">
                      <Skeleton height={12} width={130} radius="sm" />
                    </td>
                    <td className="px-4 py-3.5">
                      <Skeleton height={20} width={90} radius="xl" />
                    </td>
                    <td className="px-4 py-3.5">
                      <Skeleton height={12} width={180} radius="sm" />
                    </td>
                    <td className="px-4 py-3.5">
                      <Skeleton height={18} width={70} radius="sm" />
                    </td>
                    <td className="px-4 py-3.5">
                      <Skeleton height={18} width={60} radius="sm" />
                    </td>
                  </tr>
                ))
              ) : inquiries.length === 0 ? (
                <tr>
                  <td
                    colSpan={7}
                    className="px-5 py-12 text-center text-sm text-text-muted"
                  >
                    No inquiries found matching your criteria.
                  </td>
                </tr>
              ) : (
                inquiries.map((inq) => {
                  const isSelected = selectedIds.includes(inq.id);
                  const ticketNumber = `#TK-${inq.id.slice(0, 4).toUpperCase()}`;
                  const topic = inq.category?.name || inq.problem_type || "General";
                  const topicStyle = getTopicBadgeStyle(topic);
                  const statusStyle = getStatusBadge(inq.status);
                  const attachmentInfo = getAttachmentInfo(
                    inq.attachment,
                    inq.attachment_type
                  );

                  return (
                    <tr
                      key={inq.id}
                      onClick={() => handleRowClick(inq)}
                      className={`hover:bg-surface-primary/60 transition-colors cursor-pointer ${
                        isSelected ? "bg-surface-primary/70" : ""
                      } ${isFetching ? "opacity-75" : ""}`}
                    >
                      {/* Checkbox */}
                      <td
                        className="px-5 py-3.5 text-center"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="flex items-center justify-center">
                          <TableCheckbox
                            checked={isSelected}
                            onChange={() => toggleSelect(inq.id)}
                            aria-label={`Select ${inq.name}`}
                          />
                        </div>
                      </td>

                      {/* Requester Avatar + Name */}
                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-2.5">
                          <Avatar
                            size={26}
                            radius="xl"
                            color="dark"
                            className="bg-surface-primary text-[11px] font-bold text-text-dark border border-border-default"
                          >
                            {getInitials(inq.name, inq.email)}
                          </Avatar>
                          <div className="flex flex-col">
                            <span className="text-[13px] font-medium text-text-dark">
                              {inq.name}
                            </span>
                            <span className="text-[10px] text-text-muted font-normal">
                              {ticketNumber}
                            </span>
                          </div>
                        </div>
                      </td>

                      {/* Email */}
                      <td className="px-4 py-3.5 text-[13px] text-text-dark font-normal">
                        {inq.email}
                      </td>

                      {/* What's this about? (Topic Badge) */}
                      <td className="px-4 py-3.5">
                        <span
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium whitespace-nowrap"
                          style={{
                            backgroundColor: topicStyle.bg,
                            color: topicStyle.text,
                          }}
                        >
                          <span
                            className="w-1.5 h-1.5 rounded-full shrink-0"
                            style={{ backgroundColor: topicStyle.dot }}
                          />
                          {topic}
                        </span>
                      </td>

                      {/* Describe the problem (Truncated) */}
                      <td className="px-4 py-3.5 max-w-[280px]">
                        <p className="text-[12.5px] text-text-muted font-normal line-clamp-1 truncate">
                          {inq.description}
                        </p>
                      </td>

                      {/* Attachments */}
                      <td className="px-4 py-3.5">
                        {attachmentInfo ? (
                          <div
                            onClick={(e) => {
                              if (attachmentInfo.url) {
                                e.stopPropagation();
                                window.open(attachmentInfo.url, "_blank");
                              }
                            }}
                            className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-[6px] bg-surface-primary border border-border-default text-text-dark text-[11px] font-medium max-w-[150px] truncate hover:border-text-dark transition-colors cursor-pointer"
                            title="View attachment"
                          >
                            {getAttachmentIcon(attachmentInfo.type)}
                            <span className="truncate">{attachmentInfo.name}</span>
                          </div>
                        ) : (
                          <span className="text-text-muted text-[12px]">—</span>
                        )}
                      </td>

                      {/* Status */}
                      <td className="px-4 py-3.5">
                        <span
                          className="inline-flex items-center px-2 py-0.5 rounded-[4px] text-[10.5px] font-bold"
                          style={{
                            backgroundColor: statusStyle.bg,
                            color: statusStyle.text,
                          }}
                        >
                          {statusStyle.label}
                        </span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Footer */}
        {!isLoading && totalCount > 0 && (
          <div className="flex items-center justify-between px-5 py-3 border-t border-border-default bg-surface-primary/40">
            {/* Left: count info */}
            {isFetching && !isPlaceholderData ? (
              <span className="text-[12px] text-text-muted animate-pulse">
                Loading…
              </span>
            ) : (
              <span className="text-[12px] text-text-muted">
                {(page - 1) * PAGE_SIZE + 1}–
                {Math.min(page * PAGE_SIZE, totalCount)} of{" "}
                <strong className="text-text-dark">
                  {totalCount.toLocaleString()}
                </strong>{" "}
                inquiries
              </span>
            )}

            {/* Right: navigation buttons */}
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                disabled={page <= 1 || isFetching}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="p-1.5 rounded-[6px] border border-border-default bg-surface-card text-text-muted hover:text-text-dark hover:bg-surface-primary disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
                aria-label="Previous page"
              >
                <ChevronLeft size={14} />
              </button>

              <span className="text-[12px] font-medium text-text-dark px-2">
                Page {page} of {totalPages}
              </span>

              <button
                type="button"
                disabled={page >= totalPages || isFetching}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                className="p-1.5 rounded-[6px] border border-border-default bg-surface-card text-text-muted hover:text-text-dark hover:bg-surface-primary disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
                aria-label="Next page"
              >
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Inquiry Detail Drawer / Slide-Over Panel */}
      <Drawer
        opened={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        position="right"
        size="lg"
        padding="lg"
        title={
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-[6px] btn-gradient-black flex items-center justify-center">
              <MessageSquare size={13} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h4 className="text-sm font-bold text-text-dark">
                  {selectedInquiry
                    ? `#TK-${selectedInquiry.id.slice(0, 4).toUpperCase()}`
                    : "Inquiry Details"}
                </h4>
                {selectedInquiry && (
                  <span
                    className="text-[10px] font-bold px-2 py-0.5 rounded-[4px] inline-flex items-center gap-1"
                    style={{
                      backgroundColor: getStatusBadge(selectedInquiry.status).bg,
                      color: getStatusBadge(selectedInquiry.status).text,
                    }}
                  >
                    {updateTicketMutation.isPending && (
                      <Loader2 size={10} className="animate-spin text-current shrink-0" />
                    )}
                    <span>{getStatusBadge(selectedInquiry.status).label}</span>
                  </span>
                )}
              </div>
              <p className="text-[11px] text-text-muted">
                Submitted {formatRelativeTime(selectedInquiry?.created_at)}
              </p>
            </div>
          </div>
        }
        styles={{
          header: {
            borderBottom: "1px solid var(--border-primary)",
            paddingBottom: "12px",
          },
          body: {
            paddingTop: "16px",
          },
        }}
      >
        {selectedInquiry && (
          <div className="space-y-5">
            {/* Requester Information Card */}
            <div className="rounded-12 border border-border-default p-3.5 bg-surface-primary space-y-2.5">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold text-text-dark uppercase tracking-wider">
                  Requester Details
                </span>
                <span className="text-[10px] text-text-muted">
                  {formatRelativeTime(selectedInquiry.created_at)}
                </span>
              </div>

              <div className="flex items-center gap-3 pt-1">
                <Avatar
                  size={36}
                  radius="xl"
                  color="dark"
                  className="bg-surface-card text-xs font-bold text-text-dark border border-border-default"
                >
                  {getInitials(selectedInquiry.name, selectedInquiry.email)}
                </Avatar>
                <div className="flex flex-col">
                  <span className="text-[13px] font-bold text-text-dark">
                    {selectedInquiry.name}
                  </span>
                  <a
                    href={`mailto:${selectedInquiry.email}`}
                    className="text-xs text-text-muted hover:text-text-dark flex items-center gap-1 transition-colors"
                  >
                    <Mail size={11} />
                    {selectedInquiry.email}
                  </a>
                </div>
              </div>
            </div>

            {/* What's this about? Category Pill Section */}
            <div className="rounded-12 border border-border-default p-3.5 bg-surface-card space-y-2">
              <span className="text-[11px] font-bold text-text-dark uppercase tracking-wider block">
                What's this about?
              </span>

              <div className="pt-0.5">
                {(() => {
                  const topic =
                    selectedInquiry.category?.name ||
                    selectedInquiry.problem_type ||
                    "General";
                  const style = getTopicBadgeStyle(topic);
                  return (
                    <span
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold"
                      style={{
                        backgroundColor: style.bg,
                        color: style.text,
                      }}
                    >
                      <span
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{
                          backgroundColor: style.dot,
                        }}
                      />
                      {topic}
                    </span>
                  );
                })()}
              </div>
            </div>

            {/* Describe the Problem Section */}
            <div className="rounded-12 border border-border-default p-3.5 bg-surface-card space-y-2">
              <span className="text-[11px] font-bold text-text-dark uppercase tracking-wider block">
                Problem Description
              </span>

              <div className="p-3 rounded-[8px] bg-surface-primary border border-border-default text-[13px] text-text-dark leading-relaxed whitespace-pre-wrap">
                {selectedInquiry.description}
              </div>
            </div>

            {/* Attachments Section */}
            <div className="rounded-12 border border-border-default p-3.5 bg-surface-card space-y-2.5">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold text-text-dark uppercase tracking-wider">
                  Attachments
                </span>
                <span className="text-[11px] text-text-muted font-normal">
                  {selectedInquiry.attachment ? "1 file attached" : "None"}
                </span>
              </div>

              {selectedInquiry.attachment ? (
                (() => {
                  const att = getAttachmentInfo(
                    selectedInquiry.attachment,
                    selectedInquiry.attachment_type
                  );
                  if (!att) return null;
                  return (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between p-2.5 rounded-[8px] bg-surface-primary border border-border-default hover:border-text-dark transition-colors">
                        <div className="flex items-center gap-2.5 min-w-0">
                          <div className="w-8 h-8 rounded-[6px] bg-surface-card border border-border-default flex items-center justify-center shrink-0">
                            {getAttachmentIcon(att.type)}
                          </div>
                          <div className="flex flex-col min-w-0">
                            <span className="text-xs font-semibold text-text-dark truncate">
                              {att.name}
                            </span>
                            <span className="text-[10px] text-text-muted">
                              {selectedInquiry.attachment_type || "File"}
                            </span>
                          </div>
                        </div>

                        <button
                          type="button"
                          onClick={() => window.open(att.url, "_blank")}
                          className="p-1.5 rounded-[6px] hover:bg-surface-card text-text-muted hover:text-text-dark transition-colors cursor-pointer shrink-0"
                          title="Download / View attachment"
                        >
                          <Download size={14} />
                        </button>
                      </div>

                      {att.type === "video" && (
                        <div className="rounded-[8px] overflow-hidden border border-border-default bg-black mt-2">
                          <video
                            controls
                            src={att.url}
                            className="w-full max-h-64 object-contain"
                          />
                        </div>
                      )}
                      {att.type === "image" && (
                        <div className="rounded-[8px] overflow-hidden border border-border-default bg-black/40 mt-2">
                          <img
                            src={att.url}
                            alt={att.name}
                            className="w-full max-h-64 object-contain cursor-pointer"
                            onClick={() => window.open(att.url, "_blank")}
                          />
                        </div>
                      )}
                    </div>
                  );
                })()
              ) : (
                <div className="text-xs text-text-muted italic py-1">
                  No attachments provided with this ticket.
                </div>
              )}
            </div>

            {/* Quick Status Toggles & Reply Section */}
            <div className="rounded-12 border border-border-default p-3.5 bg-surface-card space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold text-text-dark uppercase tracking-wider">
                  Update Status
                </span>
                <div className="flex items-center gap-1.5">
                  {(
                    [
                      { value: "OPEN" as SupportStatus, label: "Open" },
                      { value: "IN_PROGRESS" as SupportStatus, label: "In Progress" },
                      { value: "RESOLVED" as SupportStatus, label: "Resolved" },
                      { value: "CLOSED" as SupportStatus, label: "Closed" },
                    ]
                  ).map((st) => {
                    const isCurrent = selectedInquiry.status === st.value;
                    const isTargetUpdating =
                      updatingStatus === st.value &&
                      updateTicketMutation.isPending;
                    const isAnyUpdating = updateTicketMutation.isPending;

                    return (
                      <button
                        key={st.value}
                        type="button"
                        disabled={isAnyUpdating}
                        onClick={() => handleStatusChange(st.value)}
                        className={`text-[11px] px-2.5 py-1 rounded-[6px] font-medium transition-all cursor-pointer inline-flex items-center gap-1.5 ${
                          isCurrent
                            ? "btn-gradient-black shadow-2xs font-semibold"
                            : "border border-border-default bg-surface-primary text-text-muted hover:text-text-dark"
                        } ${
                          isAnyUpdating && !isTargetUpdating
                            ? "opacity-50 cursor-not-allowed"
                            : ""
                        }`}
                      >
                        {isTargetUpdating && (
                          <Loader2
                            size={11}
                            className="animate-spin text-current shrink-0"
                          />
                        )}
                        <span>{st.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Reply Form */}
              <form onSubmit={handleSendReply} className="space-y-2.5 pt-1">
                <label className="block text-xs font-semibold text-text-dark">
                  Reply to {selectedInquiry.name}
                </label>
                <textarea
                  rows={3}
                  value={replyText}
                  onChange={(e) => setReplyText(e.target.value)}
                  placeholder={`Type response to ${selectedInquiry.email}...`}
                  className="w-full px-3 py-2 text-xs rounded-[8px] border border-border-default bg-surface-primary text-text-dark placeholder:text-text-muted focus:outline-none focus:border-text-dark resize-none"
                />

                <button
                  type="submit"
                  disabled={!replyText.trim() || isReplying}
                  className="w-full py-2.5 rounded-10 text-surface-card text-xs font-bold uppercase tracking-wider bg-gradient-purchase-cta shadow-md hover:opacity-95 transition-opacity flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Send size={13} />
                  <span>{isReplying ? "Sending..." : "Send Reply & Update"}</span>
                </button>
              </form>
            </div>

            {/* Delete / Close Actions */}
            <div className="pt-2 border-t border-border-default flex items-center gap-2">
              <button
                type="button"
                onClick={() => setTicketToDelete(selectedInquiry)}
                disabled={deleteTicketMutation.isPending || isDeleting}
                className="py-2.5 px-3 rounded-10 border border-red-500/30 text-red-500 hover:bg-red-500/10 text-xs font-semibold transition-colors cursor-pointer flex items-center gap-1.5 disabled:opacity-50"
                title="Delete ticket"
              >
                <Trash2 size={13} />
                <span>Delete</span>
              </button>
              <button
                type="button"
                onClick={() => setIsDrawerOpen(false)}
                className="flex-1 py-2.5 rounded-10 border border-border-default text-text-muted hover:text-text-dark hover:bg-surface-primary text-xs font-semibold transition-colors cursor-pointer"
              >
                Close Drawer
              </button>
            </div>
          </div>
        )}
      </Drawer>

      {/* Delete Confirmation Modal */}
      <Modal
        opened={!!ticketToDelete}
        onClose={() => {
          if (!isDeleting) setTicketToDelete(null);
        }}
        title={
          <div className="flex items-center gap-2 text-text-dark font-bold text-sm">
            <Trash2 size={16} className="text-[#D80027]" />
            <span>Delete Support Ticket</span>
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
              <span className="text-xs font-semibold text-text-dark">Deleting ticket...</span>
            </div>
          )}

          <p className="text-xs text-text-muted leading-relaxed">
            Are you sure you want to delete ticket{" "}
            <span className="text-text-dark font-semibold">
              #TK-{ticketToDelete?.id.slice(0, 4).toUpperCase()}
            </span>{" "}
            from{" "}
            <span className="text-text-dark font-semibold">
              {ticketToDelete?.name}
            </span>
            ? This action cannot be undone and will permanently remove this record.
          </p>

          <div className="pt-2 flex items-center justify-end gap-2 border-t border-border-default">
            <button
              type="button"
              disabled={isDeleting}
              onClick={() => setTicketToDelete(null)}
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
                <span>Delete Ticket</span>
              )}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
};

export default InquiryTable;
