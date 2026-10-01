import { useEffect } from "react";
import { useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import Link from "@tiptap/extension-link";
import TextAlign from "@tiptap/extension-text-align";
import Highlight from "@tiptap/extension-highlight";
import Subscript from "@tiptap/extension-subscript";
import Superscript from "@tiptap/extension-superscript";
import Placeholder from "@tiptap/extension-placeholder";
import { RichTextEditor } from "@mantine/tiptap";

interface LegalDocRichEditorProps {
  content: string;
  onChange: (html: string) => void;
  placeholder?: string;
  minHeight?: number | string;
  maxHeight?: number | string;
  editable?: boolean;
}

export const LegalDocRichEditor = ({
  content,
  onChange,
  placeholder = "Write the legal document terms and clauses here...",
  minHeight = "240px",
  maxHeight = "380px",
  editable = true,
}: LegalDocRichEditorProps) => {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: {
          levels: [1, 2, 3],
        },
      }),
      Underline,
      Link.configure({
        openOnClick: false,
        HTMLAttributes: {
          class: "text-blue-500 underline underline-offset-2 hover:text-blue-600 transition-colors",
        },
      }),
      TextAlign.configure({
        types: ["heading", "paragraph"],
      }),
      Highlight,
      Subscript,
      Superscript,
      Placeholder.configure({
        placeholder,
      }),
    ],
    content,
    editable,
    onUpdate: ({ editor: currentEditor }) => {
      onChange(currentEditor.getHTML());
    },
  });

  // Keep editor content in sync when external content changes
  useEffect(() => {
    if (editor && content !== editor.getHTML()) {
      editor.commands.setContent(content || "");
    }
  }, [content, editor]);

  if (!editor) {
    return (
      <div
        className="w-full rounded-8 border border-border-default bg-surface-card animate-pulse flex items-center justify-center text-xs text-text-muted"
        style={{ minHeight }}
      >
        <span>Loading Editor...</span>
      </div>
    );
  }

  return (
    <div className="w-full rounded-8 border border-border-default overflow-hidden bg-surface-card transition-colors focus-within:border-text-muted/60 [&_.mantine-RichTextEditor-control]:text-text-dark [&_.mantine-RichTextEditor-control]:transition-colors [&_.mantine-RichTextEditor-control:hover]:bg-surface-primary [&_.mantine-RichTextEditor-control:hover]:text-text-dark [&_.mantine-RichTextEditor-control[data-active]]:!bg-text-dark [&_.mantine-RichTextEditor-control[data-active]]:!text-surface-card [&_.mantine-RichTextEditor-control[data-active]_svg]:!text-surface-card [&_.mantine-RichTextEditor-control[data-active]_svg]:!stroke-surface-card [&_.mantine-RichTextEditor-control_svg]:w-4 [&_.mantine-RichTextEditor-control_svg]:h-4 [&_.mantine-RichTextEditor-control_svg]:stroke-current [&_.mantine-RichTextEditor-control_svg]:stroke-[2] [&_.mantine-RichTextEditor-control_svg]:shrink-0">
      <RichTextEditor
        editor={editor}
        styles={{
          root: {
            border: "none",
            backgroundColor: "transparent",
          },
          toolbar: {
            backgroundColor: "var(--primary-background)",
            borderBottom: "1px solid var(--border-primary)",
            padding: "6px 8px",
            gap: "3px",
            display: "flex",
            flexWrap: "nowrap",
            overflowX: "auto",
            alignItems: "center",
          },
          controlsGroup: {
            border: "none",
            backgroundColor: "transparent",
            padding: 0,
            gap: "2px",
            display: "flex",
            alignItems: "center",
            flexShrink: 0,
          },
          control: {
            borderRadius: "6px",
            border: "none",
            height: "26px",
            width: "26px",
            minWidth: "26px",
            fontSize: "12px",
            fontWeight: 600,
            color: "var(--secondary-active-dark)",
            backgroundColor: "transparent",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: "pointer",
            flexShrink: 0,
          },
          content: {
            minHeight,
            maxHeight,
            overflowY: "auto",
            padding: "14px 16px",
            fontSize: "13px",
            lineHeight: "1.7",
            color: "var(--secondary-active-dark)",
            backgroundColor: "var(--secondary-active-light)",
          },
        }}
      >
        <RichTextEditor.Toolbar sticky stickyOffset={0} className="custom-scrollbar">
          {/* Inline Text Formatting */}
          <RichTextEditor.ControlsGroup>
            <RichTextEditor.Bold />
            <RichTextEditor.Italic />
            <RichTextEditor.Underline />
            <RichTextEditor.Strikethrough />
            <RichTextEditor.Highlight />
          </RichTextEditor.ControlsGroup>

          <div className="w-px h-3.5 bg-border-default mx-1 shrink-0" />

          {/* Heading Hierarchy */}
          <RichTextEditor.ControlsGroup>
            <RichTextEditor.H1 />
            <RichTextEditor.H2 />
            <RichTextEditor.H3 />
          </RichTextEditor.ControlsGroup>

          <div className="w-px h-3.5 bg-border-default mx-1 shrink-0" />

          {/* Document Structure & Lists */}
          <RichTextEditor.ControlsGroup>
            <RichTextEditor.BulletList />
            <RichTextEditor.OrderedList />
            <RichTextEditor.Blockquote />
            <RichTextEditor.Hr />
          </RichTextEditor.ControlsGroup>

          <div className="w-px h-3.5 bg-border-default mx-1 shrink-0" />

          {/* Text Alignment */}
          <RichTextEditor.ControlsGroup>
            <RichTextEditor.AlignLeft />
            <RichTextEditor.AlignCenter />
            <RichTextEditor.AlignRight />
          </RichTextEditor.ControlsGroup>

          <div className="w-px h-3.5 bg-border-default mx-1 shrink-0" />

          {/* Links */}
          <RichTextEditor.ControlsGroup>
            <RichTextEditor.Link />
            <RichTextEditor.Unlink />
          </RichTextEditor.ControlsGroup>

          <div className="w-px h-3.5 bg-border-default mx-1 shrink-0" />

          {/* Clear & History */}
          <RichTextEditor.ControlsGroup>
            <RichTextEditor.ClearFormatting />
            <RichTextEditor.Undo />
            <RichTextEditor.Redo />
          </RichTextEditor.ControlsGroup>
        </RichTextEditor.Toolbar>

        <RichTextEditor.Content
          className="[&_.tiptap]:outline-none [&_.tiptap_h1]:text-base [&_.tiptap_h1]:font-bold [&_.tiptap_h1]:text-text-dark [&_.tiptap_h1]:mt-4 [&_.tiptap_h1]:mb-2 [&_.tiptap_h2]:text-sm [&_.tiptap_h2]:font-bold [&_.tiptap_h2]:text-text-dark [&_.tiptap_h2]:mt-3 [&_.tiptap_h2]:mb-1.5 [&_.tiptap_h3]:text-xs [&_.tiptap_h3]:font-semibold [&_.tiptap_h3]:text-text-dark [&_.tiptap_h3]:mt-2.5 [&_.tiptap_h3]:mb-1 [&_.tiptap_p]:mb-2 [&_.tiptap_ul]:list-disc [&_.tiptap_ul]:pl-5 [&_.tiptap_ul]:mb-2 [&_.tiptap_ol]:list-decimal [&_.tiptap_ol]:pl-5 [&_.tiptap_ol]:mb-2 [&_.tiptap_blockquote]:border-l-2 [&_.tiptap_blockquote]:border-border-default [&_.tiptap_blockquote]:pl-3 [&_.tiptap_blockquote]:italic [&_.tiptap_blockquote]:text-text-muted [&_.tiptap_blockquote]:my-2.5 [&_.tiptap_hr]:my-3 [&_.tiptap_hr]:border-border-default [&_.tiptap_code]:bg-surface-primary [&_.tiptap_code]:px-1.5 [&_.tiptap_code]:py-0.5 [&_.tiptap_code]:rounded-4 [&_.tiptap_code]:text-xs [&_.tiptap_code]:font-mono [&_.tiptap_pre]:bg-surface-primary [&_.tiptap_pre]:border [&_.tiptap_pre]:border-border-default [&_.tiptap_pre]:rounded-8 [&_.tiptap_pre]:p-3 [&_.tiptap_pre]:my-2 [&_.tiptap_pre]:font-mono [&_.tiptap_pre]:text-xs"
        />
      </RichTextEditor>
    </div>
  );
};

export default LegalDocRichEditor;
