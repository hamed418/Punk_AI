'use client';
import { AlertTriangle, Check, Copy, Pencil, RotateCcw, Undo2, X } from 'lucide-react';
import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { MessageBlock } from '@/types/chat';
import { Box, Text, Textarea } from '@mantine/core';
import { modals } from '@mantine/modals';
import Image from 'next/image';
import { motion } from 'framer-motion';
import PunkSymbolsLogo from '../../../../../components/PunkSymbolsLogo';
import { ThinkingSection } from './ThinkingSection';
import { isWidgetAnswer, useChat } from '@/contexts/ChatContext';
import { rewindImpact } from '@/lib/rewind';

export const SingleAgentLogo = ({
  index,
  scale = 0.4,
}: {
  index: number;
  scale?: number;
}) => {
  return (
    <div
      style={{ width: 64 * scale, height: 64 * scale }}
      className="relative shrink-0 overflow-hidden rounded-full"
    >
      <Box
        className="absolute top-0 left-0 flex origin-top-left items-center justify-start pl-6"
        style={{ transform: `scale(${scale})` }}
      >
        {index === 1 && <PunkSymbolsLogo />}
        {index === 2 && (
          <PunkSymbolsLogo
            hearDarkFill="#1784A7"
            hearLightFill="#26A2C1"
            hearStripesFill="#ffffff"
            faceBodyFill="#FFE8C7"
            bodyLightFill="#D5D5D5"
            bodyDarkFill="#BEBEBE"
          />
        )}
        {index === 3 && (
          <PunkSymbolsLogo
            hearDarkFill="#50B820"
            hearLightFill="#83EF39"
            faceBodyFill="#8563A2"
            bodyLightFill="#2E1936"
            bodyDarkFill="#2B1732"
          />
        )}
        {index >= 4 && (
          <PunkSymbolsLogo
            hearDarkFill="#B40B28"
            hearLightFill="#ED134F"
            faceBodyFill="#FFE8C7"
            bodyDarkFill="#07510C"
            bodyLightFill="#107138"
          />
        )}
      </Box>
    </div>
  );
};

export const AgentLogoStack = ({
  count,
  animated = false,
  scale = 0.4,
}: {
  count: number;
  animated?: boolean;
  scale?: number;
}) => {
  const unscaledWidth = 64 + Math.max(0, count - 1) * 40;

  return (
    <div
      style={{ width: unscaledWidth * scale, height: 64 * scale }}
      className="relative shrink-0"
    >
      <Box
        className="absolute top-0 left-0 flex origin-top-left items-center justify-start pl-6"
        style={{ transform: `scale(${scale})` }}
      >
        <PunkSymbolsLogo className="z-4" />
        {count >= 2 &&
          (animated ? (
            <motion.div
              initial={{ opacity: 0, x: -20, width: 0, minWidth: 0 }}
              animate={{ opacity: 1, x: 0, width: 40 }}
              transition={{ delay: 0.2 }}
              className="z-3"
            >
              <PunkSymbolsLogo
                hearDarkFill="#1784A7"
                hearLightFill="#26A2C1"
                hearStripesFill="#ffffff"
                faceBodyFill="#FFE8C7"
                bodyLightFill="#D5D5D5"
                bodyDarkFill="#BEBEBE"
              />
            </motion.div>
          ) : (
            <div className="z-3" style={{ width: 40 }}>
              <PunkSymbolsLogo
                hearDarkFill="#1784A7"
                hearLightFill="#26A2C1"
                hearStripesFill="#ffffff"
                faceBodyFill="#FFE8C7"
                bodyLightFill="#D5D5D5"
                bodyDarkFill="#BEBEBE"
              />
            </div>
          ))}
        {count >= 3 &&
          (animated ? (
            <motion.div
              initial={{ opacity: 0, x: -20, width: 0, minWidth: 0 }}
              animate={{ opacity: 1, x: 0, width: 40 }}
              transition={{ delay: 0.4 }}
              className="z-2"
            >
              <PunkSymbolsLogo
                hearDarkFill="#50B820"
                hearLightFill="#83EF39"
                faceBodyFill="#8563A2"
                bodyLightFill="#2E1936"
                bodyDarkFill="#2B1732"
              />
            </motion.div>
          ) : (
            <div className="z-2" style={{ width: 40 }}>
              <PunkSymbolsLogo
                hearDarkFill="#50B820"
                hearLightFill="#83EF39"
                faceBodyFill="#8563A2"
                bodyLightFill="#2E1936"
                bodyDarkFill="#2B1732"
              />
            </div>
          ))}
        {count >= 4 &&
          (animated ? (
            <motion.div
              initial={{ opacity: 0, x: -20, width: 0, minWidth: 0 }}
              animate={{ opacity: 1, x: 0, width: 40 }}
              transition={{ delay: 0.6 }}
              className="z-1"
            >
              <PunkSymbolsLogo
                hearDarkFill="#B40B28"
                hearLightFill="#ED134F"
                faceBodyFill="#FFE8C7"
                bodyDarkFill="#07510C"
                bodyLightFill="#107138"
              />
            </motion.div>
          ) : (
            <div className="z-1" style={{ width: 40 }}>
              <PunkSymbolsLogo
                hearDarkFill="#B40B28"
                hearLightFill="#ED134F"
                faceBodyFill="#FFE8C7"
                bodyDarkFill="#07510C"
                bodyLightFill="#107138"
              />
            </div>
          ))}
      </Box>
    </div>
  );
};

interface MessageBlockUIProps {
  block: MessageBlock;
  /** Last block in the transcript — only there can an answer be rewound. */
  /** An assistant turn before this answer carries a checkpoint to fork from. */
  canRewind?: boolean;
  /** Messages after this answer — what changing it will discard. */
  laterCount?: number;
  /** Keep the Edit / Change action visible instead of revealing it on hover. */
  emphasizeActions?: boolean;
  /** On the newest assistant reply: the answer Redo should re-send. */
  retryFor?: { id: string; content: string; laterCount?: number } | null;
}

export const MessageBlockUI: React.FC<MessageBlockUIProps> = ({
  block,
  canRewind = false,
  laterCount = 0,
  emphasizeActions = false,
  retryFor = null,
}) => {
  const { canUndo, retrySend, rewindTo, streaming } = useChat();
  const isAI = block.role !== 'user';
  const isStreaming = block.status === 'streaming';
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(block.content);

  const widgetAnswer = isWidgetAnswer(block.content || '');
  // The server never took this one: no row, no checkpoint, nothing to rewind to.
  const failed = block.status === 'failed';
  // canUndo is the global publish kill-switch; canRewind is per-message.
  const rewindable = canRewind && canUndo && !streaming && !failed;

  const submitEdit = () => {
    const next = draft.trim();
    setEditing(false);
    if (!next || next === block.content) return;
    void rewindTo(block.id, next);
  };

  // Rewinding deletes this answer and everything after it, on the server too —
  // one click on "Change" must not do that unannounced, and it must say what it costs.
  const confirmChangeAnswer = () =>
    modals.openConfirmModal({
      title: 'Change this answer?',
      children: (
        <Text size="sm">
          {rewindImpact(laterCount)} Punk will ask this question again.
        </Text>
      ),
      labels: { confirm: 'Change answer', cancel: 'Keep it' },
      onConfirm: () => void rewindTo(block.id),
    });

  const confirmRedo = () => {
    if (!retryFor) return;
    modals.openConfirmModal({
      title: 'Run this step again?',
      children: (
        <Text size="sm">
          {rewindImpact(retryFor.laterCount ?? 0)} It will use the same answer.
        </Text>
      ),
      labels: { confirm: 'Redo step', cancel: 'Cancel' },
      onConfirm: () => void rewindTo(retryFor.id, retryFor.content),
    });
  };

  // Action rows are hover-revealed — except where hover doesn't exist (touch), and
  // on the newest rewindable answer, so the feature is discoverable at all.
  const actionRowGrid = (always: boolean) =>
    `grid transition-all duration-200 ease-in-out ${
      always
        ? 'grid-rows-[1fr]'
        : 'grid-rows-[0fr] group-hover:grid-rows-[1fr] [@media(hover:none)]:grid-rows-[1fr]'
    }`;
  const actionRowFade = (always: boolean) =>
    `flex items-center transition-opacity duration-150 ${
      always
        ? 'opacity-100'
        : 'opacity-0 group-hover:opacity-100 group-hover:delay-100 [@media(hover:none)]:opacity-100'
    }`;

  const handleCopy = async () => {
    if (!block.content) return;
    try {
      await navigator.clipboard.writeText(block.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy text: ', err);
    }
  };

  const editPart = (
    <div className="flex w-full flex-col gap-2">
      <Textarea
        autosize
        minRows={2}
        maxRows={12}
        value={draft}
        onChange={(e) => setDraft(e.currentTarget.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            submitEdit();
          }
          if (e.key === 'Escape') setEditing(false);
        }}
        autoFocus
        classNames={{
          input:
            'text-primary-text bg-transparent! border border-stroke-widget rounded-xl',
        }}
      />
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={submitEdit}
          disabled={!draft.trim()}
          className="bg-primary-bg/10 text-primary-text hover:bg-primary-bg/20 cursor-pointer rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40"
        >
          Save &amp; submit
        </button>
        <button
          type="button"
          onClick={() => setEditing(false)}
          className="text-muted-foreground hover:bg-muted hover:text-foreground flex cursor-pointer items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium transition-colors"
        >
          <X size={14} />
          Cancel
        </button>
      </div>
      <Text fz={11} className="text-secondary-text/70">
        {rewindImpact(laterCount)}
      </Text>
    </div>
  );

  const mainContentPart = (
    <div
      className={`max-w-full min-w-0 ${isAI ? 'text-foreground/90 text-md w-full leading-relaxed font-medium tracking-tight' : 'font-inter text-md text-primary-text leading-6 font-normal tracking-normal'}`}
    >
      {isStreaming && !block.content ? null : isAI ? (
        <div
          className={`chat-markdown w-fit max-w-207.5 ${isStreaming ? 'streaming-cursor' : ''}`}
        >
          <StreamingMarkdown
            content={block.content}
            isStreaming={isStreaming}
          />
        </div>
      ) : (
        <div className="max-w-full min-w-0 text-left wrap-break-word whitespace-pre-wrap">
          {(() => {
            let displayContent: React.ReactNode = block.content;

            // ── Q/A wrapper detection (split-based, regex-free for reliability) ──
            // Widget widgets send: "Q: <prompt>\nA: <answer>"
            // We split on the FIRST "\nA:" occurrence so that the answer part
            // can be any string (plain text, JSON, etc.) without worrying about
            // regex flags or dot-vs-newline edge cases.
            const qaIdx = block.content.indexOf('\nA:');
            const isQA = block.content.startsWith('Q:') && qaIdx !== -1;

            // Strip the AI-suggested hint line (e.g. "_Suggested: **ai_suggested** — or enter your own value._")
            // Also strip parenthetical range-hint lines (e.g. "(50–100 m = inside the venue · 200–500 m = nearby foot traffic)")
            const stripSuggested = (text: string) =>
              text
                .split('\n')
                .filter(
                  (line) =>
                    !line.trim().match(/^_Suggested:/i) &&
                    !line.trim().match(/^_?Suggested by AI/i) &&
                    !line.trim().match(/^\(.*=.*\)/)
                )
                .join('\n')
                .trim();

            const questionText = isQA
              ? stripSuggested(block.content.slice(2, qaIdx).trim()) // everything between Q: and \nA:
              : '';
            const answerRawText = isQA
              ? block.content.slice(qaIdx + 3).trimStart() // everything after "\nA:"
              : block.content;
            const answerRaw = answerRawText
              ? answerRawText.charAt(0).toUpperCase() + answerRawText.slice(1)
              : answerRawText;

            try {
              // Only attempt JSON parse when the answer looks like an object/array
              if (
                answerRaw.trimStart().startsWith('{') ||
                answerRaw.trimStart().startsWith('[')
              ) {
                const parsed = JSON.parse(answerRaw);

                // Audience layer builder commit — the user's own filter edit,
                // sent structured so it can't be misread. Show it as prose.
                if (parsed.action === 'audience_filter_patch') {
                  displayContent = (
                    <div className="flex flex-col gap-0.5">
                      <span>Q: {questionText || 'Audience'}</span>
                      <span>A: Adjusted who the audience includes</span>
                    </div>
                  );
                } else if (parsed.start && parsed.end) {
                  // Date-range payload
                  const prefix = isQA ? '' : '';
                  displayContent =
                    prefix +
                    `📅 Campaign set from ${parsed.start} to ${parsed.end === 'ongoing' ? 'Ongoing' : parsed.end}`;
                }
                // ── Map-pin payload: {lat, lng, place/name} ──────────────────────────
                else if (
                  typeof parsed.lat === 'number' &&
                  typeof parsed.lng === 'number' &&
                  (typeof parsed.place === 'string' ||
                    typeof parsed.name === 'string')
                ) {
                  displayContent = (
                    <div className="flex flex-col gap-0.5">
                      <span>
                        Q:{' '}
                        {questionText || 'Pin your target location on the map'}
                      </span>
                      <span>A: {parsed.place || parsed.name}</span>
                    </div>
                  );
                }
                // ── Maid tuning payload: {poi_radius_m?, lookback_days?} ───────
                // Sent bare (no "Q:...A:" wrap) by WidgetPoiRadiusPicker's
                // Generate Audience / Confirm Settings buttons — see that
                // component's `confirmPayload`. Either key can be absent
                // (radius-only / lookback-only re-ask variants).
                else if (
                  typeof parsed.poi_radius_m === 'number' ||
                  typeof parsed.lookback_days === 'number'
                ) {
                  const answerParts: string[] = [];
                  if (typeof parsed.poi_radius_m === 'number') {
                    answerParts.push(`Radius selected ${parsed.poi_radius_m}m`);
                  }
                  if (typeof parsed.lookback_days === 'number') {
                    answerParts.push(`Lookback ${parsed.lookback_days} days`);
                  }
                  displayContent = (
                    <div className="flex flex-col gap-0.5">
                      <span>Q: {questionText || 'Audience targeting settings'}</span>
                      <span>A: {answerParts.join(' and ')}</span>
                    </div>
                  );
                }
                // ── POI confirmation payload: {confirm, added[], removed[]} ────
                else if (
                  typeof parsed.confirm === 'boolean' &&
                  (Array.isArray(parsed.added) || Array.isArray(parsed.removed))
                ) {
                  const fmt = (p: { name?: string }) =>
                    `• ${p.name || 'Selected location'}`;
                  const added = (parsed.added || []) as Array<{
                    name?: string;
                  }>;
                  const removed = (parsed.removed || []) as Array<{
                    name?: string;
                  }>;
                  const answerLines = ['Confirm'];
                  if (added.length)
                    answerLines.push(
                      `Added (${added.length}): ${added.map(fmt).join(', ')}`
                    );
                  if (removed.length)
                    answerLines.push(
                      `Removed (${removed.length}): ${removed.map(fmt).join(', ')}`
                    );
                  displayContent = (
                    <div className="flex flex-col gap-0.5">
                      <span>Q: {questionText || 'Locations Found'}</span>
                      <span>A: {answerLines.join(' ')}</span>
                    </div>
                  );
                }
                // ── Creative Campaign payload ──────────────────────────────────
                else if (
                  'cta' in parsed &&
                  'headline' in parsed &&
                  'body' in parsed
                ) {
                  displayContent = (
                    <div className="flex flex-col gap-2">
                      <div className="flex flex-col gap-0.5">
                        <span>
                          Q:{' '}
                          {questionText ||
                            'Please confirm your campaign copy and creatives.'}
                        </span>
                        <span>
                          A:
                          {parsed.headline ? (
                            <>
                              <br />
                              <b>Headline:</b> {parsed.headline}
                            </>
                          ) : null}
                          {parsed.body ? (
                            <>
                              <br />
                              <b>Body Copy:</b> {parsed.body}
                            </>
                          ) : null}
                          {parsed.cta ? (
                            <>
                              <br />
                              <b>Call to Action:</b>{' '}
                              {parsed.cta.replace(/_/g, ' ')}
                            </>
                          ) : null}
                          {!parsed.headline &&
                            !parsed.body &&
                            !parsed.cta &&
                            ' Assets uploaded successfully.'}
                        </span>
                      </div>
                      {parsed.media_urls && parsed.media_urls.length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-2">
                          {parsed.media_urls.map((url: string, i: number) => {
                            if (!url) return null;
                            const isVideo =
                              url.toLowerCase().endsWith('.mp4') ||
                              url.toLowerCase().endsWith('.webm');
                            return (
                              <div
                                key={i}
                                className="h-24 w-24 shrink-0 overflow-hidden rounded-xl border border-white/10"
                              >
                                {isVideo ? (
                                  <video
                                    src={url}
                                    className="h-full w-full object-cover"
                                    autoPlay
                                    loop
                                    muted
                                    playsInline
                                  />
                                ) : (
                                  <img
                                    src={url}
                                    alt={`Asset ${i}`}
                                    className="h-full w-full object-cover"
                                  />
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                }
                // ── File upload payload ─────────────────────────────────────────
                else if (parsed.fileUploaded) {
                  displayContent = (
                    <div className="flex flex-col gap-3">
                      {parsed.file_path && (
                        <div className="overflow-hidden rounded-2xl border border-white/10">
                          <Image
                            width={100}
                            height={100}
                            src={parsed.file_path}
                            alt={parsed.name || 'Uploaded file'}
                            className="max-h-60 w-auto object-cover"
                          />
                        </div>
                      )}
                      <Text fw={400} fz={14}>
                        📎 File Uploaded: {parsed.name || 'Success'}
                      </Text>
                    </div>
                  );
                }
                // ── Form submission payload: {values: {...}} ──────────────────
                else if (parsed.values && typeof parsed.values === 'object') {
                  const val = parsed.values as Record<string, unknown>;
                  const parts = [
                    val.business_name,
                    val.business_context,
                    val.objective,
                  ]
                    .filter(Boolean)
                    .map(String);
                  const answerText =
                    parts.length > 0
                      ? parts.join(' • ')
                      : JSON.stringify(val);
                  displayContent = (
                    <div className="flex flex-col gap-0.5">
                      <span>Q: {questionText || 'Campaign Setup'}</span>
                      <span>A: {answerText}</span>
                    </div>
                  );
                }
                else if (parsed.action || parsed.spec) {
                  displayContent =
                    parsed.action === 'save'
                      ? 'Campaign plan saved'
                      : 'Campaign plan submitted';
                } else if (isQA) {
                  displayContent = (
                    <div className="flex flex-col gap-0.5">
                      <span>Q: {questionText}</span>
                      <span>A: {answerRaw}</span>
                    </div>
                  );
                }
              } else if (isQA) {
                // Plain-text Q/A (e.g. radius, text input) — strip suggested hint and show cleaned content
                displayContent = (
                  <div className="flex flex-col gap-0.5">
                    <span>Q: {questionText}</span>
                    <span>A: {answerRaw}</span>
                  </div>
                );
              }
            } catch {
              // JSON parse failed — fall back to raw content
            }

            return displayContent;
          })()}
        </div>
      )}
    </div>
  );



  // A rewind's status line: a quiet divider, not a chat message — no copy / redo
  // actions, and it never reads as a reply.
  if (block.kind === 'rewind_marker') {
    return (
      <div
        role="status"
        className="animate-fade-in font-body mx-auto my-5 flex w-full max-w-207.5 items-center gap-3"
      >
        <span className="border-stroke-widget flex-1 border-t" />
        <Text fz={12} className="text-secondary-text shrink-0 text-center">
          {block.content}
        </Text>
        <span className="border-stroke-widget flex-1 border-t" />
      </div>
    );
  }

  if (!isAI) {
    return (
      <div className="group animate-fade-in font-body mx-auto my-10 flex w-full max-w-207.5 min-w-0 justify-end">
        <div className="flex max-w-75 min-w-0 flex-col items-end md:max-w-140">
          <div
            className={`bg-user-chat-bubble light:shadow-[0px_-1px_0px_0px_#AEAEAE66_inset,0px_3px_0px_0px_#FFFFFF73_inset,0px_8px_24px_0px_#CACACA80] light:backdrop-blur-2xl w-fit max-w-full min-w-0 rounded-2xl p-4 wrap-break-word shadow-[0px_8px_24px_0px_#00000080,0px_-1px_0px_0px_#00000066_inset,0px_1px_0px_0px_#FFFFFF1F_inset] backdrop-blur-[12.7px] ${failed ? 'border border-red-500/50 opacity-70' : ''}`}
          >
            <Text
              fz={15}
              fw={400}
              component="div"
              className="max-w-full min-w-0"
            >
              {editing ? editPart : mainContentPart}
            </Text>
          </div>
          {/* Not hover-gated: a message that never sent has to say so on its own. */}
          {failed && (
            <div className="mt-1.5 flex items-center gap-2">
              <AlertTriangle size={13} className="text-red-500" />
              <Text fz={12} className="text-red-500">
                Not sent
              </Text>
              <button
                type="button"
                onClick={() => void retrySend(block.id)}
                disabled={streaming}
                className="text-muted-foreground hover:bg-muted hover:text-foreground flex cursor-pointer items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40"
                title="Send this message again"
              >
                <RotateCcw size={13} />
                <Text fz={12}>Retry</Text>
              </button>
            </div>
          )}
          {block.edited && !editing && (
            <Text fz={11} className="text-secondary-text/70 mt-1">
              Edited
            </Text>
          )}
          {block.content && !editing && !failed && (
            <div className={actionRowGrid(emphasizeActions && rewindable)}>
              <div className="overflow-hidden">
                <div className={actionRowFade(emphasizeActions && rewindable)}>
                  <button
                    type="button"
                    onClick={handleCopy}
                    className="text-muted-foreground hover:bg-muted hover:text-foreground flex cursor-pointer items-center gap-1.5 rounded-lg p-1.5 text-xs font-medium transition-colors"
                    title="Copy message"
                  >
                    {copied ? (
                      <>
                        <Check size={14} className="text-green-500" />
                        <Text fz={12}>Copied!</Text>
                      </>
                    ) : (
                      <>
                        <Copy size={14} />
                        <Text fz={12}>Copy</Text>
                      </>
                    )}
                  </button>
                  {rewindable && !widgetAnswer && (
                    <button
                      type="button"
                      onClick={() => {
                        setDraft(block.content);
                        setEditing(true);
                      }}
                      className="text-muted-foreground hover:bg-muted hover:text-foreground flex cursor-pointer items-center gap-1.5 rounded-lg p-1.5 text-xs font-medium transition-colors"
                      title="Edit this message and re-run from here"
                    >
                      <Pencil size={14} />
                      <Text fz={12}>Edit</Text>
                    </button>
                  )}
                  {rewindable && widgetAnswer && (
                    <button
                      type="button"
                      onClick={confirmChangeAnswer}
                      className="text-muted-foreground hover:bg-muted hover:text-foreground flex cursor-pointer items-center gap-1.5 rounded-lg p-1.5 text-xs font-medium transition-colors"
                      title="Go back and answer this step again"
                    >
                      <Undo2 size={14} />
                      <Text fz={12}>Change</Text>
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="group font-body mx-auto mb-3 flex w-full max-w-207.5 justify-start">
      <div className="flex w-full min-w-0 flex-col gap-6">
        <div className="w-full">
          {isAI && <ThinkingSection thinking={block.thinking} isStreaming={isStreaming} />}
          {mainContentPart}
          {isAI && block.content && !isStreaming && (
            <div className={actionRowGrid(false)}>
              <div className="overflow-hidden">
                <div className={actionRowFade(false)}>
                  <button
                    type="button"
                    onClick={handleCopy}
                    className="text-muted-foreground hover:bg-muted hover:text-foreground flex cursor-pointer items-center gap-1.5 rounded-lg p-1.5 text-xs font-medium transition-colors"
                    title="Copy response"
                  >
                    {copied ? (
                      <>
                        <Check size={14} className="text-green-500" />
                        <Text fz={12}>Copied!</Text>
                      </>
                    ) : (
                      <>
                        <Copy size={14} />
                        <Text fz={12}>Copy</Text>
                      </>
                    )}
                  </button>
                  {retryFor && canUndo && !streaming && (
                    <button
                      type="button"
                      onClick={confirmRedo}
                      className="text-muted-foreground hover:bg-muted hover:text-foreground flex cursor-pointer items-center gap-1.5 rounded-lg p-1.5 text-xs font-medium transition-colors"
                      title="Run this step again with the same answer"
                    >
                      <RotateCcw size={14} />
                      <Text fz={12}>Redo step</Text>
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const StreamingMarkdown = ({
  content,
}: {
  content: string;
  isStreaming: boolean;
}) => {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        h1: ({ children }) => (
          <h1 className="text-primary-text mt-6 mb-4 text-3xl font-bold">
            {children}
          </h1>
        ),
        h2: ({ children }) => (
          <h2 className="text-primary-text mt-5 mb-3 text-2xl font-bold">
            {children}
          </h2>
        ),
        h3: ({ children }) => (
          <h3 className="text-primary-text mt-4 mb-2 text-xl font-bold">
            {children}
          </h3>
        ),
        h4: ({ children }) => (
          <h4 className="text-primary-text mt-3 mb-2 text-lg font-bold">
            {children}
          </h4>
        ),
        p: ({ children }) => (
          <Text fw={400} fz={15} className="mb-4 leading-relaxed light:text-primary-text/90! last:mb-0">
            {children}
          </Text>
        ),
        ul: ({ children }) => (
          <ul className="mb-4 list-disc space-y-1 light:text-primary-text/90! pl-6 text-[15px]">
            {children}
          </ul>
        ),
        ol: ({ children }) => (
          <ol className="mb-4 list-decimal space-y-1 pl-6">{children}</ol>
        ),
        li: ({ children }) => <li className="leading-relaxed light:text-primary-text/90!">{children}</li>,
        blockquote: ({ children }) => (
          <blockquote className="border-muted text-secondary-text my-4 border-l-4 pl-4 italic">
            {children}
          </blockquote>
        ),
        pre: ({ children }) => (
          <pre className="custom-scrollbar light:text-primary-text/90! my-4 overflow-x-auto rounded-lg border border-white/10 bg-zinc-950 p-4 text-sm text-zinc-50 shadow-sm">
            {children}
          </pre>
        ),
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        code: ({ className, children, ...props }: any) => {
          const isInline =
            typeof children === 'string' && !children.includes('\n');
          return isInline ? (
            <code
              className="bg-muted/50 text-primary-text rounded-md px-1.5 py-0.5 font-mono text-[0.9em]"
              {...props}
            >
              {children}
            </code>
          ) : (
            <code className={className} {...props}>
              {children}
            </code>
          );
        },
        a: ({ href, children }) => (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-blue-500 transition-colors hover:text-blue-600 hover:underline"
          >
            {children}
          </a>
        ),
        table: ({ children }) => (
          <div className="border-stroke-widget my-4 overflow-x-auto rounded-lg border">
            <table className="w-full border-collapse text-sm">{children}</table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="bg-muted/30">{children}</thead>
        ),
        th: ({ children }) => (
          <th className="border-stroke-widget text-primary-text border-b px-4 py-3 text-left font-semibold">
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td className="border-stroke-widget text-secondary-text border-b px-4 py-3">
            {children}
          </td>
        ),
        strong: ({ children }) => (
          <strong className="text-primary-text font-semibold">
            {children}
          </strong>
        ),
        hr: () => <hr className="border-stroke-widget my-6 border-t" />,
      }}
    >
      {content}
    </ReactMarkdown>
  );
};
