'use client';

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  Menu,
  MultiSelect,
  NumberInput,
  ScrollArea,
  SegmentedControl,
  Select,
  Text,
} from '@mantine/core';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronDown,
  ChevronUp,
  ChevronsUpDown,
  Minus,
  Plus,
  Undo2,
  X,
} from 'lucide-react';
import { previewAudienceAction } from '@/actions/chat.actions';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';
import type {
  AudienceFilter,
  AudiencePreviewLayer,
  AudiencePreviewResponse,
  PoiCategoryGroup,
} from '@/types/chat';
import {
  builderLimit,
  cadenceSentence,
  draftFromFilter,
  draftToPatch,
  groupLabel,
  isDirty,
  layersFor,
  rescueOptions,
  visitsSentence,
  type AudiencePatch,
  type LayerDraft,
  type RescueOption,
} from './audienceLayers';

interface AudienceLayerBuilderProps {
  sessionId: string | null;
  filter: AudienceFilter | null | undefined;
  categories: PoiCategoryGroup[];
  // The raw superset the filter narrows from (the headline itself is the last
  // layer's count, computed by the same backend path).
  unfilteredCount?: number;
  initialCount?: number;
  disabled?: boolean;
  onCommit?: (patch: AudiencePatch) => void;
  onConfirmAction?: () => void;
  isLatest?: boolean;
  isOpen?: boolean;
  onClose?: () => void;
}

const DEBOUNCE_MS = 350;
const COMBO = {
  withinPortal: true,
  zIndex: 1000001,
  shadow: 'xl',
  transitionProps: { transition: 'pop-top-left', duration: 150 },
} as const;

const glassInputStyles = {
  input: {
    background: '#0000004D',
    backdropFilter: 'blur(15.2px)',
    WebkitBackdropFilter: 'blur(15.2px)',
    borderColor: 'rgba(255, 255, 255, 0.12)',
    borderRadius: '12px',
    color: 'var(--mantine-color-text)',
    fontSize: '11px',
  },
};

const glassComboboxStyles = {
  dropdown: {
    background: '#00000080',
    backdropFilter: 'blur(20px)',
    WebkitBackdropFilter: 'blur(20px)',
    borderColor: 'rgba(255, 255, 255, 0.12)',
    borderRadius: '16px',
    boxShadow:
      '0px 10px 30px 0px rgba(0, 0, 0, 0.5), 0px 1px 0px 0px rgba(255, 255, 255, 0.12) inset',
    padding: '5px',
  },
};

const glassSelectClassNames = {
  input:
    'bg-white/5! light:bg-black/5! border! border-white/8! rounded-[34px]! text-primary-text! text-[11px]! backdrop-blur-[15.2px]! transition-all! focus:border-white/30! light:focus:border-black/30!',
  dropdown:
    'bg-[#00000080]! light:bg-white/95! backdrop-blur-[20px]! border! border-primary-text/12! shadow-[0px_10px_30px_0px_#00000080,0px_1px_0px_0px_rgba(255,255,255,0.12)_inset]! rounded-2xl! p-1.5! overflow-hidden!',
  option:
    'text-[12px]! text-secondary-text! rounded-xl! px-3! py-2! transition-colors! duration-150! hover:bg-white/8! hover:text-primary-text! light:hover:bg-black/5! data-[selected]:bg-white/10! data-[selected]:text-primary-text! data-[selected]:font-semibold! light:data-[selected]:bg-black/10!',
  empty: 'text-xs! text-secondary-text/70! py-2.5! px-3!',
};

const glassMultiSelectClassNames = {
  ...glassSelectClassNames,
  pillsList: 'gap-1.5!',
  input:
    'bg-[#0000004D]! light:bg-black/5! border! border-primary-text/12! rounded-xl! shadow-[0px_2px_8px_0px_rgba(0,0,0,0.25),0px_1px_0px_0px_rgba(255,255,255,0.08)_inset]! text-primary-text! text-[11px]! backdrop-blur-[15.2px]! transition-all! min-h-8! focus:border-white/30! light:focus:border-black/30!',
  pill: 'border! border-primary-text/15! bg-primary-text/6! light:bg-black/5! text-primary-text! rounded-full! py-0.5! px-2.5! text-[11px]! font-medium! whitespace-nowrap! shadow-[0px_1px_0px_0px_rgba(255,255,255,0.08)_inset]! backdrop-blur-[10px]! flex! items-center! gap-1.5!',
  pillLabel: 'text-primary-text! text-[11px]! font-medium! leading-none!',
  pillRemoveButton:
    'text-secondary-text! hover:text-primary-text! hover:bg-white/10! light:hover:bg-black/10! rounded-full! transition-colors! size-3.5! p-0! flex! items-center! justify-center! cursor-pointer!',
};

const glassNumberInputClassNames = {
  input:
    'bg-white/4! light:bg-black/5! border! border-primary-text/6! rounded-xl! text-primary-text! text-[11px]! transition-all! focus:border-white/30! light:focus:border-black/30!',
  controls:
    'flex! flex-col! h-full! border-l! border-primary-text/10! rounded-r-xl! overflow-hidden! w-5!',
  control:
    'border-b! last:border-b-0! border-primary-text/10! text-primary-text/60! hover:text-primary-text! hover:bg-white/8! light:hover:bg-black/5! transition-colors! cursor-pointer!',
  label: 'text-secondary-text! text-[11px]! font-medium! mb-1!',
};

const glassSegmentedControlClassNames = {
  root: 'bg-white/4! light:bg-black/5! rounded-xl! p-1! border! border-primary-text/10!',
  indicator:
    'bg-white/10! light:bg-white! rounded-lg! shadow-[0px_2px_8px_0px_rgba(0,0,0,0.25),0px_1px_0px_0px_rgba(255,255,255,0.12)_inset]!',
  control: 'border-0!',
  label:
    'text-secondary-text! data-[active]:text-primary-text! data-[active]:font-semibold! text-[11px]! py-1! font-medium! transition-colors!',
};

const glassSegmentedControlStyles = {
  root: {
    backdropFilter: 'blur(15px)',
    WebkitBackdropFilter: 'blur(15px)',
  },
  indicator: {
    backdropFilter: 'blur(10px)',
    WebkitBackdropFilter: 'blur(10px)',
  },
};

const renderGlassPill = ({
  option,
  onRemove,
  disabled,
}: {
  option?: { label?: React.ReactNode };
  onRemove?: () => void;
  disabled?: boolean;
}) => (
  <span className="border-primary-text/15 bg-primary-text/6 text-primary-text inline-flex items-center gap-1.5 rounded-full border py-0.5 pr-1.5 pl-2.5 text-[11px] font-medium whitespace-nowrap shadow-[0px_1px_0px_0px_rgba(255,255,255,0.08)_inset] backdrop-blur-[10px]">
    <span className="max-w-40 truncate">{option?.label}</span>
    {!disabled && (
      <button
        type="button"
        tabIndex={-1}
        onClick={(e) => {
          e.stopPropagation();
          onRemove?.();
        }}
        className="hover:bg-primary-text/10 text-secondary-text hover:text-primary-text flex size-3.5 cursor-pointer items-center justify-center rounded-full transition-colors"
      >
        <X size={10} />
      </button>
    )}
  </span>
);

const fmt = (n: number | null | undefined) =>
  typeof n === 'number' ? n.toLocaleString() : '—';

const Field = ({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) => (
  <div className="flex flex-col gap-0.5">
    <Text
      fz={10}
      fw={600}
      className="text-secondary-text tracking-wider uppercase"
    >
      {label}
    </Text>
    {children}
  </div>
);

const TREND_OPTIONS: {
  value: LayerDraft['trend'];
  title: string;
  desc: string;
}[] = [
  {
    value: 'any',
    title: 'No pattern',
    desc: 'Count everyone who matches above',
  },
  {
    value: 'started',
    title: 'Just started visiting',
    desc: 'Recent visits, none before',
  },
  {
    value: 'lapsed',
    title: 'Stopped visiting',
    desc: 'Came before, not recently (win-back)',
  },
];

export default function AudienceLayerBuilder({
  sessionId,
  filter,
  categories,
  unfilteredCount,
  initialCount,
  disabled = false,
  onCommit,
  onConfirmAction,
}: AudienceLayerBuilderProps) {
  const [draft, setDraft] = useState<LayerDraft>(() => draftFromFilter(filter));
  const [preview, setPreview] = useState<AudiencePreviewResponse | null>(null);
  const [rescue, setRescue] = useState<
    { option: RescueOption; layer: AudiencePreviewLayer }[]
  >([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [placesSectionOpen, setPlacesSectionOpen] = useState(true);
  const [timeSectionOpen, setTimeSectionOpen] = useState(true);
  const [visitsSectionOpen, setVisitsSectionOpen] = useState(true);
  const [patternSectionOpen, setPatternSectionOpen] = useState(true);
  const [showHowWeGotHere, setShowHowWeGotHere] = useState(false);
  const requestId = useRef(0);

  const limit = useMemo(() => builderLimit(filter), [filter]);
  const filterKey = useMemo(() => JSON.stringify(filter ?? null), [filter]);

  // A commit re-emits the map with the NEW stored filter — that, not the local
  // draft, is the source of truth again, so chat and panel never disagree.
  const [prevFilterKey, setPrevFilterKey] = useState(filterKey);
  if (filterKey !== prevFilterKey) {
    setPrevFilterKey(filterKey);
    setDraft(draftFromFilter(filter));
    setPreview(null);
    setRescue([]);
  }

  const keyById = useMemo(() => {
    const m = new Map(categories.map((c) => [c.id, c.key]));
    return (id: string) => m.get(id) ?? groupLabel(id);
  }, [categories]);

  const options = useMemo(
    () =>
      categories.map((c) => ({ value: c.id, label: `${c.key} (${c.count})` })),
    [categories]
  );

  const patchDraft = useCallback(
    (over: Partial<LayerDraft>) => setDraft((d) => ({ ...d, ...over })),
    []
  );

  // Live recount on every change. Read-only and free — it re-filters rows the
  // session already bought — so debouncing is about request volume, not cost.
  useEffect(() => {
    if (!sessionId || limit) return;
    const id = ++requestId.current;
    const timer = setTimeout(async () => {
      setLoading(true);
      const res = await previewAudienceAction(
        sessionId,
        layersFor(draft, keyById)
      );
      if (id !== requestId.current) return;
      if (!res.success) {
        setError(res.error);
        setPreview(null);
        setRescue([]);
        setLoading(false);
        return;
      }
      setError(null);
      setPreview(res.data);
      const last = res.data.layers[res.data.layers.length - 1];
      const tooFew =
        last?.count != null && last.count < res.data.min_deliverable;
      const opts = tooFew ? rescueOptions(draft, keyById) : [];
      if (!opts.length) {
        setRescue([]);
        setLoading(false);
        return;
      }
      // Count each rescue option for real — a suggestion with a guessed number
      // would repeat the mistake it is meant to fix.
      const r2 = await previewAudienceAction(
        sessionId,
        opts.map((o) => ({ label: o.label, patches: [draftToPatch(o.draft)] }))
      );
      if (id !== requestId.current) return;
      setRescue(
        r2.success
          ? opts
              .map((option, i) => ({ option, layer: r2.data.layers[i] }))
              .filter((x) => x.layer)
          : []
      );
      setLoading(false);
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [draft, sessionId, limit, keyById]);

  const layers = useMemo(() => preview?.layers ?? [], [preview]);
  const final = layers[layers.length - 1];
  const finalCount = final?.count ?? null;
  const minDeliverable = preview?.min_deliverable ?? 0;
  const dirty = isDirty(filter, draft);
  const canApply = !disabled && dirty && finalCount !== null && !loading;
  const sentence = visitsSentence(draft);
  const rhythm = cadenceSentence(draft);
  // const multi = draft.groups.length > 1;
  const anyUnevaluable = layers.some((l) => l.unevaluable);
  const toggleDropped = (key: string) =>
    patchDraft({
      dropped: draft.dropped.includes(key)
        ? draft.dropped.filter((k) => k !== key)
        : [...draft.dropped, key],
    });

  const displayCount =
    finalCount !== null
      ? finalCount
      : typeof initialCount === 'number'
        ? initialCount
        : (unfilteredCount ?? 0);

  const percent =
    typeof unfilteredCount === 'number' && unfilteredCount > 0 && typeof displayCount === 'number'
      ? Math.round((displayCount / unfilteredCount) * 100)
      : null;

  const displayPercent = useMemo(() => {
    if (percent === null) return null;
    if (percent === 0 && displayCount > 0) return '<1';
    if (percent === 100 && typeof unfilteredCount === 'number' && displayCount < unfilteredCount)
      return '>99';
    return String(percent);
  }, [percent, displayCount, unfilteredCount]);

  const progressPercent =
    typeof unfilteredCount === 'number' && unfilteredCount > 0 && typeof displayCount === 'number'
      ? Math.min(100, Math.max(displayCount > 0 ? 1 : 0, (displayCount / unfilteredCount) * 100))
      : 100;

  const howWeGotHereSteps = useMemo(() => {
    const base =
      typeof unfilteredCount === 'number' && unfilteredCount > 0
        ? unfilteredCount
        : (layers[0]?.count ?? displayCount ?? 1);

    type StepItem = {
      label: string;
      count: number | null;
      delta: number | null;
      isLast: boolean;
      percent: number;
    };

    const list: StepItem[] = [];
    let prev = typeof unfilteredCount === 'number' ? unfilteredCount : null;

    // 1. Baseline row ("Near your places")
    if (typeof unfilteredCount === 'number' && unfilteredCount > 0) {
      list.push({
        label: 'Near your places',
        count: unfilteredCount,
        delta: null,
        isLast: layers.length === 0,
        percent: 100,
      });
    }

    // 2. Subsequent filter layers
    layers.forEach((l, i) => {
      // Avoid duplicate baseline if first layer is "All places" with same count
      if (
        i === 0 &&
        (l.label === 'All places' || l.label === 'Near your places') &&
        typeof unfilteredCount === 'number' &&
        l.count === unfilteredCount
      ) {
        return;
      }

      const isLast = i === layers.length - 1;
      const count = l.count;
      const delta =
        prev !== null && count !== null && count !== prev ? count - prev : null;
      if (count !== null) prev = count;

      let label = l.label;
      if (label === 'With your visit rules') {
        if (draft.minVisits) {
          label = `Visited ${draft.minVisits}+ time${draft.minVisits > 1 ? 's' : ''}`;
        } else if (draft.windowDays) {
          label = `Seen in the last ${draft.windowDays} days`;
        } else if (sentence) {
          label = sentence;
        }
      } else if (label === 'All places') {
        label = 'Near your places';
      }

      const pct =
        typeof count === 'number' && base > 0
          ? Math.min(100, Math.max(count > 0 ? 1 : 0, (count / base) * 100))
          : 0;

      list.push({
        label,
        count,
        delta,
        isLast,
        percent: pct,
      });
    });

    return list;
  }, [unfilteredCount, layers, displayCount, draft.minVisits, draft.windowDays, sentence]);

  const placesSubtitle = useMemo(() => {
    const modeLabel =
      draft.mode === 'all'
        ? 'all of them'
        : draft.mode === 'atLeast'
          ? `at least ${draft.atLeast || 2}`
          : 'any of them';

    if (draft.groups.length === 0) {
      return `All places · ${modeLabel}`;
    }
    return `${draft.groups.map((id) => keyById(id)).join(', ')} · ${modeLabel}`;
  }, [draft.groups, draft.mode, draft.atLeast, keyById]);

  const periodOptions = useMemo(() => {
    const base = [
      { value: 'any', label: 'Any time' },
      { value: '7', label: 'Last 7 days' },
      { value: '14', label: 'Last 14 days' },
      { value: '30', label: 'Last 30 days' },
      { value: '60', label: 'Last 60 days' },
      { value: '90', label: 'Last 90 days' },
      { value: '180', label: 'Last 180 days' },
    ];
    if (
      draft.windowDays &&
      !base.some((o) => o.value === String(draft.windowDays))
    ) {
      base.push({
        value: String(draft.windowDays),
        label: `Last ${draft.windowDays} days`,
      });
    }
    return base;
  }, [draft.windowDays]);

  const timeSubtitle = useMemo(() => {
    const periodLabel = draft.windowDays
      ? `Last ${draft.windowDays} days`
      : 'Any time';
    const daysLabel =
      draft.days === 'weekdays'
        ? 'weekdays'
        : draft.days === 'weekends'
          ? 'weekends'
          : 'any day';
    return `${periodLabel} · ${daysLabel}`;
  }, [draft.windowDays, draft.days]);

  const timeRemovedCount = useMemo(() => {
    const rulesStep = howWeGotHereSteps.find((s) => s.isLast);
    if (
      rulesStep &&
      rulesStep.delta !== null &&
      rulesStep.delta < 0 &&
      (draft.windowDays || draft.days !== 'any')
    ) {
      return Math.abs(rulesStep.delta);
    }
    return null;
  }, [howWeGotHereSteps, draft.windowDays, draft.days]);

  const visitsSubtitle = useMemo(() => {
    if (draft.minVisits) {
      const scopeLabel =
        draft.visitsScope === 'each' ? 'at each place' : 'in total';
      return `${draft.minVisits}+ visits ${scopeLabel}`;
    }
    if (draft.dwellMin) {
      return `${draft.dwellMin}+ min stay`;
    }
    return 'Any visits';
  }, [draft.minVisits, draft.visitsScope, draft.dwellMin]);

  const visitsExplanation = useMemo(() => {
    const count = draft.minVisits ?? 2;
    if (draft.groups.length > 1 && draft.visitsScope === 'each') {
      return `${count}+ visits at each of these places`;
    }
    if (draft.groups.length === 0) {
      return `${count}+ visits to the same place`;
    }
    return `${count}+ visits added up across all these places`;
  }, [draft.minVisits, draft.groups.length, draft.visitsScope]);

  const visitsRemovedCount = useMemo(() => {
    const rulesStep = howWeGotHereSteps.find((s) => s.isLast);
    if (
      rulesStep &&
      rulesStep.delta !== null &&
      rulesStep.delta < 0 &&
      (draft.minVisits || draft.dwellMin)
    ) {
      return Math.abs(rulesStep.delta);
    }
    return null;
  }, [howWeGotHereSteps, draft.minVisits, draft.dwellMin]);

  const patternSubtitle = useMemo(() => {
    if (draft.trend === 'started') return 'Just started visiting';
    if (draft.trend === 'lapsed') return 'Stopped visiting';
    if (draft.cadenceDays) return `Every ${draft.cadenceDays} days`;
    return 'No pattern';
  }, [draft.trend, draft.cadenceDays]);

  const trendExplanation = useMemo(() => {
    if (draft.trend === 'lapsed') {
      return 'Visited at least twice in the period before, and not at all recently.';
    }
    if (draft.trend === 'started') {
      return 'Visited at least once recently, and not at all in the period before.';
    }
    return null;
  }, [draft.trend]);

  const periodBeforeOptions = useMemo(() => {
    const base = [
      { value: 'same', label: 'Same length' },
      { value: '7', label: '7 days' },
      { value: '14', label: '14 days' },
      { value: '30', label: '30 days' },
      { value: '60', label: '60 days' },
      { value: '90', label: '90 days' },
      { value: '180', label: '180 days' },
    ];
    if (
      draft.trendPrior &&
      !base.some((o) => o.value === String(draft.trendPrior))
    ) {
      base.push({
        value: String(draft.trendPrior),
        label: `${draft.trendPrior} days`,
      });
    }
    return base;
  }, [draft.trendPrior]);

  const patternRemovedCount = useMemo(() => {
    const rulesStep = howWeGotHereSteps.find((s) => s.isLast);
    if (
      rulesStep &&
      rulesStep.delta !== null &&
      rulesStep.delta < 0 &&
      (draft.trend !== 'any' || draft.cadenceDays)
    ) {
      return Math.abs(rulesStep.delta);
    }
    return null;
  }, [howWeGotHereSteps, draft.trend, draft.cadenceDays]);

  return (
    <div className="flex flex-col gap-2 h-96.25 min-h-96.25 max-h-96.25 -mt-2">
      {/* 1. Metric Card */}
      <div
        className="border-stroke-widget light:border-none relative overflow-hidden rounded-2xl! border p-2.5 px-3! backdrop-blur-[15.2px]! shrink-0"
        style={{
          background: '#0000004D',
        }}
      >
        <div className="flex items-baseline justify-between">
          <div className="flex flex-col">
            <div className="flex items-baseline gap-1.5">
              <span className="text-primary-text text-xl md:text-[22px]! font-bold tracking-tight leading-none">
                {loading ? '…' : fmt(displayCount)}
              </span>
              <span className="text-secondary-text text-[13px]! font-semibold!">
                people
              </span>
            </div>
          </div>

          <button
            type="button"
            disabled={!dirty || disabled}
            onClick={() => setDraft(draftFromFilter(filter))}
            className="text-secondary-text/75! hover:text-primary-text text-sm! font-semibold! cursor-pointer transition-colors disabled:opacity-30 disabled:cursor-not-allowed pt-0"
          >
            Reset
          </button>
        </div>

        {/* Progress Bar Track matching design - hidden when "How we got here" is open */}
        {!showHowWeGotHere && (
          <div className="w-full h-1! bg-white/12 light:bg-black/10 rounded-full overflow-hidden my-1.5">
            <div
              className="h-full bg-primary-text rounded-full transition-all duration-300 ease-out"
              style={{
                width: `${Math.min(100, Math.max(0, progressPercent))}%`,
              }}
            />
          </div>
        )}

        <p className={`text-[#C8C8C4BF] text-[11px]! leading-snug ${showHowWeGotHere ? 'mt-1' : ''}`}>
          {typeof unfilteredCount === 'number' && displayPercent !== null
            ? `${displayPercent}% of the ${fmt(unfilteredCount)} people near your places`
            : 'People near your places'}
        </p>

        {error && (
          <Text fz={10.5} className="text-red-400! mt-0.5">
            {error}
          </Text>
        )}

        <button
          type="button"
          onClick={() => setShowHowWeGotHere(!showHowWeGotHere)}
          className="text-secondary-text/85 hover:text-primary-text flex items-center gap-1 text-[11px]! font-semibold mt-1 cursor-pointer transition-colors"
        >
          <span>How we got here</span>
          <ChevronDown
            size={13}
            className={`transition-transform duration-200 ${
              showHowWeGotHere ? 'rotate-180' : ''
            }`}
          />
        </button>

        <AnimatePresence>
          {showHowWeGotHere && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden border-t border-primary-text/10 pt-2.5"
            >
              <div className="flex flex-col gap-1.5 max-h-35 overflow-y-auto pr-1 scrollbar-thin [scrollbar-color:rgba(255,255,255,0.25)_transparent]">
                {preview?.carried && preview.carried.length > 0 && (
                  <div className="mb-1">
                    <span className="text-secondary-text text-[10.5px]">
                      Also applied:
                    </span>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {preview.carried.map(({ key, label }) => {
                        const removed = draft.dropped.includes(key);
                        return (
                          <span
                            key={key}
                            className={`inline-flex items-center gap-1 rounded-full border border-primary-text/15 bg-primary-text/6 px-2 py-0.5 text-[10px] text-primary-text ${
                              removed ? 'opacity-50 grayscale line-through' : ''
                            }`}
                          >
                            {label}
                            <button
                              type="button"
                              onClick={() => toggleDropped(key)}
                              className="cursor-pointer text-secondary-text hover:text-primary-text"
                            >
                              {removed ? <Undo2 size={9} /> : <X size={9} />}
                            </button>
                          </span>
                        );
                      })}
                    </div>
                  </div>
                )}
                {howWeGotHereSteps.map((step, i) => (
                  <div key={`${step.label}-${i}`} className="flex flex-col">
                    <div className="flex items-center justify-between text-[11.5px] leading-tight">
                      <span
                        className={`truncate max-w-[55%] ${
                          step.isLast
                            ? 'text-primary-text font-semibold! text-[11.5px]'
                            : 'text-[#C8C8C4]! text-[11.5px]! font-normal'
                        }`}
                      >
                        {step.label}
                      </span>
                      <div className="flex items-center">
                        {step.delta !== null && (
                          <span className="text-[#C8C8C48C] text-[10.5px] font-normal tabular-nums mr-1.5">
                            {step.delta < 0
                              ? `-${fmt(Math.abs(step.delta))}`
                              : `+${fmt(step.delta)}`}
                          </span>
                        )}
                        <span
                          className={`tabular-nums text-primary-text font-semibold text-xs!`}
                        >
                          {step.count === null ? '—' : fmt(step.count)}
                        </span>
                      </div>
                    </div>

                    {/* Progress Bar Track matching design */}
                    <div className="w-full h-1.5 bg-white/10 light:bg-black/7! rounded-full overflow-hidden mt-1.5 mb-2">
                      <div
                        className={`h-full rounded-full transition-all duration-300 ease-out ${
                          step.isLast
                            ? 'bg-white/90!'
                            : 'bg-white/40! light:bg-black/35'
                        }`}
                        style={{
                          width: `${step.percent}%`,
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {limit && (
        <div
          className="border-stroke-widget light:border-none relative overflow-hidden rounded-2xl! border p-3.5! backdrop-blur-[15.2px]!"
          style={{ background: '#0000004D' }}
        >
          <Text fz={12} className="text-secondary-text">
            {limit} Tell me what to change in chat and I&apos;ll update it.
          </Text>
        </div>
      )}

      {!limit && (
        <>
          {/* 2. Scrollable Body: Places Card + Other Filter Cards */}
          <ScrollArea
            scrollbars="y"
            type="auto"
            scrollbarSize={7}
            offsetScrollbars="y"
            className="flex-1 min-h-0"
            classNames={{
              scrollbar:
                'bg-white/8! light:bg-black/10! hover:bg-white/15! light:hover:bg-black/20! rounded-full! transition-colors! my-0.5!',
              thumb:
                'bg-white/40! light:bg-black/40! hover:bg-white/60! light:hover:bg-black/60! active:bg-white/75! light:active:bg-black/75! rounded-full! transition-colors!',
            }}
            styles={{
              root: { flex: 1, minHeight: 0 },
              viewport: { height: '100%' },
              scrollbar: {
                borderRadius: '9999px',
              },
              thumb: {
                borderRadius: '9999px',
              },
            }}
          >
            <div className="flex flex-col gap-2 pr-1 py-0.5">
              {/* Places Accordion Card */}
              <div
                className="border-stroke-widget light:border-none relative overflow-hidden rounded-2xl! border backdrop-blur-[15.2px]!"
                style={{
                  background: '#0000004D',
                }}
              >
                <button
                  type="button"
                  onClick={() => setPlacesSectionOpen(!placesSectionOpen)}
                  className={`w-full flex items-center justify-between text-left cursor-pointer px-3 ${
                    placesSectionOpen ? 'pt-2.5 pb-2.5' : 'py-2.5'
                  }`}
                >
                  <div>
                    <h4 className="text-primary-text text-[13.5px]! font-semibold! leading-tight">Places</h4>
                    <p className="text-[#C8C8C4B2] text-[11px]! mt-0.5!">
                      {placesSubtitle}
                    </p>
                  </div>
                  <ChevronUp
                    size={16}
                    className={`text-secondary-text transition-transform duration-200 shrink-0 ${
                      placesSectionOpen ? '' : 'rotate-180'
                    }`}
                  />
                </button>

                <AnimatePresence initial={false}>
                  {placesSectionOpen && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.2 }}
                      className="overflow-hidden"
                    >
                      {/* Divider matching the image edge-to-edge */}
                      <div className="w-full border-t border-white/8 light:border-black/5" />

                      <div className="flex flex-col gap-3.5 px-3 pt-2.5 pb-3">
                        {/* Which places */}
                        <div className="flex flex-col gap-1.5">
                          <Text
                            fz={11.5}
                            fw={500}
                            className="text-[#C8C8C4E5] tracking-normal"
                          >
                            Which places
                          </Text>

                          <div className="flex flex-wrap items-center gap-1.5">
                            {draft.groups.length === 0 && (
                              <span className="text-secondary-text text-xs italic">
                                All places included
                              </span>
                            )}

                            {draft.groups.map((groupId) => {
                              const cat = categories.find((c) => c.id === groupId);
                              const label = cat ? cat.key : keyById(groupId);
                              const count = cat?.count;

                              return (
                                <span
                                  key={groupId}
                                  className="border border-white/12! bg-white/14! hover:bg-white/18! text-primary-text rounded-full py-1 px-2.5 text-xs! font-semibold! whitespace-nowrap flex items-center gap-1.5! transition-colors"
                                >
                                  <span>{label}</span>
                                  {count !== undefined && (
                                    <span className="text-secondary-text/50 text-[11px]! font-semibold!">
                                      {count}
                                    </span>
                                  )}
                                  <button
                                    type="button"
                                    disabled={disabled}
                                    onClick={() => {
                                      patchDraft({
                                        groups: draft.groups.filter(
                                          (g) => g !== groupId
                                        ),
                                      });
                                    }}
                                    className="text-secondary-text/60 hover:text-primary-text flex size-3.5 cursor-pointer items-center justify-center rounded-full transition-colors ml-0.5"
                                  >
                                    <X size={11} />
                                  </button>
                                </span>
                              );
                            })}

                            {/* + Add button */}
                            <Menu
                              shadow="md"
                              width={59}
                              position="bottom-start"
                              zIndex={1000002}
                            >
                              <Menu.Target>
                                <button
                                  type="button"
                                  disabled={disabled}
                                  className="border border-dashed border-white/25! hover:border-white/40 text-primary-text rounded-full py-0.5! px-2.5 text-sm! font-semibold! flex items-center gap-1 cursor-pointer transition-colors"
                                >
                                  <Plus size={12} />
                                  <span>Add</span>
                                </button>
                              </Menu.Target>
                              <Menu.Dropdown
                                style={{
                                  backdropFilter: 'blur(20px)',
                                  WebkitBackdropFilter: 'blur(20px)',
                                  background: '#00000080',
                                }}
                                className="border-primary-text/12! rounded-2xl! p-1.5!"
                              >
                                {categories.filter(
                                  (c) => !draft.groups.includes(c.id)
                                ).length === 0 ? (
                                  <Menu.Item
                                    disabled
                                    className="text-xs text-secondary-text"
                                  >
                                    All places added
                                  </Menu.Item>
                                ) : (
                                  categories
                                    .filter((c) => !draft.groups.includes(c.id))
                                    .map((cat) => (
                                      <Menu.Item
                                        key={cat.id}
                                        onClick={() => {
                                          patchDraft({
                                            groups: [...draft.groups, cat.id],
                                          });
                                        }}
                                        className="text-xs text-secondary-text hover:text-primary-text hover:bg-white/8 rounded-xl px-2.5 py-1.5"
                                      >
                                        {cat.key} ({cat.count})
                                      </Menu.Item>
                                    ))
                                )}
                              </Menu.Dropdown>
                            </Menu>
                          </div>
                        </div>

                        {/* Must have visited */}
                        <div className="flex flex-col gap-1.5">
                          <Text
                            fz={11.5}
                            fw={500}
                            className="text-[#C8C8C4E5] tracking-normal"
                          >
                            Must have visited
                          </Text>

                          <SegmentedControl
                            size="xs"
                            fullWidth
                            radius="xl"
                            withItemsBorders={false}
                            value={draft.mode}
                            onChange={(v) =>
                              patchDraft({ mode: v as LayerDraft['mode'] })
                            }
                            data={[
                              { value: 'any', label: 'Any of them' },
                              { value: 'atLeast', label: 'At least…' },
                              { value: 'all', label: 'All of them' },
                            ]}
                            disabled={disabled}
                            classNames={{
                              root: 'w-full! bg-white/4! light:bg-black/5! border! border-white/6! rounded-full! p-0.5! backdrop-blur-[15.2px]!',
                              indicator:
                                'bg-white/14! light:bg-white! rounded-full! border! border-white/20! light:border-black/5! shadow-[0px_2px_12px_0px_#00000040,0px_1px_0px_0px_#FFFFFF40_inset]!',
                              control: 'border-0! before:hidden!',
                              label:
                                'w-full! block! text-center! text-[#C8C8C4BF]! data-[active]:text-primary-text! font-semibold! text-xs! py-[5.5px]! transition-colors! duration-150!',
                            }}
                          />

                          {draft.mode === 'atLeast' && (
                            <div className="flex items-center gap-1.5 pt-0.5">
                              <NumberInput
                                size="xs"
                                w={60}
                                min={2}
                                max={Math.max(2, draft.groups.length)}
                                clampBehavior="strict"
                                value={draft.atLeast}
                                onChange={(v) =>
                                  patchDraft({ atLeast: Number(v) || 2 })
                                }
                                disabled={disabled}
                                classNames={glassNumberInputClassNames}
                                styles={glassInputStyles}
                              />
                              <Text fz={10.5} className="text-secondary-text">
                                of the {draft.groups.length || 2} places
                              </Text>
                            </div>
                          )}
                        </div>

                        {/* Leave out anyone who visited */}
                        <div className="flex flex-col gap-1.5">
                          <Text
                            fz={11.5}
                            fw={500}
                            className="text-[#C8C8C4E5] tracking-normal"
                          >
                            Leave out anyone who visited
                          </Text>

                          <MultiSelect
                            size="xs"
                            searchable
                            clearable
                            checkIconPosition="right"
                            placeholder="No one"
                            radius="xl"
                            rightSection={
                              <ChevronsUpDown
                                size={13}
                                className="text-secondary-text pointer-events-none"
                              />
                            }
                            data={options.filter(
                              (o) => !draft.groups.includes(o.value)
                            )}
                            value={draft.exclude}
                            onChange={(exclude) => patchDraft({ exclude })}
                            disabled={disabled}
                            comboboxProps={COMBO}
                            renderPill={renderGlassPill}
                            classNames={{
                              ...glassMultiSelectClassNames,
                              input:
                                'bg-white/5! light:bg-black/5! border! border-white/8! rounded-full! text-primary-text/50! text-xs! transition-all! min-h-8! px-3! focus:border-white/30! light:focus:border-black/30!',
                            }}
                            styles={{ ...glassInputStyles, ...glassComboboxStyles }}
                          />

                          {draft.exclude.length > 0 && (
                            <SegmentedControl
                              size="xs"
                              fullWidth
                              radius="xl"
                              value={draft.excludeEver ? 'ever' : 'same'}
                              onChange={(v) =>
                                patchDraft({ excludeEver: v === 'ever' })
                              }
                              data={[
                                { value: 'same', label: 'In lookback window' },
                                { value: 'ever', label: 'Ever (historical)' },
                              ]}
                              disabled={disabled}
                              classNames={{
                                root: 'w-full! bg-[#0000004D]! light:bg-black/5! rounded-full! p-1! backdrop-blur-[15.2px]! mt-1',
                                indicator:
                                  'bg-white/8! light:bg-white! rounded-full! border-t! border-t-white/12! border-b! border-b-white/8! light:border-black/5! shadow-[inset_0px_1px_0px_0px_#FFFFFF40,0px_2px_12px_0px_#00000040]!',
                                control: 'border-0!',
                                label:
                                  'w-full! block! text-center! text-secondary-text! data-[active]:text-primary-text! data-[active]:font-semibold! text-xs! py-[5px]! font-medium! transition-colors! duration-150!',
                              }}
                            />
                          )}
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              {/* Time Accordion Card */}
              <div
                className="border-stroke-widget light:border-none relative overflow-hidden rounded-2xl! border"
                style={{
                  background: '#0000004D',
                }}
              >
                <button
                  type="button"
                  onClick={() => setTimeSectionOpen(!timeSectionOpen)}
                  className={`w-full flex items-center justify-between text-left cursor-pointer px-3 ${
                    timeSectionOpen ? 'pt-2.5 pb-2.5' : 'py-2.5'
                  }`}
                >
                  <div>
                    <h4 className="text-primary-text text-[13.5px]! font-semibold! leading-tight">
                      Time
                    </h4>
                    <p className="text-[#C8C8C4B2]! text-[11px]! mt-0.5!">
                      {timeSubtitle}
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {timeRemovedCount !== null && (
                      <span className="text-[#C8C8C4A6]! text-[10.5px]! font-medium! tabular-nums">
                        removes {fmt(timeRemovedCount)}
                      </span>
                    )}
                    <ChevronUp
                      size={16}
                      className={`text-secondary-text transition-transform duration-200 shrink-0 ${
                        timeSectionOpen ? '' : 'rotate-180'
                      }`}
                    />
                  </div>
                </button>

                <AnimatePresence initial={false}>
                  {timeSectionOpen && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.2 }}
                      className="overflow-hidden"
                    >
                      {/* Divider matching the image edge-to-edge */}
                      <div className="w-full border-t border-white/8 light:border-black/5" />

                      <div className="grid grid-cols-2 gap-2.5 px-3 pt-2.5 pb-3">
                        {/* Period */}
                        <div className="flex flex-col gap-1.5">
                          <Text
                            fz={11.5}
                            fw={500}
                            className="text-[#C8C8C4E5]! tracking-normal"
                          >
                            Period
                          </Text>

                          <Select
                            size="xs"
                            allowDeselect={false}
                            checkIconPosition="right"
                            rightSectionPointerEvents="none"
                            rightSection={
                              <ChevronsUpDown
                                size={13}
                                className="text-secondary-text pointer-events-none"
                              />
                            }
                            value={
                              draft.windowDays
                                ? String(draft.windowDays)
                                : 'any'
                            }
                            onChange={(v) => {
                              patchDraft({
                                windowDays:
                                  v && v !== 'any' ? Number(v) : null,
                              });
                            }}
                            data={periodOptions}
                            disabled={disabled}
                            comboboxProps={COMBO}
                            classNames={glassSelectClassNames}
                            styles={{
                              ...glassInputStyles,
                              ...glassComboboxStyles,
                            }}
                          />
                        </div>

                        {/* Days */}
                        <div className="flex flex-col gap-1.5">
                          <Text
                            fz={11.5}
                            fw={500}
                            className="text-[#C8C8C4E5]! tracking-normal"
                          >
                            Days
                          </Text>

                          <Select
                            size="xs"
                            allowDeselect={false}
                            checkIconPosition="right"
                            rightSectionPointerEvents="none"
                            rightSection={
                              <ChevronsUpDown
                                size={13}
                                className="text-secondary-text pointer-events-none"
                              />
                            }
                            value={draft.days}
                            onChange={(v) => {
                              const days = (v as LayerDraft['days']) || 'any';
                              patchDraft({ days });
                            }}
                            data={[
                              { value: 'any', label: 'Any day' },
                              { value: 'weekdays', label: 'Weekdays' },
                              { value: 'weekends', label: 'Weekends' },
                            ]}
                            disabled={disabled}
                            comboboxProps={COMBO}
                            classNames={glassSelectClassNames}
                            styles={{
                              ...glassInputStyles,
                              ...glassComboboxStyles,
                            }}
                          />
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              {/* Visits Accordion Card */}
              <div
                className="border-stroke-widget light:border-none relative overflow-hidden rounded-2xl! border"
                style={{
                  background: '#0000004D',
                }}
              >
                <button
                  type="button"
                  onClick={() => setVisitsSectionOpen(!visitsSectionOpen)}
                  className={`w-full flex items-center justify-between text-left cursor-pointer px-3 ${
                    visitsSectionOpen ? 'pt-2.5 pb-2.5' : 'py-2.5'
                  }`}
                >
                  <div>
                    <h4 className="text-primary-text text-[13.5px]! font-semibold! leading-tight">
                      Visits
                    </h4>
                    <p className="text-[#C8C8C4B2]! text-[11px]! mt-0.5!">
                      {visitsSubtitle}
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {visitsRemovedCount !== null && (
                      <span className="text-[#C8C8C4A6]! text-[10.5px]! font-medium! tabular-nums">
                        removes {fmt(visitsRemovedCount)}
                      </span>
                    )}
                    <ChevronUp
                      size={16}
                      className={`text-secondary-text transition-transform duration-200 shrink-0 ${
                        visitsSectionOpen ? '' : 'rotate-180'
                      }`}
                    />
                  </div>
                </button>

                <AnimatePresence initial={false}>
                  {visitsSectionOpen && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.2 }}
                      className="overflow-hidden"
                    >
                      {/* Divider matching the image edge-to-edge */}
                      <div className="w-full border-t border-white/8 light:border-black/5" />

                      <div className="flex flex-col gap-3.5 px-3 pt-2.5 pb-3">
                        {/* How many visits */}
                        <div className="flex flex-col gap-1.5">
                          <Text
                            fz={11.5}
                            fw={500}
                            className="text-[#C8C8C4E5]! tracking-normal"
                          >
                            How many visits
                          </Text>

                          <div className="flex items-center gap-2">
                            <div className="inline-flex items-center h-8 rounded-full border border-white/10 bg-white/4 light:bg-black/5 backdrop-blur-[15.2px] overflow-hidden">
                              <button
                                type="button"
                                disabled={
                                  disabled ||
                                  draft.minVisits === null ||
                                  draft.minVisits <= 1
                                }
                                onClick={() => {
                                  const next = (draft.minVisits ?? 2) - 1;
                                  patchDraft({
                                    minVisits: next <= 1 ? null : next,
                                  });
                                }}
                                className="size-8 flex items-center justify-center text-secondary-text hover:text-primary-text transition-colors disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                              >
                                <Minus size={13} />
                              </button>

                              <div className="w-px h-3.5 bg-white/10" />

                              <div className="min-w-9 px-2 text-center text-xs font-semibold text-primary-text tabular-nums select-none">
                                {draft.minVisits ?? 'Any'}
                              </div>

                              <div className="w-px h-3.5 bg-white/10" />

                              <button
                                type="button"
                                disabled={
                                  disabled ||
                                  (draft.minVisits !== null &&
                                    draft.minVisits >= 50)
                                }
                                onClick={() => {
                                  const next =
                                    draft.minVisits === null
                                      ? 2
                                      : Math.min(50, draft.minVisits + 1);
                                  patchDraft({ minVisits: next });
                                }}
                                className="size-8 flex items-center justify-center text-secondary-text hover:text-primary-text transition-colors disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                              >
                                <Plus size={13} />
                              </button>
                            </div>

                            <Text fz={12} className="text-[#C8C8C4]!">
                              or more
                            </Text>
                          </div>
                        </div>

                        {/* Count them */}
                        <div className="flex flex-col gap-1.5">
                          <Text
                            fz={11.5}
                            fw={500}
                            className="text-[#C8C8C4E5]! tracking-normal"
                          >
                            Count them
                          </Text>

                          <SegmentedControl
                            size="xs"
                            fullWidth
                            radius="xl"
                            value={draft.visitsScope}
                            onChange={(v) =>
                              patchDraft({
                                visitsScope: v as LayerDraft['visitsScope'],
                              })
                            }
                            data={[
                              { value: 'total', label: 'In total' },
                              { value: 'each', label: 'At each place' },
                            ]}
                            disabled={disabled}
                            classNames={{
                              root: 'w-full! bg-white/4! light:bg-black/5! border! border-white/6! rounded-full! p-0.5! backdrop-blur-[15.2px]!',
                              indicator:
                                'bg-white/14! light:bg-white! rounded-full! border! border-white/20! light:border-black/5! shadow-[0px_2px_12px_0px_#00000040,0px_1px_0px_0px_#FFFFFF40_inset]!',
                              control: 'border-0!',
                              label:
                                'w-full! block! text-center! text-[#C8C8C4BF]! data-[active]:text-primary-text! font-semibold! text-xs! py-[5.5px]! transition-colors! duration-150!',
                            }}
                          />

                          <Text fz={10.5} className="text-[#C8C8C48C]!">
                            {visitsExplanation}
                          </Text>
                        </div>

                        {/* Minimum stay */}
                        <div className="flex flex-col gap-1.5">
                          <Text
                            fz={11.5}
                            fw={500}
                            className="text-[#C8C8C4E5]! tracking-normal"
                          >
                            Minimum stay
                          </Text>

                          <div className="flex items-center gap-2">
                            <div className="inline-flex items-center h-8 rounded-full border border-white/10 bg-white/4 light:bg-black/5 backdrop-blur-[15.2px] overflow-hidden">
                              <button
                                type="button"
                                disabled={disabled || !draft.dwellMin}
                                onClick={() => {
                                  if (!draft.dwellMin) return;
                                  const next =
                                    draft.dwellMin <= 15
                                      ? null
                                      : draft.dwellMin - 15;
                                  patchDraft({ dwellMin: next });
                                }}
                                className="size-8 flex items-center justify-center text-secondary-text hover:text-primary-text transition-colors disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                              >
                                <Minus size={13} />
                              </button>

                              <div className="w-px h-3.5 bg-white/10" />

                              <div className="min-w-9 px-2 text-center text-xs font-semibold text-primary-text tabular-nums select-none">
                                {draft.dwellMin ?? 'Any'}
                              </div>

                              <div className="w-px h-3.5 bg-white/10" />

                              <button
                                type="button"
                                disabled={
                                  disabled ||
                                  (draft.dwellMin !== null &&
                                    draft.dwellMin >= 1440)
                                }
                                onClick={() => {
                                  const next =
                                    draft.dwellMin === null
                                      ? 15
                                      : Math.min(1440, draft.dwellMin + 15);
                                  patchDraft({ dwellMin: next });
                                }}
                                className="size-8 flex items-center justify-center text-secondary-text hover:text-primary-text transition-colors disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                              >
                                <Plus size={13} />
                              </button>
                            </div>

                            <Text fz={12} className="text-[#C8C8C4]!">
                              minutes per visit
                            </Text>
                          </div>

                          <Text fz={10.5} className="text-[#C8C8C48C]!">
                            Visits with a single location reading have no measurable length and never count.
                          </Text>
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              {/* Visit Pattern Accordion Card */}
              <div
                className="border-stroke-widget light:border-none relative overflow-hidden rounded-2xl! border"
                style={{
                  background: '#0000004D',
                }}
              >
                <button
                  type="button"
                  onClick={() => setPatternSectionOpen(!patternSectionOpen)}
                  className={`w-full flex items-center justify-between text-left cursor-pointer px-3 ${
                    patternSectionOpen ? 'pt-2.5 pb-2.5' : 'py-2.5'
                  }`}
                >
                  <div>
                    <h4 className="text-primary-text text-[13.5px]! font-semibold! leading-tight">
                      Visit pattern
                    </h4>
                    <p className="text-[#C8C8C4B2]! text-[11px]! mt-0.5!">
                      {patternSubtitle}
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {patternRemovedCount !== null && (
                      <span className="text-[#C8C8C4A6]! text-[10.5px]! font-medium! tabular-nums">
                        removes {fmt(patternRemovedCount)}
                      </span>
                    )}
                    <ChevronUp
                      size={16}
                      className={`text-secondary-text transition-transform duration-200 shrink-0 ${
                        patternSectionOpen ? '' : 'rotate-180'
                      }`}
                    />
                  </div>
                </button>

                <AnimatePresence initial={false}>
                  {patternSectionOpen && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.2 }}
                      className="overflow-hidden"
                    >
                      {/* Divider matching the image edge-to-edge */}
                      <div className="w-full border-t border-white/8 light:border-black/5" />

                      <div className="flex flex-col gap-3 px-3 pt-2.5 pb-3">
                        {/* 3 Pattern Options */}
                        <div className="flex flex-col gap-1.5">
                          {TREND_OPTIONS.map((opt) => {
                            const selected = draft.trend === opt.value;
                            return (
                              <button
                                key={opt.value}
                                type="button"
                                disabled={disabled}
                                onClick={() => {
                                  patchDraft(
                                    opt.value === 'any'
                                      ? {
                                          trend: 'any',
                                          trendRecent: null,
                                          trendPrior: null,
                                        }
                                      : { trend: opt.value }
                                  );
                                }}
                                className={`w-full flex items-center gap-3 px-3.5 py-2.5 rounded-full text-left cursor-pointer transition-all ${
                                  selected
                                    ? 'bg-white/10! light:bg-black/8 border border-white/22! light:border-black/30 shadow-[0px_2px_12px_0px_#00000040,0px_1px_0px_0px_#FFFFFF40_inset]!'
                                    : 'bg-white/3 light:bg-black/5 border border-white/6 light:border-black/10 hover:bg-white/6 hover:border-white/15'
                                }`}
                              >
                                <div
                                  className={`size-4 rounded-full border flex items-center justify-center shrink-0 transition-colors ${
                                    selected
                                      ? 'border-white bg-#FAF9F5'
                                      : 'border-white/35 bg-transparent'
                                  }`}
                                >
                                  {selected && (
                                    <div className="size-2 rounded-full bg-white shadow-sm" />
                                  )}
                                </div>
                                <div className="flex flex-col min-w-0">
                                  <span className="text-primary-text/85! font-semibold! text-[12.5px]! leading-snug">
                                    {opt.title}
                                  </span>
                                  <span className="text-[#C8C8C499]! text-[10.5px]! leading-tight mt-0.5!">
                                    {opt.desc}
                                  </span>
                                </div>
                              </button>
                            );
                          })}
                        </div>

                        {/* Trend explanation text */}
                        {trendExplanation && (
                          <Text fz={10.5} className="text-[#C8C8C4CC]! leading-normal px-0.5">
                            {trendExplanation}
                          </Text>
                        )}

                        {/* Recent period & Period before columns */}
                        {draft.trend !== 'any' && (
                          <div className="flex flex-col gap-1.5">
                            <div className="grid grid-cols-2 gap-2.5">
                              {/* Recent period */}
                              <div className="flex flex-col gap-1.5">
                                <Text
                                  fz={11.5}
                                  fw={500}
                                  className="text-[#C8C8C4E5]! tracking-normal"
                                >
                                  Recent period
                                </Text>

                                <div className="w-fit self-start inline-flex items-center h-8 rounded-full border border-white/10 bg-white/4 light:bg-black/5 backdrop-blur-[15.2px] overflow-hidden">
                                  <button
                                    type="button"
                                    disabled={
                                      disabled ||
                                      (draft.trendRecent ?? draft.windowDays ?? 30) <= 7
                                    }
                                    onClick={() => {
                                      const current =
                                        draft.trendRecent ?? draft.windowDays ?? 30;
                                      const next = Math.max(7, current - 7);
                                      patchDraft({ trendRecent: next });
                                    }}
                                    className="size-8 flex items-center justify-center text-secondary-text hover:text-primary-text transition-colors disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                                  >
                                    <Minus size={13} />
                                  </button>

                                  <div className="w-px h-3.5 bg-white/10" />

                                  <div className="min-w-9 px-2 text-center text-xs font-semibold text-primary-text tabular-nums select-none">
                                    {`${draft.trendRecent ?? draft.windowDays ?? 30}d`}
                                  </div>

                                  <div className="w-px h-3.5 bg-white/10" />

                                  <button
                                    type="button"
                                    disabled={
                                      disabled ||
                                      (draft.trendRecent ?? draft.windowDays ?? 30) >= 180
                                    }
                                    onClick={() => {
                                      const current =
                                        draft.trendRecent ?? draft.windowDays ?? 30;
                                      const next = Math.min(180, current + 7);
                                      patchDraft({ trendRecent: next });
                                    }}
                                    className="size-8 flex items-center justify-center text-secondary-text hover:text-primary-text transition-colors disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                                  >
                                    <Plus size={13} />
                                  </button>
                                </div>
                              </div>

                              {/* Period before */}
                              <div className="flex flex-col gap-1.5">
                                <Text
                                  fz={11.5}
                                  fw={500}
                                  className="text-[#C8C8C4E5]! tracking-normal"
                                >
                                  Period before
                                </Text>

                                <Select
                                  size="xs"
                                  allowDeselect={false}
                                  checkIconPosition="right"
                                  rightSectionPointerEvents="none"
                                  rightSection={
                                    <ChevronsUpDown
                                      size={13}
                                      className="text-secondary-text pointer-events-none"
                                    />
                                  }
                                  value={
                                    draft.trendPrior
                                      ? String(draft.trendPrior)
                                      : 'same'
                                  }
                                  onChange={(v) => {
                                    patchDraft({
                                      trendPrior:
                                        v === 'same' || !v ? null : Number(v),
                                    });
                                  }}
                                  data={periodBeforeOptions}
                                  disabled={disabled}
                                  comboboxProps={COMBO}
                                  classNames={glassSelectClassNames}
                                  styles={{
                                    ...glassInputStyles,
                                    ...glassComboboxStyles,
                                  }}
                                />
                              </div>
                            </div>

                            <Text fz={10.5} className="text-[#C8C8C4CC]! pt-2! leading-snug px-0.5">
                              Recent period follows your Time setting ({draft.windowDays ?? 30} days) until you change it.
                            </Text>
                          </div>
                        )}

                        {/* Comes back regularly */}
                        <div className="flex flex-col gap-1.5">
                          <Text
                            fz={11.5}
                            fw={500}
                            className="text-[#C8C8C4E5]! tracking-normal"
                          >
                            Comes back regularly
                          </Text>

                          <div className="flex items-center gap-2">
                            <div className="inline-flex items-center h-8 rounded-full border border-white/10 bg-white/4 light:bg-black/5 backdrop-blur-[15.2px] overflow-hidden">
                              <button
                                type="button"
                                disabled={disabled || !draft.cadenceDays}
                                onClick={() => {
                                  if (!draft.cadenceDays) return;
                                  const next =
                                    draft.cadenceDays <= 7
                                      ? null
                                      : draft.cadenceDays - 7;
                                  patchDraft(
                                    next === null
                                      ? { cadenceDays: null, cadenceTol: null }
                                      : { cadenceDays: next }
                                  );
                                }}
                                className="size-8 flex items-center justify-center text-secondary-text hover:text-primary-text transition-colors disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                              >
                                <Minus size={13} />
                              </button>

                              <div className="w-px h-3.5 bg-white/10" />

                              <div className="min-w-9 px-2 text-center text-xs font-semibold text-primary-text tabular-nums select-none">
                                {draft.cadenceDays ? `${draft.cadenceDays}d` : 'Off'}
                              </div>

                              <div className="w-px h-3.5 bg-white/10" />

                              <button
                                type="button"
                                disabled={
                                  disabled ||
                                  (draft.cadenceDays !== null &&
                                    draft.cadenceDays >= 90)
                                }
                                onClick={() => {
                                  const next =
                                    draft.cadenceDays === null
                                      ? 7
                                      : Math.min(90, draft.cadenceDays + 7);
                                  patchDraft({ cadenceDays: next });
                                }}
                                className="size-8 flex items-center justify-center text-secondary-text hover:text-primary-text transition-colors disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                              >
                                <Plus size={13} />
                              </button>
                            </div>

                            <Text fz={12} className="text-[#C8C8C4]!">
                              days between visits
                            </Text>
                          </div>

                          {rhythm && (
                            <Text fz={11} className="text-[#C8C8C4B2]">
                              {rhythm}
                            </Text>
                          )}
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              {/* Rescue options if audience is too low */}
              {finalCount !== null && finalCount < minDeliverable && (
                <div className="flex flex-col gap-1.5 p-1">
                  <Text fz={12} fw={600} className="text-primary-text">
                    {finalCount === 0
                      ? 'That leaves nobody.'
                      : `That leaves ${fmt(finalCount)} people — too few to run well.`}
                  </Text>
                  {rescue.length > 0 && (
                    <>
                      <Text fz={11} className="text-secondary-text">
                        Try one of these — they use the visitors already
                        found, so there&apos;s no extra cost:
                      </Text>
                      {rescue.map(({ option, layer }) => (
                        <button
                          key={option.key}
                          type="button"
                          disabled={disabled}
                          onClick={() => setDraft(option.draft)}
                          className="border-primary-text/12 bg-primary-text/5 hover:border-primary-text/25 flex cursor-pointer items-center justify-between gap-3 rounded-xl px-3 py-2 text-left shadow-[0px_2px_8px_0px_#00000026,0px_1px_0px_0px_rgba(255,255,255,0.08)_inset] backdrop-blur-md transition-all duration-150 hover:bg-white/10"
                        >
                          <span className="text-primary-text text-xs font-medium">
                            {option.label}
                          </span>
                          <span className="text-primary-text text-xs font-semibold tabular-nums">
                            {layer.count === null
                              ? '—'
                              : `${fmt(layer.count)} people`}
                          </span>
                        </button>
                      ))}
                    </>
                  )}
                  {anyUnevaluable && (
                    <Text fz={11} className="text-secondary-text">
                      This panel only re-filters what was already found.
                    </Text>
                  )}
                </div>
              )}
            </div>
          </ScrollArea>

          {/* 4. Bottom Sticky Button */}
          <div className="pt-0.5">
            <PrimaryGlassBtn
              className="w-full!"
              disabled={disabled || loading || (dirty && !canApply)}
              onClick={() => {
                if (dirty) {
                  onCommit?.(draftToPatch(draft));
                } else if (onConfirmAction) {
                  onConfirmAction();
                }
              }}
            >
              Apply Filters
            </PrimaryGlassBtn>
          </div>
        </>
      )}
    </div>
  );
}
