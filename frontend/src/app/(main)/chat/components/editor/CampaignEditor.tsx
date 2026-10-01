'use client';

/**
 * CampaignEditor — the bespoke Meta-Ads-Manager-style plan editor.
 *
 * Renders a serialized CampaignSpec (Campaign panel · Ad Set tabs · Ad cards)
 * from the `campaign_plan_editor` pending action. Every parameter is editable;
 * ad sets and ads can be added/removed; each ad carries its own copy + image
 * (upload or AI-generate). Geo ZIPs + the MAID audience are shown read-only
 * (locked — confirmed earlier on the map).
 *
 * On Save/Publish it submits the whole edited tree:
 *   onConfirm(JSON.stringify({ action: 'save' | 'publish', spec }))
 * Picking a previous campaign to start from needs a Graph read, so it is the one
 * control that round-trips instead of resolving locally:
 *   onConfirm(JSON.stringify({ action: 'apply_template', campaign_id, adset_ids,
 *                              ad_ids, spec }))
 * `adset_ids` / `ad_ids` are what the user ticked in the copy picker. Omitting
 * them means "the whole campaign" — the fallback when its structure can't be read.
 * The backend (CampaignSpec) is the authority and re-validates; field errors
 * come back keyed by path (e.g. "adsets[0].ads[1].creative.title").
 */

import { useEffect, useRef, useState } from 'react';
import { useParams } from 'next/navigation';
import { Box, Flex, SegmentedControl, Skeleton, Text, Tooltip } from '@mantine/core';
import {
  Rocket,
  Trash2,
  ChevronDown,
  Zap,
  Pencil,
  AlertTriangle,
  Loader2,
} from 'lucide-react';
import { AnimatePresence, motion } from 'framer-motion';

import WidgetLayout from '../widgets/WidgetLayout';
import WidgetHeaderV2 from '@/components/WidgetHeaderV2';
import SecondaryBtn from '@/components/secondaryBtn';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';
import DynamicForm, { type DynamicFormHandle } from '../forms/DynamicForm';
import { listCampaignTreeAction } from '@/actions/ads.actions';
import { useChat } from '@/contexts/ChatContext';
import { useSidebar } from '@/contexts/SidebarContext';
import { trackEvent } from '@/lib/analytics';
import type {
  CampaignEditorSpec,
  CampaignTreeAdSet,
  EditorAd,
  EditorAdSet,
  EditorCatalog,
  EditorDestination,
  EditorOption,
  PendingActionBlock,
} from '@/types/chat';

import {
  attachMedia,
  centsToDollars,
  forValidation,
  frequencyCapOf,
  pixelEventsOf,
  restoreFromLocked,
  roasGoalOf,
  segmentedControlClassNames,
  tooltipStyles,
  validateSpec,
} from './components/editorUtils';
import AdSetPanel from './components/AdSetPanel';
import CampaignGeneralSettings from './components/CampaignGeneralSettings';
import CampaignTemplatePicker from './components/CampaignTemplatePicker';
import EditorNav from './components/EditorNav';
import EditorShell from './components/EditorShell';
import BuildingPane from './components/BuildingPane';
import PreviewPanes, { SET_LIVE, STAY_PAUSED } from './components/PreviewPanes';
import LockedOverlay from './components/LockedOverlay';
import GenerateAdOverlay from '../creative/GenerateAdOverlay';
import LeadFormOverlay from './LeadFormOverlay';

interface Props {
  content: PendingActionBlock['content'];
  onConfirm: (value: string) => void;
  showLogo?: boolean;
  isLatest?: boolean;
}

export default function CampaignEditor({
  content,
  onConfirm,
  showLogo = false,
  isLatest = true,
}: Props) {
  const params = useParams();
  const threadId = params.threadId as string;
  // `streaming` drives the intake phase's build state (the pane fades to a
  // spinner instead of unmounting), `currentStepLabel` is the `update` SSE
  // text the backend already streams during that build ("Building your
  // campaign plan...", "Building your Meta campaign...") and previously went
  // nowhere in the UI.
  const { streaming, currentStepLabel, loading } = useChat();
  const formRef = useRef<DynamicFormHandle>(null);

  const catalog = content.catalog as EditorCatalog | undefined;
  // Which half of the two-phase express editor this is. "intake" — the plan
  // doesn't exist yet; the Campaign pane renders the intake form instead of
  // CampaignGeneralSettings, and there is no spec/catalog to read below.
  const phase = content.phase ?? 'plan';
  // Checks the backend would reject anyway, run before the round trip so the
  // empty box is marked on the ad set that is missing it rather than a banner
  // arriving from the server naming neither.
  const [localErrors, setLocalErrors] = useState<Record<string, string>>({});
  const locks = content.locks ?? { geo: true, audience: true };
  // Told explicitly rather than inferred from `locks`' shape — inference
  // breaks the moment express_unlocked (below) collapses locks to the same
  // shape guide mode ships. Falls back to the old inference for a server that
  // hasn't been redeployed with `publish_mode` yet.
  const isExpress = content.publish_mode
    ? content.publish_mode === 'express'
    : !!locks.campaign && !!locks.adset;
  // "Do it for me" opens with the campaign and ad-set halves — answered on the
  // intake form or defaulted — shown read-only, and the tree collapsed to the
  // one ad set actually rendered (the server mirrors it onto the rest at
  // submit). Unlock & edit drops both: the whole tree becomes real and
  // editable, and the server stops mirroring for this session. Seeded from
  // the server so a save's round trip (which remounts this component) does
  // not silently re-lock what the user just unlocked.
  const [unlocked, setUnlocked] = useState(content.express_unlocked ?? false);
  // Autopilot / Manual footer toggle's confirm-before-discard state. Declared
  // here (every hook must run unconditionally, and phase "intake" returns
  // before the rest of this function) even though it's only read in phase
  // "plan" — see the toggle and relock() below.
  const [showRelockWarning, setShowRelockWarning] = useState(false);
  const adsOnly = isExpress && !unlocked;
  const rawErrors = { ...(content.errors ?? {}), ...localErrors };
  // Ads-only renders ad set 0's card alone (the server copies it onto the rest at
  // submit), so an error keyed to a hidden ad set would mark no control at all.
  // Point it at the one card on screen.
  const errors = adsOnly
    ? Object.fromEntries(
        Object.entries(rawErrors).map(([k, v]) => [
          k.replace(/^adsets\[\d+\]\./, 'adsets[0].'),
          v,
        ])
      )
    : rawErrors;

  const { isSidebarOpen } = useSidebar();

  const [spec, setSpec] = useState<CampaignEditorSpec | null>(() => {
    if (!content.spec) return null;
    const cloned = structuredClone(content.spec);
    if (isExpress && cloned.adsets?.length > 1) {
      cloned.adsets = cloned.adsets.slice(0, 1);
    }
    return cloned;
  });
  // Beside the spec, not inside it — see the payload comment on
  // PendingActionBlock.tracking_method.
  const [trackingMethod, setTrackingMethod] = useState(
    content.tracking_method ?? ''
  );
  // Read once, never edited here — it only decides how an untouched ad card
  // opens, and the pick itself lands on the spec.
  const creativeSource = content.creative_source ?? '';
  const [cardOpen, setCardOpen] = useState(true);
  // Publish's own build state: the gap between the Publish click and the
  // `phase: "preview"` payload landing. `phase` stays "plan" and `content` is
  // still the pre-publish payload for that whole gap (same reason intake's
  // `building` reads `streaming` directly rather than a phase check) — set on
  // submit('publish'), cleared the moment either a new spec lands (a blocked
  // publish re-emits the plan with errors) or the phase actually flips to
  // "preview", both below. NOT set for 'save'/'apply_template' — those keep
  // the tree on screen (the "All changes saved" notice is enough there).
  const [justPublishing, setJustPublishing] = useState(false);
  const [generating, setGenerating] = useState<{ a: number; d: number } | null>(
    null
  );
  const [buildingForm, setBuildingForm] = useState<number | null>(null);
  const [newForms, setNewForms] = useState<{ id: string; name?: string }[]>([]);
  // Which tree node the right pane shows. Persisted per-thread so a save's
  // round trip (the server re-emits this editor, remounting it) reopens on
  // the same node instead of bouncing back to Campaign.
  const navKey = `punk:editor:nav:${threadId}`;
  // Express (adsOnly) opens straight on the one real ad — that's where the
  // creative upload lives, and campaign/ad set are locked summaries anyway.
  // Guide-me opens on the campaign, same as always. Intake has only one real
  // node, Campaign, regardless of adsOnly. Preview opens on the first
  // published ad — the only real nodes it has.
  const defaultNode =
    phase === 'intake'
      ? 'campaign'
      : phase === 'preview'
        ? 'preview-ad-0'
        : adsOnly
          ? 'adset-0-ad-0'
          : 'campaign';
  const [selectedNode, setSelectedNode] = useState<string>(() => {
    if (phase === 'intake' || phase === 'preview') return defaultNode;
    try {
      return sessionStorage.getItem(navKey) || defaultNode;
    } catch {
      return defaultNode;
    }
  });
  const selectNode = (node: string) => {
    // Not persisted for intake/preview: intake has one real node, and
    // remembering it would make phase "plan"'s first render (a fresh emit,
    // not a user click) reopen on the campaign summary instead of falling
    // through to defaultNode (adset-0-ad-0) — where the creative upload
    // actually lives. Preview's nodes (preview-ad-N) don't even exist in
    // plan/intake's node space, so persisting them would do the same thing
    // in reverse the next time this thread opens on the plan phase.
    if (phase === 'intake' || phase === 'preview') {
      setSelectedNode(node);
      return;
    }
    setSelectedNode(node);
    try {
      sessionStorage.setItem(navKey, node);
    } catch {
      /* private-mode / storage disabled — just don't persist */
    }
  };

  // Sync local state from a new `content` prop without remounting — this
  // component now keeps one stable identity across the whole intake → plan
  // transition (see ActiveWidgetRenderer's fixed key), so what a remount used
  // to do for free (re-seed spec/unlocked/trackingMethod from the fresh
  // props) has to happen explicitly here instead. Render-time adjustment
  // (react.dev "you might not need an effect"), not a useEffect — an effect
  // would paint one frame of stale spec before catching up, and this repo's
  // React Compiler config rejects a ref read during render, which is what
  // AdCard's analogous one-shot-apply pattern works around the same way.
  //
  // `wasEmpty` narrows the nav jump to the ONE moment that actually needs
  // it — content.spec turning up for the first time (intake finished
  // building). Every later re-emit with a real spec (a blocked publish's
  // error re-render, apply_template resolving) still re-syncs spec/unlocked/
  // trackingMethod from the server, but leaves selectedNode alone — exactly
  // what the old sessionStorage-on-remount behavior preserved.
  const [seenSpec, setSeenSpec] = useState(content.spec);
  // Guarded against phase "preview": that payload carries no `spec` at all
  // (it has `ads`/`summary`/`tracking` instead), so without this guard the
  // very first preview render would read `content.spec` as newly-undefined,
  // treat that as a real change, and wipe spec/unlocked/trackingMethod to
  // null right as the plan tree they belong to is still on screen behind the
  // build spinner. Preview reads none of those three, so nothing here needs
  // to track it, and a Back / publish-error re-emit of phase "plan" lands on
  // live state instead of a blanked tree.
  if (phase !== 'preview' && content.spec !== seenSpec) {
    const wasEmpty = !seenSpec;
    setSeenSpec(content.spec);
    const newSpec = content.spec ? structuredClone(content.spec) : null;
    if (isExpress && newSpec && newSpec.adsets?.length > 1) {
      newSpec.adsets = newSpec.adsets.slice(0, 1);
    }
    setSpec(newSpec);
    setUnlocked(content.express_unlocked ?? false);
    setTrackingMethod(content.tracking_method ?? '');
    setLocalErrors({});
    setJustPublishing(false);
    if (wasEmpty && content.spec) selectNode(defaultNode);
  }

  // Analogous re-seed for the plan -> preview hop: a wholly new pending_action
  // (different step_key, media_confirm_go_live) arrives on this same
  // persistent mount, same as intake -> plan above. selectedNode carried over
  // from the plan phase (an adset-N-ad-M node) has no meaning in preview's
  // node space, so jump to the first published ad the moment `phase` actually
  // *becomes* "preview" — not on every re-render while it stays "preview",
  // which would fight a click the user just made on the nav.
  const [seenPhase, setSeenPhase] = useState(phase);
  if (phase !== seenPhase) {
    setSeenPhase(phase);
    setJustPublishing(false);
    setCardOpen(true);
    if (phase === 'preview') selectNode(defaultNode);
  }

  // Funnel Step 3: Campaign Created (User completes campaign setup and reaches the point where it is ready to publish)
  const hasTrackedCreatedRef = useRef<string | null>(null);
  useEffect(() => {
    if (phase === 'plan' && spec && hasTrackedCreatedRef.current !== spec.name) {
      hasTrackedCreatedRef.current = spec.name || 'unnamed';
      const adSetsCount = spec.adsets?.length || 0;
      const adsCount = spec.adsets?.reduce((acc, a) => acc + (a.ads?.length || 0), 0) || 0;
      trackEvent('Campaign Created', {
        campaign_name: spec.name,
        objective: spec.objective,
        ad_sets_count: adSetsCount,
        ads_count: adsCount,
        daily_budget: spec.daily_budget ? spec.daily_budget / 100 : undefined,
        publish_mode: isExpress ? 'express' : 'custom',
      });
      trackEvent('campaign_created', {
        campaign_name: spec.name,
        objective: spec.objective,
        ad_sets_count: adSetsCount,
        ads_count: adsCount,
        daily_budget: spec.daily_budget ? spec.daily_budget / 100 : undefined,
        publish_mode: isExpress ? 'express' : 'custom',
      });
    }
  }, [phase, spec, isExpress]);

  // Funnel Step 4: Campaign Published (Publishing is successfully confirmed)
  const hasTrackedPublishedRef = useRef(false);
  useEffect(() => {
    if (phase === 'preview' && !hasTrackedPublishedRef.current) {
      hasTrackedPublishedRef.current = true;
      trackEvent('Campaign Published', {
        campaign_name: content.title || spec?.name,
        objective: spec?.objective,
        ad_account_id: spec?.page_id || undefined,
        publish_mode: isExpress ? 'express' : 'custom',
        status: 'confirmed',
      });
      trackEvent('campaign_published', {
        campaign_name: content.title || spec?.name,
        objective: spec?.objective,
        ad_account_id: spec?.page_id || undefined,
        publish_mode: isExpress ? 'express' : 'custom',
        status: 'confirmed',
      });
    }
  }, [phase, content.title, spec, isExpress]);

  // ── "start from a previous campaign" copy picker ──────────────────────────
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [templateTree, setTemplateTree] = useState<CampaignTreeAdSet[]>([]);
  const [templateLoading, setTemplateLoading] = useState(false);
  const [pickedAdsets, setPickedAdsets] = useState<Set<string>>(new Set());
  const [pickedAds, setPickedAds] = useState<Set<string>>(new Set());

  const pickTemplate = (id: string | null) => {
    setTemplateId(id);
    setTemplateTree([]);
    setPickedAdsets(new Set());
    setPickedAds(new Set());
    setTemplateLoading(!!id);
  };

  useEffect(() => {
    if (!templateId) return;
    let live = true;
    listCampaignTreeAction(templateId)
      .then((adsets) => {
        if (!live) return;
        setTemplateTree(adsets);
        setPickedAdsets(new Set(adsets.map((a) => a.id)));
        setPickedAds(new Set(adsets.flatMap((a) => a.ads.map((ad) => ad.id))));
      })
      .finally(() => {
        if (live) setTemplateLoading(false);
      });
    return () => {
      live = false;
    };
  }, [templateId]);

  const [showSaveNotice, setShowSaveNotice] = useState(false);
  const saveNoticeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const triggerSaveNotice = () => {
    setShowSaveNotice(true);
    if (saveNoticeTimerRef.current) clearTimeout(saveNoticeTimerRef.current);
    saveNoticeTimerRef.current = setTimeout(() => {
      setShowSaveNotice(false);
    }, 5000);
  };
  useEffect(() => {
    return () => {
      if (saveNoticeTimerRef.current) clearTimeout(saveNoticeTimerRef.current);
    };
  }, []);

  // Phase "intake": no spec/catalog exist yet — the form below is what
  // produces them. Same outer shell as the plan phase (so the transition
  // reads as one surface, not two screens), but the content pane is
  // DynamicForm instead of CampaignGeneralSettings, and the ad tree preview
  // is EditorNav's own phase="intake" placeholder. The footer (not
  // DynamicForm's own submit row — suppressed via submitActions={[]}) owns
  // the "Build my plan" action, driving the form through its ref, so intake
  // and plan share one footer shell instead of visibly swapping between them.
  //
  // `building` spans the submit → the new plan landing: the form fades to a
  // spinner over whatever step label the backend is currently streaming
  // ("Building your campaign plan...", "Building your Meta campaign...").
  // This pane staying mounted and merely changing content IS the seamless
  // transition — see the stable key in ActiveWidgetRenderer and the
  // content-sync block above that makes surviving this update possible.
  if (phase === 'intake') {
    const building = streaming || loading;
    return (
      <EditorShell
        showLogo={showLogo}
        collapsible={true}
        open={cardOpen}
        onToggleOpen={() => setCardOpen((v) => !v)}
        headerRight={
          <div className="flex flex-col items-start leading-tight">
            <Text className="text-primary-text/32! text-[10px]! font-bold! tracking-[0.8px]! leading-3.75! uppercase">
              CAMPAIGN
            </Text>
            <Text className="text-primary-text! max-w-105! truncate! text-[17px]! font-semibold! leading-[20.4px]! tracking-[-0.2px]!">
              Campaign Basics
            </Text>
          </div>
        }
        nav={
          <EditorNav
            phase="intake"
            building={building}
            errors={{}}
            locks={locks}
            unlocked={unlocked}
            adsOnly={false}
            selected="campaign"
            onSelect={() => {}}
            onAddAdSet={() => {}}
            onAddAd={() => {}}
          />
        }
        footer={
          <div className="flex w-full items-center justify-end">
            <div className="flex items-center gap-2.5">
              {building || !content.form_schema ? (
                <>
                  <Skeleton height={32} width={68} radius="xl" />
                  <Skeleton height={32} width={120} radius="xl" />
                </>
              ) : (
                <>
                  <SecondaryBtn
                    radius="xl"
                    size="sm"
                    disabled
                    className="text-primary-text/80! border-primary-text/15! border! bg-transparent! text-[13px]! disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    Back
                  </SecondaryBtn>
                  <SecondaryBtn
                    radius="xl"
                    size="sm"
                    onClick={() => formRef.current?.submit('generate')}
                    disabled={!isLatest}
                    className="text-primary-text/80! border-primary-text/15! border! bg-transparent! text-[13px]! cursor-pointer disabled:opacity-30"
                  >
                    Build my plan
                  </SecondaryBtn>
                </>
              )}
            </div>
          </div>
        }
      >
        {building || !content.form_schema ? (
          <BuildingPane label={currentStepLabel} />
        ) : (
          <div className="custom-scrollbar flex min-h-0 w-full md:w-198.5 flex-1 flex-col gap-4 overflow-y-auto p-4 md:p-5">
            <DynamicForm
              ref={formRef}
              schema={content.form_schema}
              initialValues={content.values}
              errors={content.errors ?? content.form_schema.errors}
              submitMode="full"
              submitActions={[]}
              onSubmit={(_action, values) => {
                if (!isLatest) return;
                onConfirm(`Q: ${content.prompt}\nA: ${JSON.stringify({ values })}`);
              }}
            />
          </div>
        )}
      </EditorShell>
    );
  }

  // Phase "preview": the campaign is already built in Meta and PAUSED — this
  // is the last screen before anything spends. Same persistent mount as
  // intake/plan (see ActiveWidgetRenderer's fixed key and the phase-transition
  // re-seed above); `EditorNav phase="preview"` is the ad pager (clicking an
  // ad node drives `selectedAdId` below), and `PreviewPanes` is the body
  // content shared with the legacy standalone `campaign_preview` widget.
  if (phase === 'preview') {
    const ads = content.ads ?? [];
    const adMatch = /^preview-ad-(\d+)$/.exec(selectedNode);
    const selectedAdIndex = adMatch ? Number(adMatch[1]) : 0;
    const selectedAdId = ads[selectedAdIndex]?.ad_id ?? ads[0]?.ad_id ?? null;
    const publishing = (justPublishing && streaming) || streaming || loading;

    const answer = (option: string) => {
      if (!isLatest) return;
      onConfirm(`Q: ${content.prompt || content.title || 'Preview & Publish'}\nA: ${option}`);
    };

    return (
      <EditorShell
        showLogo={showLogo}
        collapsible={true}
        open={cardOpen}
        onToggleOpen={() => setCardOpen((v) => !v)}
        headerRight={
          <div className="flex flex-col items-start leading-tight">
            <Text className="text-primary-text/32! text-[10px]! font-bold! tracking-[0.8px]! leading-3.75! uppercase">
              CAMPAIGN
            </Text>
            <Text className="text-primary-text! max-w-105! truncate! text-[17px]! font-semibold! leading-[20.4px]! tracking-[-0.2px]!">
              {content.title || 'Preview & Publish'}
            </Text>
          </div>
        }
        nav={<EditorNav phase="preview" ads={ads} selected={selectedNode} onSelect={selectNode} errors={{}} locks={locks} unlocked={unlocked} adsOnly={false} onAddAdSet={() => {}} onAddAd={() => {}} />}
        footer={
          <div className="flex w-full items-center justify-end">
            <div className="flex items-center gap-2.5">
              {publishing ? (
                <>
                  <Skeleton height={32} width={114} radius="xl" />
                  <Skeleton height={32} width={96} radius="xl" />
                </>
              ) : (
                <>
                  <SecondaryBtn
                    radius="xl"
                    size="sm"
                    onClick={() => answer(STAY_PAUSED)}
                    disabled={!isLatest}
                    className="text-primary-text/80! border-primary-text/15! border! bg-transparent! text-[13px]! cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    Leave it paused
                  </SecondaryBtn>
                  <PrimaryGlassBtn
                    radius="xl"
                    leftSection={<Rocket size={14} />}
                    onClick={() => answer(SET_LIVE)}
                    disabled={!isLatest}
                    className="bg-primary-text/10! border-primary-text/16! border! text-[13px]! shadow-[0px_8px_32px_0px_#00000059,0px_2px_6px_0px_#00000033,0px_1.5px_0px_0px_#FFFFFF59_inset] disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    Set it live
                  </PrimaryGlassBtn>
                </>
              )}
            </div>
          </div>
        }
      >
        {publishing ? (
          <BuildingPane label={currentStepLabel || 'Publishing to Meta…'} />
        ) : (
          <PreviewPanes content={content} selectedAdId={selectedAdId} />
        )}
      </EditorShell>
    );
  }

  if (!spec || !catalog) {
    return (
      <EditorShell
        showLogo={showLogo}
        headerRight={
          <div className="flex flex-col items-start leading-tight">
            <Text className="text-primary-text/32! text-[10px]! font-bold! tracking-[0.8px]! leading-3.75! uppercase">
              CAMPAIGN
            </Text>
            <Text className="text-primary-text! max-w-105! truncate! text-[17px]! font-semibold! leading-[20.4px]! tracking-[-0.2px]!">
              Campaign Basics
            </Text>
          </div>
        }
        nav={
          <EditorNav
            phase="intake"
            building
            errors={{}}
            locks={locks}
            unlocked={unlocked}
            adsOnly={false}
            selected="campaign"
            onSelect={() => {}}
            onAddAdSet={() => {}}
            onAddAd={() => {}}
          />
        }
        footer={
          <div className="flex w-full items-center justify-end">
            <div className="flex items-center gap-2.5">
              <Skeleton height={32} width={68} radius="xl" />
              <Skeleton height={32} width={120} radius="xl" />
            </div>
          </div>
        }
      >
        <BuildingPane label={currentStepLabel} />
      </EditorShell>
    );
  }

  if (!catalog.destinations_by_objective) {
    return (
      <WidgetLayout mode="full" showLogo={showLogo}>
        <div className="border-stroke-widget bg-primary-widget shadow-widget mb-4 flex flex-col gap-4 rounded-3xl border p-6">
          <WidgetHeaderV2
            icon={<Rocket size={15} className="text-primary-text" />}
            title="Campaign editor unavailable"
            subtitle={
              'This plan was built before the campaign form was updated, so it ' +
              'is missing the conversion-location options. Ask me to rebuild the ' +
              'plan and the editor will come back.'
            }
          />
        </div>
      </WidgetLayout>
    );
  }

  const budgetMode: 'cbo' | 'adset' =
    spec.daily_budget || spec.lifetime_budget ? 'cbo' : 'adset';

  // ── immutable spec updates ────────────────────────────────────────────────
  const update = (fn: (draft: CampaignEditorSpec) => void) => {
    setSpec((prev) => {
      const draft = structuredClone(prev!);
      fn(draft);
      return draft;
    });
    // Any edit clears our own marks; they are re-derived on the next submit.
    // Server errors are left alone — those belong to the tree that was sent.
    setLocalErrors((prev) => (Object.keys(prev).length ? {} : prev));
  };
  const patchAdset = (i: number, patch: Partial<EditorAdSet>) =>
    update((d) => Object.assign(d.adsets[i], patch));
  const patchTargeting = (i: number, patch: Record<string, unknown>) =>
    update((d) => {
      d.adsets[i].targeting = { ...(d.adsets[i].targeting || {}), ...patch };
    });
  const patchAd = (a: number, dIdx: number, patch: Partial<EditorAd>) =>
    update((d) => Object.assign(d.adsets[a].ads[dIdx], patch));
  const patchCreative = (
    a: number,
    dIdx: number,
    patch: Partial<EditorAd['creative']>
  ) => update((d) => Object.assign(d.adsets[a].ads[dIdx].creative, patch));

  const err = (path: string) => errors[path];

  const objective = spec.objective;
  const destinations = catalog.destinations_by_objective[objective] || [];
  const bidStrategies = catalog.bid_strategies_by_objective[objective] || [];
  const minDollars = (catalog.min_budget_cents || 100) / 100;

  // ── objective × conversion location cascade ───────────────────────────────
  const keepOrFirst = (
    current: string | null | undefined,
    opts: EditorOption[]
  ) =>
    opts.some((o) => o.value === current)
      ? (current as string)
      : opts[0]?.value;

  // `objective` is threaded rather than read off `spec`: changeObjective sets it
  // on the draft first, so the closed-over `spec` is one objective stale by the
  // time the cascade needs it to pick a default conversion event.
  const applyDestination = (
    as: EditorAdSet,
    dest: EditorDestination,
    objective: string
  ) => {
    as.destination_type = dest.value;
    as.optimization_goal = keepOrFirst(
      as.optimization_goal,
      dest.optimization_goals
    );
    applyGoal(as, dest, objective);
  };

  const applyGoal = (
    as: EditorAdSet,
    dest: EditorDestination,
    objective: string
  ) => {
    const goal = catalog.goal_rules?.[as.optimization_goal];

    const billing = goal
      ? dest.billing_events.filter((e: EditorOption) => goal.billing_events.includes(e.value))
      : dest.billing_events;
    as.billing_event =
      keepOrFirst(as.billing_event, billing) ?? as.billing_event;

    if (goal && !goal.bid_strategies.includes(as.bid_strategy)) {
      as.bid_strategy = goal.bid_strategies[0];
    }
    if (!catalog.bid_strategies_requiring_amount.includes(as.bid_strategy)) {
      as.bid_amount = null;
    }
    if (as.bid_strategy !== roasGoalOf(catalog).bid_strategy) {
      as.bid_constraints = null;
    }

    if (goal && !goal.allows_frequency_control) {
      as.frequency_control_specs = null;
    } else if (
      goal?.allows_frequency_control &&
      !as.frequency_control_specs?.length
    ) {
      const { event, interval_days, max_frequency } = frequencyCapOf(catalog);
      as.frequency_control_specs = [{ event, interval_days, max_frequency }];
    }
    if (goal && !goal.allows_attribution_spec) as.attribution_spec = null;

    const kind =
      dest.promoted_object_kind_by_goal[as.optimization_goal] ?? 'none';
    if (kind === 'none') as.promoted_object = null;
    if (kind === 'page') {
      as.promoted_object = { page_id: spec.page_id ?? catalog.page_id ?? null };
    }
    // Rebuilt, not merged: promoted_object has one shape per kind and the pixel
    // selects below spread onto whatever is here, so a leftover page_id from the
    // previous goal makes a mixed-kind object the server rejects.
    if (kind === 'pixel') {
      as.promoted_object = {
        // No candidate[0] fallback: a preselected pixel reads as "Punk
        // verified this" and publishes without a look. validateSpec already
        // blocks publish on a blank pixel_id for a pixel-promoting goal.
        pixel_id: as.promoted_object?.pixel_id ?? null,
        custom_event_type:
          as.promoted_object?.custom_event_type ??
          catalog.default_pixel_event_by_objective?.[objective] ??
          pixelEventsOf(catalog)[0],
      };
    }

    if (!dest.requires_lead_form) as.lead_form_draft = null;

    const formats = goal?.ad_formats
      ? dest.ad_formats.filter((f: EditorOption) => goal.ad_formats!.includes(f.value))
      : dest.ad_formats;

    as.ads.forEach((ad) => {
      ad.creative.call_to_action = keepOrFirst(
        ad.creative.call_to_action,
        dest.call_to_actions
      );
      ad.creative.format =
        keepOrFirst(ad.creative.format, formats) ?? ad.creative.format;
      if (!dest.requires_lead_form) ad.creative.lead_gen_form_id = null;
    });
  };

  const changeGoal = (i: number, next: string) =>
    update((d) => {
      const as = d.adsets[i];
      as.optimization_goal = next;
      const dest = (catalog.destinations_by_objective[d.objective] || []).find(
        (x) => x.value === as.destination_type
      );
      if (dest) applyGoal(as, dest, d.objective);
    });

  const changeObjective = (next: string) =>
    update((d) => {
      d.objective = next;
      const nextDests = catalog.destinations_by_objective[next] || [];
      const nextBids = catalog.bid_strategies_by_objective[next] || [];
      if (d.bid_strategy)
        d.bid_strategy = keepOrFirst(d.bid_strategy, nextBids);
      d.adsets.forEach((as) => {
        const dest =
          nextDests.find((x) => x.value === as.destination_type) ??
          nextDests[0];
        if (!dest) return;
        as.bid_strategy = keepOrFirst(as.bid_strategy, nextBids);
        applyDestination(as, dest, next);
      });
    });

  const changeDestination = (i: number, next: string) =>
    update((d) => {
      const dest = destinations.find((x) => x.value === next);
      if (dest) applyDestination(d.adsets[i], dest, d.objective);
    });

  // ── publishing identity ───────────────────────────────────────────────────
  const pageId = spec.page_id ?? catalog.page_id ?? null;
  const pages = catalog.page_candidates ?? [];
  const currentPage = pages.find((pg) => pg.id === pageId);

  const changePage = (next: string) =>
    update((d) => {
      d.page_id = next;
      d.instagram_user_id =
        pages.find((pg) => pg.id === next)?.instagram?.id ?? null;
      d.adsets.forEach((as) => {
        if (as.promoted_object?.page_id) as.promoted_object.page_id = next;
        as.lead_form_draft = null;
        as.ads.forEach((ad) => {
          ad.creative.lead_gen_form_id = null;
          ad.creative.object_story_id = null;
        });
      });
    });

  const setSpecialAdCategories = (next: string[]) =>
    update((d) => {
      d.special_ad_categories = next;
      if (!next.length) d.special_ad_category_country = [];
      else if (!d.special_ad_category_country?.length)
        d.special_ad_category_country = ['US'];
    });

  const blocksDemographics = spec.special_ad_categories.some((c) =>
    catalog.categories_blocking_demographics.includes(c)
  );

  // ── structure edits ───────────────────────────────────────────────────────
  const addAdSet = () => {
    update((d) => {
      const src = d.adsets[d.adsets.length - 1];
      const clone = structuredClone(src);
      clone.name = `Ad Set ${d.adsets.length + 1}`;
      clone.audience_role = 'broad';
      d.adsets.push(clone);
    });
  };
  const removeAdSet = (i: number) => {
    if (spec.adsets.length <= 1) return;
    update((d) => d.adsets.splice(i, 1));
  };
  // One blank clone, or one clone per media patch — the "several ads in one ad
  // set" half of what Ads Manager offers. Each ad gets its own creative and its
  // own reporting, so the images compete on cost.
  //
  // The other half is combining media into ONE ad (AdCard's `extra_media`), which
  // is where a multi-file pick now goes. This path is what "Split into separate
  // ads" and the "+ Add ad" button use.
  const addAds = (a: number, patches?: Partial<EditorAd['creative']>[]) =>
    update((d) => {
      const ads = d.adsets[a].ads;
      const src = ads[ads.length - 1];
      for (const patch of patches?.length ? patches : [undefined]) {
        ads.push({
          name: `${d.adsets[a].name} Ad ${ads.length + 1}`,
          creative: {
            ...src.creative,
            media_id: null,
            image_hash: null,
            video_id: null,
            media_url: null,
            // A clone starts as a single-media ad; the source's combined extras
            // belong to the ad they were combined on.
            extra_media: null,
            ...patch,
          },
        } as EditorAd);
      }
    });
  const removeAd = (a: number, dIdx: number) =>
    update((d) => {
      if (d.adsets[a].ads.length <= 1) return;
      d.adsets[a].ads.splice(dIdx, 1);
    });

  const switchBudgetMode = (mode: 'cbo' | 'adset') =>
    update((d) => {
      if (mode === 'cbo') {
        const total = d.adsets.reduce((s, as) => s + (as.daily_budget || 0), 0);
        d.daily_budget = total || catalog.min_budget_cents;
        d.lifetime_budget = null;
        d.bid_strategy = d.bid_strategy || bidStrategies[0]?.value || null;
        d.is_adset_budget_sharing_enabled = false;
        d.adsets.forEach((as) => {
          as.daily_budget = null;
          as.lifetime_budget = null;
        });
      } else {
        const per = Math.max(
          Math.round(
            (d.daily_budget || catalog.min_budget_cents) / d.adsets.length
          ),
          catalog.min_budget_cents
        );
        d.daily_budget = null;
        d.lifetime_budget = null;
        d.bid_strategy = null;
        d.adsets.forEach((as) => {
          if (!as.daily_budget && !as.lifetime_budget) as.daily_budget = per;
        });
      }
    });

  // ── campaign-level bid target (CBO) ───────────────────────────────────────
  // setCampaignBidStrategy writes this onto EVERY ad set, so the campaign list is
  // only what every ad set's optimization goal accepts. Offering the objective's
  // full list put the same rejected strategy on all of them at once.
  const cboBidStrategies = bidStrategies.filter((s) =>
    spec.adsets.every((as) => {
      const g = catalog.goal_rules?.[as.optimization_goal];
      return !g || g.bid_strategies.includes(s.value);
    })
  );
  const roasGoal = roasGoalOf(catalog);
  const cboNeedsBidAmount =
    budgetMode === 'cbo' &&
    !!spec.bid_strategy &&
    catalog.bid_strategies_requiring_amount.includes(spec.bid_strategy);
  const cboNeedsRoasFloor =
    budgetMode === 'cbo' && spec.bid_strategy === roasGoal.bid_strategy;

  const roasFloorToX = (c?: { roas_average_floor: number } | null) =>
    c ? c.roas_average_floor / roasGoal.scale : '';

  const setCampaignBidStrategy = (next: string) =>
    update((d) => {
      d.bid_strategy = next;
      const capped = catalog.bid_strategies_requiring_amount.includes(next);
      const roas = next === roasGoal.bid_strategy;
      d.adsets.forEach((as) => {
        as.bid_strategy = next;
        // Keep an amount already typed, invent none. This used to fall back to
        // catalog.min_budget_cents — a DAILY BUDGET floor standing in for a
        // per-result bid ceiling, which is a different quantity in the same
        // units, so the auction ran against a number nobody chose. An empty box
        // is safe now: submit() refuses to publish while a capped ad set has no
        // amount, and marks the box.
        as.bid_amount = capped ? as.bid_amount : null;
        // The ROAS floor keeps its seed — roasGoal.scale is 1.0x, "make back
        // what I spend", which is a real default rather than a borrowed number.
        as.bid_constraints = roas
          ? as.bid_constraints || { roas_average_floor: roasGoal.scale }
          : null;
      });
    });

  const setEveryAdsetBidAmount = (cents: number | null) =>
    update((d) => d.adsets.forEach((as) => (as.bid_amount = cents)));

  const setEveryAdsetRoasFloor = (x: number | string) =>
    update((d) => {
      const floor = Math.round(Number(x || 0) * roasGoal.scale);
      d.adsets.forEach(
        (as) => (as.bid_constraints = { roas_average_floor: floor })
      );
    });

  // ── submit ────────────────────────────────────────────────────────────────
  // `media_url` is a client-only preview. The server spec is extra="forbid", so
  // leaving one in does not get ignored — it rejects the WHOLE plan, and the
  // error lands on a field the editor renders no input for. Cards carry their
  // own preview and were being missed, which made any carousel with an uploaded
  // card image unsavable; combined extra media carries one for the same reason.
  const forSubmit = () => {
    const out = structuredClone(spec);
    if (!out) return out;

    // When "Let Punk setup" (express), frontend has only one ad set.
    // The payloader copies that one ad set for both ad sets in the backend.
    if (isExpress && out.adsets?.length === 1) {
      const firstAdset = out.adsets[0];
      const secondAdset = structuredClone(firstAdset);

      const priorSecond = content.spec?.adsets?.[1];
      if (priorSecond) {
        secondAdset.name = priorSecond.name;
        if (priorSecond.audience_role) secondAdset.audience_role = priorSecond.audience_role;
        if (priorSecond.targeting) secondAdset.targeting = structuredClone(priorSecond.targeting);
        if (priorSecond.daily_budget !== undefined) secondAdset.daily_budget = priorSecond.daily_budget;
        if (priorSecond.lifetime_budget !== undefined) secondAdset.lifetime_budget = priorSecond.lifetime_budget;
      } else {
        secondAdset.name = `${firstAdset.name} 2`;
      }

      secondAdset.ads = secondAdset.ads.map((ad, d) => ({
        ...ad,
        name: `${secondAdset.name || 'Ad Set'} Ad ${d + 1}`,
      }));

      out.adsets.push(secondAdset);
    }

    out.adsets.forEach((as) =>
      as.ads.forEach((ad) => {
        for (const slot of [
          ad.creative,
          ...(ad.creative.extra_media ?? []),
          ...(ad.creative.cards ?? []),
        ]) {
          delete (slot as { media_url?: unknown }).media_url;
        }
      })
    );
    return out;
  };

  // Returns whether it actually submitted (false = blocked by validation) —
  // "Save & next" needs to know before it advances the tree selection; a
  // blocked save has to leave the user right where the error is, not move on.
  const submit = (action: 'save' | 'publish'): boolean => {
    if (!isLatest) return false;
    const out = forSubmit();
    // Validate what is on screen, submit the whole tree — see forValidation.
    const blockers = validateSpec(
      forValidation(out, adsOnly),
      catalog,
      pageId,
      action
    );
    const marked = Object.keys(blockers);
    if (marked.length) {
      setLocalErrors(blockers);
      return false;
    }
    setLocalErrors({});
    if (action === 'save') {
      triggerSaveNotice();
    } else {
      setJustPublishing(true);
    }
    onConfirm(
      JSON.stringify({
        action,
        spec: out,
        tracking_method: trackingMethod,
        // Sent every time now, not only when true: the backend's own check is
        // `"unlocked" in submission`, both directions — re-locking (relock()
        // below sets this back to false before calling submit) has to arrive
        // as an explicit false, not silently omitted, or the server never
        // resumes mirroring ad set 0 onto the rest.
        unlocked,
      })
    );
    return true;
  };

  // Autopilot/Manual footer toggle: the count the warning bar names when
  // going back to Autopilot. Manual needs no such bar — nothing is lost by
  // unlocking.
  const addedAdsetCount = content.spec
    ? Math.max(0, spec.adsets.length - (isExpress ? 1 : content.spec.adsets.length))
    : 0;

  // Re-lock: the inverse of "Unlock & edit". No server round trip of its
  // own — the editor makes exactly one call, at publish (submit('save') has
  // no caller in this design) — so this restores locally from `content.spec`,
  // the plan as the server last sent it, and lets the next save carry
  // `unlocked: false` to the backend. The restore itself is
  // restoreFromLocked, in editorUtils — pure and unit-checked there.
  const relock = () => {
    if (!content.spec) return;
    const restored = restoreFromLocked(content.spec, spec);
    if (isExpress && restored.adsets?.length > 1) {
      restored.adsets = restored.adsets.slice(0, 1);
    }
    setSpec(restored);
    setUnlocked(false);
    setLocalErrors({});
    setShowRelockWarning(false);
    selectNode('adset-0-ad-0');
  };

  const applyTemplate = () => {
    if (!isLatest || !templateId) return;
    const out = forSubmit();
    const payload: Record<string, unknown> = {
      action: 'apply_template',
      campaign_id: templateId,
      spec: out,
      // Carried through the round trip, or overlaying a template would silently
      // drop the answer.
      tracking_method: trackingMethod,
    };
    if (templateTree.length) {
      payload.adset_ids = [...pickedAdsets];
      payload.ad_ids = [...pickedAds];
    }
    onConfirm(JSON.stringify(payload));
  };

  const toggleTemplateAdset = (adset: CampaignTreeAdSet, on: boolean) => {
    setPickedAdsets((prev) => {
      const next = new Set(prev);
      if (on) next.add(adset.id);
      else next.delete(adset.id);
      return next;
    });
    setPickedAds((prev) => {
      const next = new Set(prev);
      adset.ads.forEach((ad) => {
        if (on) next.add(ad.id);
        else next.delete(ad.id);
      });
      return next;
    });
  };

  const toggleTemplateAd = (adId: string, on: boolean) =>
    setPickedAds((prev) => {
      const next = new Set(prev);
      if (on) next.add(adId);
      else next.delete(adId);
      return next;
    });

  // Falls back to any error, not just the form-level one: server-side checks now
  // name the field they are about (adsets[0].promoted_object.pixel_id), which
  // marks the right control but sits inside a collapsed ad set panel. The banner
  // is what tells the user there is something to open.
  const rootError = err('__root__') ?? Object.values(errors)[0];
  const objectiveLabel =
    catalog.objectives.find((o) => o.value === spec.objective)?.label ??
    spec.objective;
  // Ads-only edits one ad and every ad set runs it, so counting it per ad set
  // would say "2 / 2" for the single card on screen.
  const totalCents =
    budgetMode === 'cbo'
      ? spec.daily_budget || spec.lifetime_budget || 0
      : spec.adsets.reduce(
          (s, as) => s + (as.daily_budget || as.lifetime_budget || 0),
          0
        );
  const totalDollars = centsToDollars(totalCents);

  // Flat walk order over the tree — what "Save & next" advances through.
  // Mirrors EditorNav's own adsOnly slicing so the two never disagree about
  // what's reachable.
  const nodeOrder = [
    'campaign',
    ...spec.adsets.flatMap((as, i) => [
      `adset-${i}`,
      ...as.ads.map((_, d) => `adset-${i}-ad-${d}`),
    ]),
  ];

  // Whether the WHOLE tree — not just the section on screen — would pass a
  // real publish. Computed every render, not just on click, so the Publish
  // button and the tree's own red dots can both reflect it before the user
  // ever tries. Same rules `submit('publish')` already enforces.
  const publishBlockers = validateSpec(
    forValidation(spec, adsOnly),
    catalog,
    pageId,
    'publish'
  );
  const publishReady = Object.keys(publishBlockers).length === 0;

  const previewBlockReasons = Object.entries(publishBlockers).map(([key, msg]) => {
    if (key.includes('creative.media')) {
      return 'Upload an image or video to preview';
    }
    return msg;
  });
  const mediaReason = previewBlockReasons.find(
    (r) => r === 'Upload an image or video to preview'
  );
  const primaryBlockReason = mediaReason ?? previewBlockReasons[0] ?? null;

  // EditorNav-only: its dots are allowed to flag "still incomplete" ambiently
  // (it's a map, not an accusation). The panes below keep getting the plain
  // `errors` — an untouched field shouldn't turn red before anyone's looked
  // at it just because something elsewhere in the tree isn't done yet.
  const navErrors = { ...errors, ...publishBlockers };

  const errorBanner = rootError && (
    <div
      className="rounded-[14px] bg-[#000000]/30 px-4 py-3.75"
      style={{
        boxShadow: '0px 1px 0px 0px #FFFFFF14 inset',
        backdropFilter: 'blur(65.5999984741211px)',
      }}
    >
      <Flex gap={5}>
        <Box className="mr-1">
          <svg
            width="22"
            height="22"
            viewBox="0 0 22 22"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <g filter="url(#filter0_i_7132_5698_err)">
              <mask id="path-1-inside-1_7132_5698_err" fill="white">
                <path d="M0 11C0 4.92487 4.92487 0 11 0C17.0751 0 22 4.92487 22 11C22 17.0751 17.0751 22 11 22C4.92487 22 0 17.0751 0 11Z" />
              </mask>
              <path
                d="M0 11C0 4.92487 4.92487 0 11 0C17.0751 0 22 4.92487 22 11C22 17.0751 17.0751 22 11 22C4.92487 22 0 17.0751 0 11Z"
                fill="white"
                fillOpacity="0.07"
              />
              <path
                d="M0 11M22 11M22 11M0 11M11 0M22 11M11 22M0 11M11 22V21C5.47715 21 1 16.5228 1 11H0H-1C-1 17.6274 4.37258 23 11 23V22ZM22 11H21C21 16.5228 16.5228 21 11 21V22V23C17.6274 23 23 17.6274 23 11H22ZM11 0V1C16.5228 1 21 5.47715 21 11H22H23C23 4.37258 17.6274 -1 11 -1V0ZM11 0V-1C4.37258 -1 -1 4.37258 -1 11H0H1C1 5.47715 5.47715 1 11 1V0Z"
                fill="#EF4444"
                fillOpacity="0.42"
                mask="url(#path-1-inside-1_7132_5698_err)"
              />
              <path
                d="M11 7.5V11"
                stroke="#EF4444"
                strokeWidth="1.2"
                strokeLinecap="round"
              />
              <path
                d="M11 14.5C11.4142 14.5 11.75 14.1642 11.75 13.75C11.75 13.3358 11.4142 13 11 13C10.5858 13 10.25 13.3358 10.25 13.75C10.25 14.1642 10.5858 14.5 11 14.5Z"
                fill="#EF4444"
              />
            </g>
            <defs>
              <filter
                id="filter0_i_7132_5698_err"
                x="0"
                y="0"
                width="22"
                height="22"
                filterUnits="userSpaceOnUse"
                colorInterpolationFilters="sRGB"
              >
                <feFlood floodOpacity="0" result="BackgroundImageFix" />
                <feBlend
                  mode="normal"
                  in="SourceGraphic"
                  in2="BackgroundImageFix"
                  result="shape"
                />
                <feColorMatrix
                  in="SourceAlpha"
                  type="matrix"
                  values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0"
                  result="hardAlpha"
                />
                <feOffset dy="1" />
                <feComposite
                  in2="hardAlpha"
                  operator="arithmetic"
                  k2="-1"
                  k3="1"
                />
                <feColorMatrix
                  type="matrix"
                  values="0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0.12 0"
                />
                <feBlend
                  mode="normal"
                  in2="shape"
                  result="effect1_innerShadow_7132_5698_err"
                />
              </filter>
            </defs>
          </svg>
        </Box>

        <Box className="flex flex-col items-start justify-center">
          <Text
            fz={14}
            fw={600}
            className="font-inter! leading-4! tracking-wide!"
          >
            Error
          </Text>
          <Text fz={13} fw={400} className="text-secondary-text/40 mt-1!">
            {rootError}
          </Text>
        </Box>
      </Flex>
    </div>
  );

  const complianceBanner = !!spec.compliance_notes?.length && (
    <div
      className="rounded-[14px] bg-[#000000]/30 px-4 py-3.75"
      style={{
        boxShadow: '0px 1px 0px 0px #FFFFFF14 inset',
        backdropFilter: 'blur(65.5999984741211px)',
      }}
    >
      <Flex gap={5}>
        <Box className="mr-1">
          <svg
            width="22"
            height="22"
            viewBox="0 0 22 22"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <g filter="url(#filter0_i_7132_5698)">
              <mask id="path-1-inside-1_7132_5698" fill="white">
                <path d="M0 11C0 4.92487 4.92487 0 11 0C17.0751 0 22 4.92487 22 11C22 17.0751 17.0751 22 11 22C4.92487 22 0 17.0751 0 11Z" />
              </mask>
              <path
                d="M0 11C0 4.92487 4.92487 0 11 0C17.0751 0 22 4.92487 22 11C22 17.0751 17.0751 22 11 22C4.92487 22 0 17.0751 0 11Z"
                fill="white"
                fillOpacity="0.07"
              />
              <path
                d="M0 11M22 11M22 11M0 11M11 0M22 11M11 22M0 11M11 22V21C5.47715 21 1 16.5228 1 11H0H-1C-1 17.6274 4.37258 23 11 23V22ZM22 11H21C21 16.5228 16.5228 21 11 21V22V23C17.6274 23 23 17.6274 23 11H22ZM11 0V1C16.5228 1 21 5.47715 21 11H22H23C23 4.37258 17.6274 -1 11 -1V0ZM11 0V-1C4.37258 -1 -1 4.37258 -1 11H0H1C1 5.47715 5.47715 1 11 1V0Z"
                fill="#F4964E"
                fillOpacity="0.42"
                mask="url(#path-1-inside-1_7132_5698)"
              />
              <path
                d="M11 7.5V11"
                stroke="#F4964E"
                strokeWidth="1.2"
                strokeLinecap="round"
              />
              <path
                d="M11 14.5C11.4142 14.5 11.75 14.1642 11.75 13.75C11.75 13.3358 11.4142 13 11 13C10.5858 13 10.25 13.3358 10.25 13.75C10.25 14.1642 10.5858 14.5 11 14.5Z"
                fill="#F4964E"
              />
            </g>
            <defs>
              <filter
                id="filter0_i_7132_5698"
                x="0"
                y="0"
                width="22"
                height="22"
                filterUnits="userSpaceOnUse"
                colorInterpolationFilters="sRGB"
              >
                <feFlood floodOpacity="0" result="BackgroundImageFix" />
                <feBlend
                  mode="normal"
                  in="SourceGraphic"
                  in2="BackgroundImageFix"
                  result="shape"
                />
                <feColorMatrix
                  in="SourceAlpha"
                  type="matrix"
                  values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0"
                  result="hardAlpha"
                />
                <feOffset dy="1" />
                <feComposite
                  in2="hardAlpha"
                  operator="arithmetic"
                  k2="-1"
                  k3="1"
                />
                <feColorMatrix
                  type="matrix"
                  values="0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0.12 0"
                />
                <feBlend
                  mode="normal"
                  in2="shape"
                  result="effect1_innerShadow_7132_5698"
                />
              </filter>
            </defs>
          </svg>
        </Box>

        <Box className="flex flex-col items-start">
          {/* Notes come from four sources — special-category removals, unavailable
              platforms, placement restrictions and a budget raised to Meta's
              per-ad-set minimum. The heading has to cover all four; naming only
              the category case mislabels the other three. */}
          <Text
            fz={14}
            fw={600}
            className="font-inter! leading-4! tracking-wide!"
          >
            Adjustments applied to this plan
          </Text>
          {spec.compliance_notes.length < 2 ? (
            <Text fz={13} fw={400} className="text-secondary-text/40 mt-1!">
              {spec.compliance_notes![0]}
            </Text>
          ) : (
            <ul className="text-secondary-text/40 mt-1 list-disc space-y-0.5 pl-4">
              {spec.compliance_notes!.map((note, i) => (
                <li key={i}>
                  <Text fz={13} fw={400} className="text-secondary-text/40">
                    {note}
                  </Text>
                </li>
              ))}
            </ul>
          )}
        </Box>
      </Flex>
    </div>
  );

  // ── locked-summary rows ("do it for me", pre-unlock) ──────────────────────
  const campaignSummaryRows = [
    { label: 'Objective', value: objectiveLabel },
    {
      label: 'Budget',
      value:
        totalDollars != null
          ? `$${totalDollars}${budgetMode === 'cbo' ? '/day (campaign)' : '/day total'}`
          : '—',
    },
    { label: 'Page', value: currentPage?.name || '—' },
    {
      label: 'Special ad categories',
      value: spec.special_ad_categories.length
        ? spec.special_ad_categories.join(', ')
        : 'None',
    },
  ];

  const adsetSummaryRows = (as: EditorAdSet) => {
    const dest = destinations.find((d) => d.value === as.destination_type);
    const goalLabel =
      dest?.optimization_goals.find((g) => g.value === as.optimization_goal)
        ?.label ?? as.optimization_goal;
    const bidLabel =
      bidStrategies.find((b) => b.value === as.bid_strategy)?.label ??
      as.bid_strategy;
    const budget =
      budgetMode === 'cbo'
        ? 'Shares campaign budget'
        : centsToDollars(as.daily_budget ?? as.lifetime_budget) != null
          ? `$${centsToDollars(as.daily_budget ?? as.lifetime_budget)}${as.lifetime_budget != null ? ' lifetime' : '/day'}`
          : '—';
    return [
      { label: 'Conversion location', value: dest?.label ?? as.destination_type },
      { label: 'Optimization goal', value: goalLabel },
      { label: 'Bid strategy', value: bidLabel },
      { label: 'Budget', value: budget },
    ];
  };

  const isAdTab = /^adset-\d+-ad-\d+$/.test(selectedNode);
  const nodeIdx = nodeOrder.indexOf(selectedNode);
  const nextNode =
    nodeIdx >= 0 && nodeIdx < nodeOrder.length - 1
      ? nodeOrder[nodeIdx + 1]
      : undefined;
  const prevNode = nodeIdx > 0 ? nodeOrder[nodeIdx - 1] : undefined;

  const goNext = () => {
    if (nextNode) {
      selectNode(nextNode);
      triggerSaveNotice();
    } else {
      if (!publishReady) {
        setLocalErrors(publishBlockers);
        return;
      }
      submit('publish');
    }
  };

  const goBack = () => {
    if (prevNode) {
      selectNode(prevNode);
      triggerSaveNotice();
    }
  };

  // Header active node breadcrumbs and remove action
  const activeNodeInfo = (() => {
    if (selectedNode === 'campaign') {
      return {
        eyebrow: 'CAMPAIGN',
        title: spec.name || 'Campaign Basics',
        canDelete: false,
        onDelete: undefined,
      };
    }
    const m = /^adset-(\d+)(?:-ad-(\d+))?$/.exec(selectedNode);
    if (!m) return { eyebrow: '', title: '', canDelete: false, onDelete: undefined };
    const aIdx = Number(m[1]);
    const dIdx = m[2] != null ? Number(m[2]) : undefined;
    const as = spec.adsets[aIdx];
    if (!as) return { eyebrow: '', title: '', canDelete: false, onDelete: undefined };

    if (dIdx == null) {
      return {
        eyebrow: `AD SET ${aIdx + 1}`,
        title: as.name || `Ad Set ${aIdx + 1}`,
        canDelete: spec.adsets.length > 1,
        onDelete: () => removeAdSet(aIdx),
      };
    }

    const ad = as.ads[dIdx];
    return {
      eyebrow: `AD SET ${aIdx + 1}`,
      title: ad?.name || `${as.name || 'Ad Set'} Ad ${dIdx + 1}`,
      canDelete: as.ads.length > 1,
      onDelete: () => removeAd(aIdx, dIdx),
    };
  })();

  return (
    <WidgetLayout
      mode="full"
      showLogo={showLogo}
      className={`w-full max-w-256.75! 2xl:px-0 ${isSidebarOpen ? 'xl:px-2' : 'lg:pr-1.5'}`}
    >
      <Box className="relative w-full max-w-256.75 mx-auto rounded-[20px]!">
        <Box
          className={`border-white/8! bg-white/1! flex w-full flex-col overflow-hidden border transition-all duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] will-change-[max-width,height] ${
            cardOpen
              ? 'h-[85vh] max-h-[85vh] max-w-256.75 mx-auto rounded-[20px]!'
              : 'h-14 md:h-20 max-h-14 md:max-h-20 max-w-210 mx-auto rounded-4xl!'
          }`}
          style={{
            backdropFilter: 'blur(75.9px)',
            WebkitBackdropFilter: 'blur(75.9px)',
            boxShadow: `
              0px 1px 0px 0px #FFFFFF17 inset,
              0px 32px 80px 0px #000000A6
            `,
          }}
        >
          {/* ── Top Header matching Image 1 ─────────────────────────────────── */}
          <div
            onClick={() => setCardOpen((v) => !v)}
            className={`border-primary-text/8 relative flex shrink-0 cursor-pointer select-none items-stretch bg-primary-text/1 transition-colors duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] hover:bg-white/2 ${
              cardOpen ? 'border-b' : 'border-b-0'
            }`}
          >
            {/* Mobile: single compact row */}
            <div className="flex min-w-0 flex-1 items-center gap-2.5 px-4 py-3 pr-12 md:hidden">
              <Rocket size={18} className="text-primary-text shrink-0" />
              <div className="flex min-w-0 flex-col leading-tight">
                {activeNodeInfo.eyebrow && (
                  <Text className="text-primary-text/32! text-[10px]! font-bold! tracking-[0.8px]! leading-3.75! uppercase">
                    {activeNodeInfo.eyebrow}
                  </Text>
                )}
                <Text className="text-primary-text! w-full! truncate! text-[15px]! font-semibold! leading-5! tracking-[-0.2px]!">
                  {activeNodeInfo.title || 'Campaign Editor'}
                </Text>
              </div>
            </div>

            {/* Chevron pinned to top-right on mobile */}
            <div className="absolute right-3 top-1/2 -translate-y-1/2 md:hidden">
              <div className="text-secondary-text flex h-7 w-7 items-center justify-center rounded-full">
                <ChevronDown
                  size={16}
                  className={`transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] ${
                    cardOpen ? 'rotate-0' : 'rotate-180'
                  }`}
                />
              </div>
            </div>

            {/* ── Desktop: two-column layout ── */}
            <div className="hidden w-full md:flex md:flex-row md:items-stretch">
              {/* Left: Rocket + title */}
              <div className="border-primary-text/8 flex w-58 shrink-0 items-center! gap-2.25 border-r px-4 py-7">
                <Rocket size={24} className="text-primary-text" />
                <Text fz={13} fw={600} lh={'19.5px'} className="text-primary-text!">
                  Campaign Editor
                </Text>
              </div>

              {/* Right: breadcrumb + actions */}
              <div className="flex min-w-0 flex-1 items-center justify-between px-8 py-[12.5px]">
                {activeNodeInfo.title ? (
                  <div className="flex min-w-0 items-center gap-2.5">
                    <div className="flex w-full min-w-0 flex-col items-start leading-tight">
                      {activeNodeInfo.eyebrow && (
                        <Text className="text-primary-text/32! text-[10px]! font-bold! tracking-[0.8px]! leading-3.75! uppercase">
                          {activeNodeInfo.eyebrow}
                        </Text>
                      )}
                      <Text className="text-primary-text! w-full! truncate! text-[17px]! font-semibold! leading-[20.4px]! tracking-[-0.2px]!">
                        {activeNodeInfo.title}
                      </Text>
                    </div>
                  </div>
                ) : (
                  <div />
                )}

                <div className="border-primary-text/8 flex items-center gap-2 pl-3">
                  {activeNodeInfo.canDelete && activeNodeInfo.onDelete && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        activeNodeInfo.onDelete?.();
                      }}
                      title="Delete"
                      className="text-secondary-text hover:text-red-400 hover:bg-red-500/10 flex h-7 w-7 cursor-pointer items-center justify-center rounded-full transition-colors"
                    >
                      <Trash2 size={15} />
                    </button>
                  )}
                  <div
                    className="text-secondary-text hover:text-primary-text flex h-7 w-7 items-center justify-center rounded-full transition-colors"
                    title={cardOpen ? 'Collapse' : 'Expand'}
                  >
                    <ChevronDown
                      size={16}
                      className={`transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] ${
                        cardOpen ? 'rotate-0' : 'rotate-180'
                      }`}
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

            {cardOpen && (
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden animate-in fade-in-0 duration-400 ease-out">
              {/* ── Nav + Content Pane ─────────────────────────────────────────── */}
              <div className="flex min-h-0 flex-1 flex-col md:flex-row overflow-hidden">
            <EditorNav
              spec={spec}
              errors={navErrors}
              locks={locks}
              unlocked={unlocked}
              adsOnly={adsOnly}
              selected={selectedNode}
              onSelect={selectNode}
              onAddAdSet={addAdSet}
              onAddAd={(i) => {
                const newIndex = spec.adsets[i].ads.length;
                addAds(i);
                selectNode(`adset-${i}-ad-${newIndex}`);
              }}
            />

            <div className="relative flex min-h-0 w-full md:w-198.5 flex-1 flex-col overflow-hidden">
              {justPublishing && streaming && (
                // The gap between Publish and the preview payload landing —
                // an overlay, not a content swap, so the tree stays mounted
                // underneath exactly as the user left it (a validation
                // rejection clears this and re-reveals it with errors marked,
                // rather than having to be rebuilt from scratch).
                <div className="bg-primary-bg/90! absolute inset-0 z-10 flex flex-col items-center justify-center gap-3">
                  <Loader2 className="text-primary-text/50 h-6 w-6 animate-spin" />
                  <Text className="text-secondary-text/60 text-[13px]">
                    {currentStepLabel || 'Publishing to Meta…'}
                  </Text>
                </div>
              )}
              {!isAdTab && errorBanner && <div className="px-5 pt-3">{errorBanner}</div>}
              {!isAdTab && complianceBanner && <div className="px-5 pt-3">{complianceBanner}</div>}

              {selectedNode === 'campaign' &&
                (locks.campaign && !unlocked ? (
                  <LockedOverlay
                    onUnlock={() => {
                      setUnlocked(true);
                      setShowRelockWarning(false);
                    }}
                  >
                    <CampaignTemplatePicker
                      previousCampaigns={catalog.previous_campaigns}
                      templateId={templateId}
                      onPickTemplate={pickTemplate}
                      templateLoading={templateLoading}
                      templateTree={templateTree}
                      pickedAdsets={pickedAdsets}
                      pickedAds={pickedAds}
                      onToggleAdset={toggleTemplateAdset}
                      onToggleAd={toggleTemplateAd}
                      onApplyTemplate={applyTemplate}
                    />
                    <CampaignGeneralSettings
                      spec={spec}
                      catalog={catalog}
                      errors={errors}
                      pages={pages}
                      pageId={pageId}
                      budgetMode={budgetMode}
                      bidStrategies={cboBidStrategies}
                      minDollars={minDollars}
                      cboNeedsBidAmount={cboNeedsBidAmount}
                      cboNeedsRoasFloor={cboNeedsRoasFloor}
                      roasGoal={roasGoal}
                      roasFloorToX={roasFloorToX}
                      trackingMethod={trackingMethod}
                      setTrackingMethod={setTrackingMethod}
                      update={update}
                      changePage={changePage}
                      changeObjective={changeObjective}
                      setSpecialAdCategories={setSpecialAdCategories}
                      switchBudgetMode={switchBudgetMode}
                      setCampaignBidStrategy={setCampaignBidStrategy}
                      setEveryAdsetBidAmount={setEveryAdsetBidAmount}
                      setEveryAdsetRoasFloor={setEveryAdsetRoasFloor}
                    />
                  </LockedOverlay>
                ) : (
                  <div className="custom-scrollbar flex min-h-0 w-full flex-1 flex-col gap-4 overflow-y-auto p-5">
                    <CampaignTemplatePicker
                      previousCampaigns={catalog.previous_campaigns}
                      templateId={templateId}
                      onPickTemplate={pickTemplate}
                      templateLoading={templateLoading}
                      templateTree={templateTree}
                      pickedAdsets={pickedAdsets}
                      pickedAds={pickedAds}
                      onToggleAdset={toggleTemplateAdset}
                      onToggleAd={toggleTemplateAd}
                      onApplyTemplate={applyTemplate}
                    />
                    <CampaignGeneralSettings
                      spec={spec}
                      catalog={catalog}
                      errors={errors}
                      pages={pages}
                      pageId={pageId}
                      budgetMode={budgetMode}
                      bidStrategies={cboBidStrategies}
                      minDollars={minDollars}
                      cboNeedsBidAmount={cboNeedsBidAmount}
                      cboNeedsRoasFloor={cboNeedsRoasFloor}
                      roasGoal={roasGoal}
                      roasFloorToX={roasFloorToX}
                      trackingMethod={trackingMethod}
                      setTrackingMethod={setTrackingMethod}
                      update={update}
                      changePage={changePage}
                      changeObjective={changeObjective}
                      setSpecialAdCategories={setSpecialAdCategories}
                      switchBudgetMode={switchBudgetMode}
                      setCampaignBidStrategy={setCampaignBidStrategy}
                      setEveryAdsetBidAmount={setEveryAdsetBidAmount}
                      setEveryAdsetRoasFloor={setEveryAdsetRoasFloor}
                    />
                  </div>
                ))}

              {(() => {
                const m = /^adset-(\d+)(?:-ad-(\d+))?$/.exec(selectedNode);
                if (!m) return null;
                const i = Number(m[1]);
                const as = spec.adsets[i];
                if (!as) return null;
                const adIndex = m[2] != null ? Number(m[2]) : undefined;

                if (adIndex == null && locks.adset && !unlocked) {
                  return (
                    <LockedOverlay
                      onUnlock={() => {
                        setUnlocked(true);
                        setShowRelockWarning(false);
                      }}
                    >
                      <AdSetPanel
                        adset={as}
                        index={i}
                        catalog={catalog}
                        errors={errors}
                        locks={locks}
                        minDollars={minDollars}
                        budgetMode={budgetMode}
                        blocksDemographics={blocksDemographics}
                        destinations={destinations}
                        bidStrategies={bidStrategies}
                        canRemove={spec.adsets.length > 1}
                        onRemove={() => removeAdSet(i)}
                        onChangeDestination={(v) => changeDestination(i, v)}
                        onChangeGoal={(v) => changeGoal(i, v)}
                        campaignIsLifetime={spec.lifetime_budget != null}
                        patchAdset={(p) => patchAdset(i, p)}
                        patchTargeting={(p) => patchTargeting(i, p)}
                        onAddAd={(patches) => addAds(i, patches)}
                        onRemoveAd={(d) => removeAd(i, d)}
                        patchAd={(d, p) => patchAd(i, d, p)}
                        patchCreative={(d, p) => patchCreative(i, d, p)}
                        onGenerate={(d) => setGenerating({ a: i, d })}
                        extraLeadForms={newForms}
                        onBuildLeadForm={() => setBuildingForm(i)}
                        pageId={pageId}
                        page={currentPage}
                        creativeSource={creativeSource}
                        show="settings"
                      />
                    </LockedOverlay>
                  );
                }
                if (adIndex == null) {
                  return (
                    <div className="custom-scrollbar flex min-h-0 w-full flex-1 flex-col gap-4 overflow-y-auto p-5">
                      <AdSetPanel
                        adset={as}
                        index={i}
                        catalog={catalog}
                        errors={errors}
                        locks={locks}
                        minDollars={minDollars}
                        budgetMode={budgetMode}
                        blocksDemographics={blocksDemographics}
                        destinations={destinations}
                        bidStrategies={bidStrategies}
                        canRemove={spec.adsets.length > 1}
                        onRemove={() => removeAdSet(i)}
                        onChangeDestination={(v) => changeDestination(i, v)}
                        onChangeGoal={(v) => changeGoal(i, v)}
                        campaignIsLifetime={spec.lifetime_budget != null}
                        patchAdset={(p) => patchAdset(i, p)}
                        patchTargeting={(p) => patchTargeting(i, p)}
                        onAddAd={(patches) => addAds(i, patches)}
                        onRemoveAd={(d) => removeAd(i, d)}
                        patchAd={(d, p) => patchAd(i, d, p)}
                        patchCreative={(d, p) => patchCreative(i, d, p)}
                        onGenerate={(d) => setGenerating({ a: i, d })}
                        extraLeadForms={newForms}
                        onBuildLeadForm={() => setBuildingForm(i)}
                        pageId={pageId}
                        page={currentPage}
                        creativeSource={creativeSource}
                        show="settings"
                      />
                    </div>
                  );
                }
                return (
                  <div className="flex h-full min-h-0 w-full flex-1 overflow-hidden">
                    <AdSetPanel
                      adset={as}
                      index={i}
                      catalog={catalog}
                      errors={errors}
                      locks={locks}
                      minDollars={minDollars}
                      budgetMode={budgetMode}
                      blocksDemographics={blocksDemographics}
                      destinations={destinations}
                      bidStrategies={bidStrategies}
                      canRemove={spec.adsets.length > 1}
                      onRemove={() => removeAdSet(i)}
                      onChangeDestination={(v) => changeDestination(i, v)}
                      onChangeGoal={(v) => changeGoal(i, v)}
                      campaignIsLifetime={spec.lifetime_budget != null}
                      patchAdset={(p) => patchAdset(i, p)}
                      patchTargeting={(p) => patchTargeting(i, p)}
                      onAddAd={(patches) => addAds(i, patches)}
                      onRemoveAd={(d) => removeAd(i, d)}
                      patchAd={(d, p) => patchAd(i, d, p)}
                      patchCreative={(d, p) => patchCreative(i, d, p)}
                      onGenerate={(d) => setGenerating({ a: i, d })}
                      extraLeadForms={newForms}
                      onBuildLeadForm={() => setBuildingForm(i)}
                      pageId={pageId}
                      page={currentPage}
                      creativeSource={creativeSource}
                      show="ad"
                      adIndex={adIndex}
                    />
                  </div>
                );
              })()}
            </div>
          </div>

          {/* Autopilot/Manual re-lock confirmation — armed by the footer toggle
              below going back to Autopilot, since that discards whatever was
              set while unlocked. Manual needs no such bar: nothing is lost by
              unlocking. Full-width, not split into nav/content columns like
              the footer — it's a message, not navigation. */}
          {showRelockWarning && (
            <div className="border-primary-text/8 flex items-center justify-between gap-4 border-t bg-amber-500/8 px-5 py-3">
              <div className="text-primary-text/80 flex items-center gap-2 text-[12.5px]">
                <AlertTriangle size={14} className="shrink-0 text-amber-400" />
                <span>
                  Punk rebuilds the campaign and ad-set settings
                  {addedAdsetCount > 0 &&
                    ` and drops the ${addedAdsetCount} ad set${addedAdsetCount === 1 ? '' : 's'} you added`}
                  . Your ad copy and creative stay.
                </span>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <SecondaryBtn
                  radius="xl"
                  size="xs"
                  onClick={() => setShowRelockWarning(false)}
                  className="text-primary-text/80! border-primary-text/15! border! bg-transparent! text-[12px]! cursor-pointer"
                >
                  Cancel
                </SecondaryBtn>
                <SecondaryBtn
                  radius="xl"
                  size="xs"
                  onClick={relock}
                  className="text-primary-text/80! border-primary-text/15! border! bg-transparent! text-[12px]! cursor-pointer"
                >
                  Yes, rebuild
                </SecondaryBtn>
              </div>
            </div>
          )}

          {/* ── Bottom Sticky Footer ───────────────────────── */}
          <div className="flex shrink-0 flex-col md:flex-row items-stretch bg-primary-text/1">
            {/* Left Column (232px) */}
            <div className="border-primary-text/8 hidden md:flex w-58 shrink-0 items-center border-r p-3 " />

            {/* Right: Autopilot/Manual + "● All changes saved" on left, Back & Next on right (794px) */}
            <div className="flex w-full md:w-198.5 min-w-0 flex-1 items-center justify-between border-t border-primary-text/8 px-4 md:px-5 py-3 flex-wrap gap-2.5">
              <div className="flex items-center gap-3">
                {isExpress && (
                  <SegmentedControl
                    size="xs"
                    value={unlocked ? 'manual' : 'auto'}
                    onChange={(v) => {
                      if (v === 'manual') {
                        setUnlocked(true);
                        setShowRelockWarning(false);
                      } else {
                        setShowRelockWarning(true);
                      }
                    }}
                    data={[
                      {
                        value: 'auto',
                        label: (
                          <span className="flex items-center gap-1.5">
                            <Zap size={12} /> Autopilot
                          </span>
                        ),
                      },
                      {
                        value: 'manual',
                        label: (
                          <span className="flex items-center gap-1.5">
                            <Pencil size={12} /> Manual
                          </span>
                        ),
                      },
                    ]}
                    classNames={segmentedControlClassNames}
                  />
                )}
                <AnimatePresence>
                  {showSaveNotice && (
                    <motion.div
                      initial={{ opacity: 0, scale: 0.95 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, scale: 0.95 }}
                      transition={{ duration: 0.2 }}
                      className="flex items-center gap-2 text-[12.5px] font-medium text-primary-text/80"
                    >
                      <Text className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399]" />
                      <Text>All changes saved</Text>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              {/* Right: Dynamic Back & Next / Preview buttons */}
              <div className="flex items-center gap-2.5">
                {(justPublishing && streaming) || streaming || loading ? (
                  <>
                    <Skeleton height={32} width={68} radius="xl" />
                    <Skeleton height={32} width={nextNode ? 68 : 84} radius="xl" />
                  </>
                ) : (
                  <>
                    <SecondaryBtn
                      radius="xl"
                      size="sm"
                      onClick={goBack}
                      disabled={!prevNode}
                      className="text-primary-text/80! border-primary-text/15! border! bg-transparent! text-[13px]! disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                      Back
                    </SecondaryBtn>

                    {!nextNode && !publishReady && primaryBlockReason && (
                      <div
                        className="flex items-center gap-1.5 text-amber-400 text-[12px] bg-amber-500/10 border border-amber-500/20 px-3 py-1.5 rounded-full animate-in fade-in-0 duration-200"
                        title={previewBlockReasons.join('\n')}
                      >
                        <AlertTriangle size={13} className="shrink-0 text-amber-400" />
                        <span className="max-w-65 truncate font-medium">{primaryBlockReason}</span>
                      </div>
                    )}

                    <Tooltip
                      label={
                        previewBlockReasons.length > 1 ? (
                          <div className="flex flex-col gap-1 py-0.5 text-left">
                            <span className="font-semibold text-[11.5px] text-white">Cannot preview yet:</span>
                            <ul className="list-disc pl-3 text-[11px] space-y-0.5 text-primary-text/90">
                              {previewBlockReasons.map((r, idx) => (
                                <li key={idx}>{r}</li>
                              ))}
                            </ul>
                          </div>
                        ) : (
                          primaryBlockReason
                        )
                      }
                      disabled={!(!nextNode && !publishReady)}
                      multiline
                      withArrow
                      position="top-end"
                      styles={tooltipStyles}
                    >
                      <span
                        className="inline-block"
                        onClick={() => {
                          if (!nextNode && !publishReady) {
                            setLocalErrors(publishBlockers);
                          }
                        }}
                      >
                        <SecondaryBtn
                          radius="xl"
                          size="sm"
                          onClick={goNext}
                          disabled={!nextNode && !publishReady}
                          className="text-primary-text/80! border-primary-text/15! border! bg-transparent! text-[13px]! cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          {nextNode ? `Next` : 'Preview'}
                        </SecondaryBtn>
                      </span>
                    </Tooltip>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

          {generating && (
            <GenerateAdOverlay
              type="image"
              threadId={threadId}
              onClose={() => setGenerating(null)}
              onAdd={(generated) => {
                if (!generated.length) return;
                const asCreative = (a: (typeof generated)[number]) => ({
                  media_id: a.id ?? null,
                  media_url: a.url ?? null,
                  media_kind: 'image' as const,
                  image_hash: null,
                  video_id: null,
                });
                update((d) => {
                  const cr = d.adsets[generating.a].ads[generating.d].creative;
                  Object.assign(
                    cr,
                    attachMedia(
                      cr,
                      generated.map(asCreative),
                      catalog.creative_limits.max_media_per_ad
                    )
                  );
                });
                setGenerating(null);
              }}
            />
          )}

          {buildingForm !== null && spec.adsets[buildingForm] && (
            <LeadFormOverlay
              catalog={catalog}
              pageId={pageId}
              draft={spec.adsets[buildingForm].lead_form_draft}
              campaignName={spec.name}
              adHeadline={spec.adsets[buildingForm].ads[0]?.creative.title}
              onClose={() => setBuildingForm(null)}
              onSaveDraft={(draft) => {
                update((d) => {
                  const as = d.adsets[buildingForm];
                  as.lead_form_draft = draft;
                  as.ads.forEach((ad) => (ad.creative.lead_gen_form_id = null));
                });
                setBuildingForm(null);
              }}
              onCreated={(form) => {
                setNewForms((prev) => [...prev, form]);
                update((d) => {
                  const as = d.adsets[buildingForm];
                  as.lead_form_draft = null;
                  as.ads.forEach(
                    (ad) => (ad.creative.lead_gen_form_id = form.id)
                  );
                });
                setBuildingForm(null);
              }}
            />
          )}
        </Box>
      </Box>
    </WidgetLayout>
  );
}
