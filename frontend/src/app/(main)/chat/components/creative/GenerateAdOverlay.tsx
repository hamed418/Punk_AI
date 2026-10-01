'use client';
import {
  Sparkles,
  Image as ImageIcon,
  Video,
  Loader2,
  X,
  Upload,
  Check,
} from 'lucide-react';
import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Textarea, SegmentedControl, useMantineColorScheme } from '@mantine/core';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';
import SecondaryBtn from '@/components/secondaryBtn';

import {
  generateCreativeAction,
  pollJobStatusAction,
} from '@/actions/creative.actions';
import { uploadMediaAction } from '@/actions/chat.actions';
import type { CreativeAspectRatio, CreativeMedia } from '@/services/creative.service';

export interface GeneratedAsset {
  type: 'image' | 'video';
  name: string;
  url?: string;
  id?: string;
}

interface GenerateAdOverlayProps {
  type: 'image' | 'video';
  threadId: string;
  onClose: () => void;
  /** Every asset the user ticked — an ad carries one image, so several picks
   *  mean several ads (see `addAds` in CampaignEditor). */
  onAdd: (assets: GeneratedAsset[]) => void;
}

type Phase = 'input' | 'generating' | 'done';

const ASPECT_OPTIONS: { label: string; value: CreativeAspectRatio }[] = [
  { label: 'Square 1:1', value: '1:1' },
  { label: 'Portrait 4:5', value: '4:5' },
  { label: 'Landscape 1.91:1', value: '1.91:1' },
  { label: 'Story 9:16', value: '9:16' },
];

/** Concepts rendered per round. */
const VARIANT_COUNT = 3;
/** Rounds a user gets in one modal session — the first batch plus 2 redos. */
const MAX_ROUNDS = 3;

export default function GenerateAdOverlay({
  type,
  threadId,
  onClose,
  onAdd,
}: GenerateAdOverlayProps) {
  const { colorScheme } = useMantineColorScheme();
  const isLight = colorScheme === 'light';
  const isImage = type === 'image';
  const Icon = isImage ? ImageIcon : Video;

  // ── generation controls (image only; harmless for video) ──────────────────
  const [phase, setPhase] = useState<Phase>('input');
  const [prompt, setPrompt] = useState('');
  const [aspect, setAspect] = useState<CreativeAspectRatio>('1:1');
  const [refMediaId, setRefMediaId] = useState<string | null>(null);
  const [refPreview, setRefPreview] = useState<string | null>(null);
  const [refUploading, setRefUploading] = useState(false);

  const [progress, setProgress] = useState(0);
  const [assets, setAssets] = useState<CreativeMedia[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // Rounds burned in THIS modal session. Purely a cost/UX guardrail — the
  // endpoint itself is unmetered, so this is not a security boundary.
  const [round, setRound] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const roundsLeft = MAX_ROUNDS - round;
  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  const onRefFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setRefUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await uploadMediaAction(fd);
      if (res.success && res.data) {
        setRefMediaId(res.data.id);
        setRefPreview(res.data.file_path);
      }
    } finally {
      setRefUploading(false);
      e.target.value = '';
    }
  };

  const startGeneration = async () => {
    if (roundsLeft <= 0) return;
    setPhase('generating');
    setProgress(0);
    setError(null);
    setAssets([]);
    setSelected(new Set());
    setRound((r) => r + 1);

    let progressSim: ReturnType<typeof setInterval> | undefined;
    let pollingInterval: ReturnType<typeof setInterval> | undefined;

    try {
      const res = await generateCreativeAction({
        media_type: type,
        thread_id: threadId,
        variation_hint: prompt.trim() || undefined,
        reference_media_id: refMediaId || undefined,
        aspect_ratio: aspect,
        variant_count: VARIANT_COUNT,
      });

      const jobId = res.job_id;

      progressSim = setInterval(() => {
        setProgress((prev) => Math.min(prev + Math.floor(Math.random() * 5) + 2, 95));
      }, 800);

      pollingInterval = setInterval(async () => {
        try {
          const statusRes = await pollJobStatusAction(jobId);
          const ready =
            statusRes.medias?.length
              ? statusRes.medias
              : statusRes.media
                ? [statusRes.media]
                : [];
          if (statusRes.status === 'ready' && ready.length) {
            clearInterval(pollingInterval);
            clearInterval(progressSim);
            setProgress(100);
            setAssets(ready);
            setSelected(new Set([ready[0].id])); // first is pre-ticked
            setPhase('done');
          } else if (statusRes.status === 'failed') {
            clearInterval(pollingInterval);
            clearInterval(progressSim);
            setError(statusRes.error || 'Generation failed.');
            setRound((r) => r - 1); // a round that produced nothing doesn't count
            setPhase('input');
          }
        } catch (pollErr) {
          console.error(pollErr);
        }
      }, 2500);
    } catch (err) {
      if (progressSim) clearInterval(progressSim);
      if (pollingInterval) clearInterval(pollingInterval);
      setError(err instanceof Error ? err.message : 'Failed to start generation.');
      setRound((r) => r - 1);
      setPhase('input');
    }
  };

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
        className="absolute inset-0 bg-black/80"
        onClick={onClose}
      />

      {/* Modal */}
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 16 }}
        transition={{ duration: 0.25, ease: 'easeOut' }}
        className="text-primary-text relative flex w-full max-w-160 flex-col overflow-hidden rounded-[28px] border"
        style={{
          background: isLight ? 'var(--mantine-color-body)' : '#1C1C1C',
          borderColor: isLight
            ? 'var(--mantine-color-gray-3)'
            : 'rgba(255, 255, 255, 0.15)',
          boxShadow: isLight
            ? '0 8px 40px rgba(0,0,0,0.12)'
            : '0px 8px 32px 0px #00000099, 0px -1px 0px 0px #00000066 inset, 0px 1px 0px 0px #FFFFFF1F inset',
        }}
      >
        {/* Header */}
        <div
          className="flex shrink-0 items-center justify-between border-b px-5 py-4"
          style={{
            borderColor: isLight
              ? 'var(--mantine-color-gray-2)'
              : 'rgba(255, 255, 255, 0.08)',
          }}
        >
          <div className="flex items-center gap-2">
            <div
              className={`flex h-6 w-6 items-center justify-center rounded-md border ${
                isLight ? 'border-stroke-widget bg-white' : 'border-white/10 bg-white/5'
              }`}
            >
              <Sparkles size={13} className="text-secondary-text" />
            </div>
            <span className="text-secondary-text/90 text-[13px] font-medium">
              Punk ideas · Create asset
            </span>
          </div>
          <button
            onClick={onClose}
            className={`flex h-7 w-7 items-center justify-center rounded-full transition-colors ${
              isLight ? 'hover:bg-black/5' : 'hover:bg-white/10'
            }`}
          >
            <X size={16} className="text-secondary-text" />
          </button>
        </div>

        <div className="custom-textarea-scrollbar flex max-h-[calc(100vh-160px)] flex-1 flex-col overflow-y-auto px-6 py-6">
          <AnimatePresence mode="wait">
            {/* ── INPUT ─────────────────────────────────────────────────── */}
            {phase === 'input' && (
              <motion.div
                key="input"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.2 }}
                className="flex w-full flex-col gap-4"
              >
                <div>
                  <h3 className="text-primary-text mb-1 text-[16px] font-semibold">
                    Describe the creative
                  </h3>
                  <p className="text-secondary-text/70 text-[13px] leading-relaxed">
                    Give direction and (optionally) a reference image. Leave blank to let
                    Punk decide.
                  </p>
                </div>

                {/* Direction prompt */}
                <Textarea
                  label={
                    <span className="text-secondary-text mb-1 text-[12px]">
                      Direction prompt
                    </span>
                  }
                  placeholder="e.g. warm morning light, hands holding a latte, cozy café counter"
                  value={prompt}
                  onChange={(e) => setPrompt(e.currentTarget.value)}
                  autosize
                  minRows={2}
                  maxRows={4}
                  classNames={{
                    input:
                      'bg-transparent! border-underline/15! text-primary-text! rounded-xl! text-[13px]!',
                  }}
                />

                {/* Reference image */}
                <div>
                  <div className="text-secondary-text mb-1 text-[12px]">
                    Reference image (optional)
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="border-underline/15 flex h-20 w-20 shrink-0 items-center justify-center overflow-hidden rounded-xl border">
                      {refPreview ? (
                        <img
                          src={refPreview}
                          alt="reference"
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <ImageIcon size={20} className="text-secondary-text/40" />
                      )}
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <label className="border-stroke-widget text-secondary-text/90 flex cursor-pointer items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] hover:bg-white/5">
                        {refUploading ? (
                          <Loader2 size={13} className="animate-spin" />
                        ) : (
                          <Upload size={13} />
                        )}
                        {refMediaId ? 'Replace image' : 'Upload image'}
                        <input
                          type="file"
                          accept="image/*"
                          className="hidden"
                          onChange={onRefFile}
                        />
                      </label>
                      {refMediaId && (
                        <button
                          onClick={() => {
                            setRefMediaId(null);
                            setRefPreview(null);
                          }}
                          className="text-secondary-text/60 self-start text-[11px] hover:text-red-400"
                        >
                          Remove
                        </button>
                      )}
                    </div>
                  </div>
                </div>

                {/* Aspect ratio */}
                <div>
                  <div className="text-secondary-text mb-1 text-[12px]">Aspect ratio</div>
                  <SegmentedControl
                    fullWidth
                    size="xs"
                    value={aspect}
                    onChange={(v) => setAspect(v as CreativeAspectRatio)}
                    data={ASPECT_OPTIONS}
                  />
                </div>

                {error && <div className="text-[13px] text-red-500">{error}</div>}

                <div className="mt-1 flex items-center justify-end gap-3">
                  <SecondaryBtn radius="xl" size="sm" onClick={onClose}>
                    Cancel
                  </SecondaryBtn>
                  <PrimaryGlassBtn
                    radius="xl"
                    size="sm"
                    leftSection={<Sparkles size={14} />}
                    onClick={startGeneration}
                  >
                    Generate
                  </PrimaryGlassBtn>
                </div>
              </motion.div>
            )}

            {/* ── GENERATING ────────────────────────────────────────────── */}
            {phase === 'generating' && (
              <motion.div
                key="loading"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.2 }}
                className="flex w-full flex-col items-center py-6 text-center"
              >
                <div
                  className={`mb-6 flex h-15 w-15 items-center justify-center rounded-2xl border shadow-inner ${
                    isLight
                      ? 'border-stroke-widget bg-[#1515150F]'
                      : 'border-white/10 bg-white/5'
                  }`}
                >
                  <Icon size={26} className="text-secondary-text" strokeWidth={1.5} />
                </div>

                <h3 className="text-primary-text mb-2 text-[19px] font-semibold">
                  Building {VARIANT_COUNT} concepts for you...
                </h3>
                <p className="text-secondary-text/70 mb-8 max-w-[320px] text-[14px] leading-relaxed">
                  Reading between the lines · finding what actually sells
                </p>

                <div className="flex w-full max-w-90 flex-col gap-2">
                  <div
                    className={`h-1 w-full overflow-hidden rounded-full ${
                      isLight ? 'bg-stroke-widget' : 'bg-white/10'
                    }`}
                  >
                    <motion.div
                      className="bg-primary-text h-full rounded-full"
                      initial={{ width: 0 }}
                      animate={{ width: `${progress}%` }}
                      transition={{ ease: 'linear', duration: 0.25 }}
                    />
                  </div>
                  <div className="flex items-center justify-end gap-1.5">
                    <Loader2 size={12} className="text-secondary-text/60 animate-spin" />
                    <span className="text-secondary-text/60 text-[12px] tabular-nums">
                      {progress}%
                    </span>
                  </div>
                </div>
              </motion.div>
            )}

            {/* ── DONE ──────────────────────────────────────────────────── */}
            {phase === 'done' && (
              <motion.div
                key="done"
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ type: 'spring', damping: 25, stiffness: 300 }}
                className="flex w-full flex-col py-2"
              >
                <h3 className="text-primary-text mb-1 text-center text-[19px] font-semibold">
                  {assets.length > 1
                    ? `${assets.length} concepts ready`
                    : 'Campaign asset ready'}
                </h3>
                <p className="text-secondary-text/70 mx-auto mb-5 max-w-90 text-center text-[14px] leading-relaxed">
                  Pick the ones you want — they run together on this ad.
                </p>

                <div className="grid grid-cols-3 gap-3">
                  {assets.map((a, i) => {
                    const url = a.url || a.file_path;
                    const isSelected = selected.has(a.id);
                    return (
                      <button
                        key={a.id}
                        type="button"
                        onClick={() => toggle(a.id)}
                        aria-pressed={isSelected}
                        className={`relative aspect-square overflow-hidden rounded-2xl border transition-all ${
                          isSelected
                            ? 'border-transparent ring-2 ring-blue-500'
                            : isLight
                              ? 'border-stroke-widget hover:border-black/25'
                              : 'border-white/10 hover:border-white/30'
                        }`}
                      >
                        {type === 'video' ? (
                          <video
                            src={url}
                            autoPlay
                            loop
                            muted
                            playsInline
                            className="h-full w-full object-cover"
                          />
                        ) : (
                          <img
                            src={url}
                            alt={`Concept ${i + 1}`}
                            className="h-full w-full object-cover"
                          />
                        )}
                        <span
                          className={`absolute top-2 right-2 flex h-5 w-5 items-center justify-center rounded-full border text-white ${
                            isSelected
                              ? 'border-blue-500 bg-blue-500'
                              : 'border-white/70 bg-black/40'
                          }`}
                        >
                          {isSelected && <Check size={12} strokeWidth={3} />}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Footer (done actions) */}
        <AnimatePresence>
          {phase === 'done' && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex shrink-0 items-center justify-center gap-3 border-t px-6 py-4"
              style={{
                borderColor: isLight
                  ? 'var(--mantine-color-gray-2)'
                  : 'rgba(255, 255, 255, 0.08)',
              }}
            >
              <SecondaryBtn
                radius="xl"
                size="sm"
                disabled={roundsLeft <= 0}
                onClick={startGeneration}
              >
                {roundsLeft > 0
                  ? `Regenerate (${roundsLeft} left)`
                  : 'No regenerations left'}
              </SecondaryBtn>
              <PrimaryGlassBtn
                radius="xl"
                size="sm"
                disabled={selected.size === 0}
                onClick={() =>
                  onAdd(
                    assets
                      .filter((a) => selected.has(a.id))
                      .map((a) => ({
                        type,
                        name:
                          a.file_name ||
                          (isImage ? 'spring_ad_v1.png' : 'spring_ad_v1.mp4'),
                        url: a.url || a.file_path,
                        id: a.id,
                      }))
                  )
                }
              >
                {selected.size > 1 ? `Add ${selected.size}` : 'Add'}
              </PrimaryGlassBtn>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  );
}
