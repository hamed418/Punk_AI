'use client';
import { uploadMediaAction } from '@/actions/chat.actions';
import { useChat } from '@/contexts/ChatContext';
import type { PendingActionBlock } from '@/types/chat';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Check,
  ChevronDown,
  ChevronUp,
  Image,
  Info,
  Loader2,
  Video,
} from 'lucide-react';
import type React from 'react';
import { useMemo, useRef, useState } from 'react';
import WidgetLayout from './WidgetLayout';
import WidgetHeaderV2 from '@/components/WidgetHeaderV2';
import GetHeaderHelper from '@/utils/GetHeaderHelper';
import { getWidgetHeader, getWidgetSubheader } from '@/utils';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';
import { Text } from '@mantine/core';
// import { BlobOverlay } from '@/components/MouseFollowBlob'
// import { useMouseFollowBlob } from '@/hooks/useMouseFollowBlob'

interface WidgetFileUploadProps {
  content: PendingActionBlock['content'];
  onConfirm?: (value: string) => void;
  isLatest?: boolean;
  showLogo?: boolean;
  userResponse?: string | null;
}

export default function WidgetFileUploadV2({
  content,
  onConfirm,
  isLatest = true,
  showLogo = false,
  userResponse = null,
}: WidgetFileUploadProps) {
  const { conversation, activeThreadId } = useChat();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const userResponseFromHistory = useMemo(() => {
    if (!conversation) return null;
    const index = conversation.blocks.findIndex(
      (b) =>
        b.type === 'pending_action' &&
        b.content?.action_type === 'file_upload' &&
        b.content?.field === content.field
    );
    if (index === -1) return null;
    const nextBlock = conversation.blocks[index + 1];
    if (nextBlock?.type === 'message' && nextBlock.role === 'user') {
      return nextBlock.content;
    }
    return null;
  }, [conversation, content]);

  const initialUserResponse = userResponseFromHistory || userResponse;

  const parsedInitial = useMemo(() => {
    if (!initialUserResponse) return null;
    try {
      const parsed = JSON.parse(initialUserResponse);
      if (parsed && parsed.fileUploaded) return parsed;
    } catch {
      // Ignore JSON parse error
    }
    return null;
  }, [initialUserResponse]);

  const [files, setFiles] = useState<
    { file?: File; preview: string; name: string }[]
  >(() => {
    if (parsedInitial) {
      return [
        {
          name: parsedInitial.name || 'uploaded_file',
          preview: parsedInitial.file_path || '',
        },
      ];
    }
    return [];
  });
  const [isUploading, setIsUploading] = useState(false);
  const [isUploaded, setIsUploaded] = useState(!!parsedInitial);
  const [isDragging, setIsDragging] = useState(false);
  const [open, setOpen] = useState(isLatest);
  const [prevIsLatest, setPrevIsLatest] = useState(isLatest);
  const [isSubmitted, setIsSubmitted] = useState(!!initialUserResponse);
  const [uploadResult, setUploadResult] = useState<{
    id: string;
    name: string;
    file_path: string;
  } | null>(() => {
    if (parsedInitial) {
      return {
        id: parsedInitial.id || '',
        name: parsedInitial.name || '',
        file_path: parsedInitial.file_path || '',
      };
    }
    return null;
  });
  const abortControllerRef = useRef<AbortController | null>(null);

  const [prevUserResponse, setPrevUserResponse] = useState<string | null>(
    initialUserResponse
  );

  if (conversation && conversation.id === activeThreadId) {
    const effectiveUserResponse = userResponseFromHistory || userResponse;
    if (effectiveUserResponse !== prevUserResponse) {
      setPrevUserResponse(effectiveUserResponse);
      if (effectiveUserResponse) {
        setIsSubmitted(true);
        try {
          const parsed = JSON.parse(effectiveUserResponse);
          if (parsed && parsed.fileUploaded) {
            setIsUploaded(true);
            setFiles([
              {
                name: parsed.name || 'uploaded_file',
                preview: parsed.file_path || '',
              },
            ]);
            setUploadResult({
              id: parsed.id || '',
              name: parsed.name || '',
              file_path: parsed.file_path || '',
            });
          } else {
            setIsUploaded(false);
            setFiles([]);
            setUploadResult(null);
          }
        } catch {
          setIsUploaded(false);
          setFiles([]);
          setUploadResult(null);
        }
      } else {
        setIsSubmitted(false);
        setIsUploaded(false);
        setFiles([]);
        setUploadResult(null);
      }
    }
  }

  if (isLatest !== prevIsLatest) {
    setPrevIsLatest(isLatest);
    if (!isLatest) {
      setOpen(false);
    }
  }

  // Parse prompt to extract title and recommendations
  const { recommendations } = useMemo(() => {
    const lines = content.prompt.split('\n');
    let titleText = '';
    const recs: string[] = [];
    let footerText = '';

    let section: 'title' | 'recs' | 'footer' = 'title';

    lines.forEach((line) => {
      const trimmed = line.trim();
      if (!trimmed) return;

      if (trimmed.toLowerCase().includes('recommended sizes')) {
        section = 'recs';
        return;
      }
      if (trimmed.toLowerCase().includes("type 'skip'")) {
        section = 'footer';
      }

      if (section === 'title') titleText += (titleText ? ' ' : '') + trimmed;
      else if (section === 'recs') {
        if (trimmed.startsWith('•') || trimmed.startsWith('-')) {
          recs.push(trimmed.replace(/^[•-]\s*/, ''));
        } else {
          recs.push(trimmed);
        }
      } else if (section === 'footer') {
        footerText += (footerText ? ' ' : '') + trimmed;
      }
    });

    return { title: titleText, recommendations: recs, footer: footerText };
  }, [content.prompt]);

  const handleUploadClick = () => {
    if (fileInputRef.current && isLatest && !isUploading) {
      fileInputRef.current.click();
    }
  };

  const processFiles = async (selectedFiles: File[]) => {
    if (selectedFiles.length === 0) return;

    const newFiles = selectedFiles.map((file) => ({
      file,
      preview: URL.createObjectURL(file),
      name: file.name,
    }));

    setFiles(newFiles);
    setIsUploading(true);
    setIsSubmitted(false);

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const uploadPromises = selectedFiles.map((file) => {
        const formData = new FormData();
        formData.append('file', file);
        if (activeThreadId) {
          formData.append('thread_id', activeThreadId);
        }
        return uploadMediaAction(formData);
      });

      const actionResults = await Promise.all(uploadPromises);
      // Map Server Action results
      const results = actionResults.map((res) => {
        if (!res.success) throw new Error(res.error);
        return res.data!;
      });

      setIsUploading(false);
      setIsUploaded(true);

      if (results.length > 0) {
        setUploadResult({
          id: results[0].id,
          name: newFiles[0].name,
          file_path: results[0].file_path,
        });
      }
    } catch (error: unknown) {
      if (error instanceof Error && error.name === 'AbortError') {
        console.log('Upload aborted');
        return;
      }
      console.error('Upload failed', error);
      setIsUploading(false);
      alert('Upload failed. Please try again.');
    }
  };

  const handleSubmit = () => {
    if (onConfirm && isLatest && uploadResult && !isSubmitted) {
      setIsSubmitted(true);
      onConfirm(
        JSON.stringify({
          fileUploaded: true,
          id: uploadResult.id,
          name: uploadResult.name,
          file_path: uploadResult.file_path,
        })
      );
    }
  };

  const handleCancelUpload = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setFiles([]);
    setIsUploading(false);
    setIsUploaded(false);
    setIsSubmitted(false);
    setUploadResult(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      processFiles(Array.from(e.target.files));
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    if (isLatest) setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (isLatest && e.dataTransfer.files) {
      processFiles(Array.from(e.dataTransfer.files));
    }
  };

  // const { containerRef, blobX, blobY, opacity, handleMouseMove } =
  //   useMouseFollowBlob()

  return (
    <WidgetLayout mode="single" showLogo={showLogo}>
      <div className="mb-3 transition-opacity duration-300">
        {/* Outer wrapper — tracks mouse and positions blob behind card */}
        <div
          // ref={containerRef}
          // onMouseMove={handleMouseMove}
          className="relative rounded-[30px]"
        >
          {/* Blob sits behind the card so backdrop-blur blurs it naturally */}
          {/* <BlobOverlay blobX={blobX} blobY={blobY} opacity={opacity} /> */}
          {/* Outer card — lighter surface */}
          <motion.div
            layout
            transition={{
              type: 'spring',
              damping: 20,
              stiffness: 300,
              mass: 1,
            }}
            className="animate-fade-up border-stroke-widget! bg-primary-widget! shadow-widget! light:shadow-sm! relative z-10 flex flex-col overflow-hidden rounded-[30px] border! transition-opacity duration-300"
            style={{
              backdropFilter: 'blur(75.9px)',
            }}
          >
            {/* ── Header ── */}
            <button
              type="button"
              onClick={() => setOpen(!open)}
              className={`flex w-full cursor-pointer items-center justify-between px-5 pt-5 pb-4 text-left ${open ? 'border-underline/15 border-b' : 'border-b border-transparent'}`}
            >
              <WidgetHeaderV2
                icon={GetHeaderHelper(content.field || 'file_upload')}
                title={
                  getWidgetHeader(content.field || 'file_upload') ||
                  content.title
                }
                subtitle={
                  userResponse
                    ? userResponse.trim()
                    : content.subtitle ||
                      getWidgetSubheader(content.field || 'file_upload')
                }
              />
              {open ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
            </button>

            {/* ── Body ── */}
            <AnimatePresence initial={false}>
              {open && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2, ease: 'easeInOut' }}
                  className="overflow-hidden"
                >
                  <div className="flex flex-col gap-3 p-3">
                    {/* ── Upload Zone ── */}
                    <AnimatePresence mode="wait">
                      {isUploading ? (
                        <motion.div
                          key="uploading"
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          exit={{ opacity: 0 }}
                          className="border-plus-minus-button-border/40 bg-plus-minus-button-bg/30 hover:border-plus-minus-button-border/80 hover:bg-plus-minus-button-hover! flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed py-10"
                        >
                          <Loader2 className="text-primary-text/50 h-7 w-7 animate-spin" />
                          <div className="text-center">
                            <p className="text-primary-text/70 text-sm font-medium">
                              Uploading Assets…
                            </p>
                            <p className="text-primary-text/35 mt-0.5 text-[11px]">
                              Processing {files.length}{' '}
                              {files.length === 1 ? 'file' : 'files'}
                            </p>
                          </div>
                        </motion.div>
                      ) : isUploaded ? (
                        <motion.div
                          key="uploaded"
                          initial={{ opacity: 0, scale: 0.98 }}
                          animate={{ opacity: 1, scale: 1 }}
                          className="border-plus-minus-button-border/40 bg-plus-minus-button-bg/30 hover:border-plus-minus-button-border/80 hover:bg-plus-minus-button-hover! flex flex-col gap-4 rounded-xl border p-4"
                        >
                          <div className="flex items-center gap-3">
                            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-white/6">
                              <Check className="text-primary-text/60 h-4 w-4" />
                            </div>
                            <div>
                              <p className="text-primary-text/80 text-sm font-semibold">
                                Upload Successful
                              </p>
                              <p className="text-primary-text/35 text-[11px]">
                                Your assets are ready to use
                              </p>
                            </div>
                          </div>
                          <div className="flex flex-wrap gap-3 pt-0.5">
                            {files.map((f) => (
                              <div key={f.name} className="relative h-16 w-16">
                                <div className="h-full w-full overflow-hidden rounded-lg border border-white/10">
                                  {f.preview.startsWith('data:') ||
                                  f.preview.includes('blob:') ||
                                  f.name.match(
                                    /\.(jpg|jpeg|png|gif|webp|svg)/i
                                  ) ||
                                  (f.file &&
                                    f.file.type.startsWith('image')) ? (
                                    <img
                                      src={f.preview}
                                      alt="preview"
                                      className="h-full w-full object-cover"
                                    />
                                  ) : (
                                    <div className="bg-secondary-widget flex h-full w-full items-center justify-center">
                                      <Video className="text-primary-text/40 h-6 w-6" />
                                    </div>
                                  )}
                                </div>
                                <button
                                  type="button"
                                  onClick={handleCancelUpload}
                                  disabled={isSubmitted}
                                  className="bg-primary-widget hover:bg-primary-widget/85 border-stroke-widget text-primary-text! disabled:border-stroke-widget/40 disabled:text-primary-text/30 absolute -top-1.5 -right-1.5 z-10 flex h-5 w-5 cursor-pointer items-center justify-center rounded-full border text-[10px] font-bold shadow-md transition-all disabled:cursor-not-allowed disabled:bg-white/10"
                                  title={
                                    isSubmitted
                                      ? undefined
                                      : 'Cancel and remove upload'
                                  }
                                >
                                  ✕
                                </button>
                              </div>
                            ))}
                          </div>
                        </motion.div>
                      ) : (
                        <motion.div
                          key="idle"
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          className="flex flex-col gap-3"
                        >
                          {/* Dropzone */}
                          <div
                            role="button"
                            tabIndex={0}
                            onDragOver={handleDragOver}
                            onDragLeave={handleDragLeave}
                            onDrop={handleDrop}
                            onClick={handleUploadClick}
                            onKeyDown={(e) =>
                              e.key === 'Enter' && handleUploadClick()
                            }
                            className={`relative flex w-full cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border border-dashed py-10 transition-all duration-200 ${
                              isDragging
                                ? 'border-plus-minus-button-border/60 bg-plus-minus-button-bg/50'
                                : 'border-plus-minus-button-border/40 bg-plus-minus-button-bg/30 hover:border-plus-minus-button-border/80 hover:bg-plus-minus-button-hover!'
                            } ${!isLatest ? 'cursor-not-allowed opacity-50' : ''}`}
                          >
                            <input
                              type="file"
                              ref={fileInputRef}
                              className="hidden"
                              multiple
                              onChange={handleFileChange}
                              disabled={!isLatest}
                              accept="image/*,video/*"
                            />

                            {/* Upload icon circle */}
                            <div className="bg-plus-minus-button-bg! flex h-12 w-12 items-center justify-center rounded-full shadow-sm">
                              <svg
                                width="18"
                                height="18"
                                viewBox="0 0 18 18"
                                fill="none"
                                className="text-primary-text/60"
                              >
                                <path
                                  d="M9 12V3M9 3L5.5 6.5M9 3l3.5 3.5"
                                  stroke="currentColor"
                                  strokeWidth="1.5"
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                />
                                <path
                                  d="M2 13.5v1A1.5 1.5 0 003.5 16h11a1.5 1.5 0 001.5-1.5v-1"
                                  stroke="currentColor"
                                  strokeWidth="1.5"
                                  strokeLinecap="round"
                                />
                              </svg>
                            </div>

                            {/* Text */}
                            <div className="text-center">
                              {isDragging ? (
                                <p className="text-primary-text/60 text-[13px] font-medium">
                                  Drop to upload
                                </p>
                              ) : (
                                <p className="text-primary-text/60 text-[13px] font-medium">
                                  Drag &amp; drop or{' '}
                                  <span className="text-primary-text cursor-pointer underline underline-offset-2">
                                    browse files
                                  </span>
                                </p>
                              )}
                              <p className="text-primary-text/30 mt-1 text-[11px]">
                                PNG, JPG, MP4, MOV supported
                              </p>
                            </div>
                          </div>

                          {/* Recommended Specs */}
                          {recommendations.length > 0 && (
                            <div className="border-stroke-widget bg-primary-widget! shadow-widget my-2 flex flex-col gap-2.5 rounded-2xl border p-4 backdrop-blur-md">
                              <div className="flex items-center gap-2">
                                <Info
                                  size={16}
                                  className="text-primary-text/70 shrink-0"
                                />
                                <Text
                                  fw={600}
                                  fz={13}
                                  className="text-primary-text tracking-wider uppercase"
                                >
                                  Recommended Specs
                                </Text>
                              </div>
                              <div className="flex flex-col gap-2">
                                {recommendations.map((rec, i) => (
                                  <div
                                    key={rec}
                                    className="flex items-center gap-2.5"
                                  >
                                    <div className="text-primary-text/40 shrink-0">
                                      {i === 0 ? (
                                        <Image size={13} />
                                      ) : (
                                        <Video size={13} />
                                      )}
                                    </div>
                                    <p className="text-secondary-text/40 text-[12px] leading-snug">
                                      {rec}
                                    </p>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </motion.div>
                      )}
                    </AnimatePresence>

                    {/* ── Footer ── */}
                    <div className="flex items-center justify-end rounded-full p-0.5">
                      {isUploaded ? (
                        <PrimaryGlassBtn
                          type="button"
                          onClick={handleSubmit}
                          disabled={!isLatest || isUploading || isSubmitted}
                          withArrow={true}
                        >
                          Confirm
                        </PrimaryGlassBtn>
                      ) : (
                        <PrimaryGlassBtn
                          type="button"
                          onClick={handleUploadClick}
                          disabled={!isLatest || isUploading}
                          withArrow={true}
                        >
                          Confirm
                        </PrimaryGlassBtn>
                      )}
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </div>
      </div>
    </WidgetLayout>
  );
}
