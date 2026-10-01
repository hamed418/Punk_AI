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
import {
  Select,
  MultiSelect,
  TextInput,
  NumberInput,
  Textarea,
  Combobox,
  useCombobox,
  SegmentedControl,
  Accordion,
  Checkbox,
  Modal,
  Loader,
  Tooltip,
  Box,
  Text,
} from '@mantine/core';
import { DateTimePicker } from '@mantine/dates';
import dayjs from 'dayjs';
import {
  Plus,
  Trash2,
  Lock,
  Upload,
  Sparkles,
  Image as ImageIcon,
  X,
  Rocket,
  Save,
  Search,
  Pencil,
} from 'lucide-react';

import { WidgetLayout } from '../../../widgets';
import WidgetHeaderV2 from '@/components/WidgetHeaderV2';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';
import SecondaryBtn from '@/components/secondaryBtn';
import { uploadMediaAction } from '@/actions/chat.actions';
import {
  listCampaignTreeAction,
  listPageObjectsAction,
  searchTargetingAction,
  suggestTargetingAction,
} from '@/actions/ads.actions';
import type {
  CampaignEditorSpec,
  CampaignTreeAdSet,
  EditorAd,
  EditorAdSet,
  EditorCarouselCard,
  EditorCatalog,
  EditorPage,
  PageObject,
  EditorDestination,
  EditorOption,
  BudgetScheduleSpec,
  FrequencyControlSpec,
  PendingActionBlock,
  TargetingSuggestion,
} from '@/types/chat';
import { InfoLabel, makeOptionRenderer } from '../../../forms/InfoLabel';
import LeadFormOverlay from '../../LeadFormOverlay';
import GenerateAdOverlay from '../../../creative/GenerateAdOverlay';
import {
  AttributionField,
  type AttributionWindow,
  type DayPart,
  DaypartingField,
} from '../../../forms/scheduleFields';

interface Props {
  content: PendingActionBlock['content'];
  onConfirm: (value: string) => void;
  showLogo?: boolean;
  isLatest?: boolean;
}

const centsToDollars = (c?: number | null) =>
  c == null ? undefined : Math.round(c) / 100;
const dollarsToCents = (d?: number | string | null) =>
  d == null || d === '' ? null : Math.round(Number(d) * 100);

// Mantine v9 DateTimePicker is controlled by a local wall-clock STRING
// ("YYYY-MM-DD HH:mm:ss"), not a Date. Store as an ISO-8601 string with offset
// (dayjs().format()) so the picked instant reaches Meta correctly. Mirrors the
// datetime handling in DynamicForm.tsx.
const toLocalString = (stored?: string | null) =>
  stored ? dayjs(String(stored)).format('YYYY-MM-DD HH:mm:ss') : null;
const fromPicker = (v: string | null) => (v ? dayjs(v).format() : null);

// Meta needs a window to spread a lifetime budget over, and CampaignSpec rejects
// the plan without one — at the ad set AND under a campaign lifetime budget. So
// switching to Lifetime fills an end date instead of leaving the user to find out
// from a validation error on a field that was labelled optional. 30 days mirrors
// parsing.resolve_flight's default_flight_days, so a plan flipped to Lifetime
// lands on the same flight the builder would have picked.
const DEFAULT_FLIGHT_DAYS = 30;
const defaultEnd = (start?: string | null) =>
  dayjs(start || undefined)
    .add(DEFAULT_FLIGHT_DAYS, 'day')
    .format();

const selectClassNames = {
  input:
    'bg-transparent! border-primary-text/10! shadow-[0px_-1px_0px_0px_#00000026_inset,0px_1px_0px_0px_#FFFFFF0F_inset]! text-primary-text! rounded-[32px]! pb-1! text-[13px]!',
  dropdown:
    'bg-[#1C1C1C]/90! light:bg-white/90! backdrop-blur-xl! border border-stroke-widget! shadow-widget! rounded-2xl!',
  option:
    'text-primary-text/80! data-[selected]:text-primary-text! text-[13px]! rounded-lg!',
  label: 'font-medium! text-xs! text-primary-text! mb-2!',
  pill: 'bg-primary-bg! border border-stroke-widget! rounded-full! py-0! h-6.5! flex items-center! gap-1! shadow-[0px_1.5px_3px_#00000040]!',
  pillLabel:
    'text-primary-text! text-[11px]! font-semibold! tracking-wide! leading-none!',
  pillRemoveButton:
    'text-secondary-text! hover:text-red-400! hover:bg-transparent! transition-colors! size-4! p-0! flex items-center justify-center!',
  control: 'border-b! last:border-b-0! border-primary-text/10!',
};

const multiSelectClassNames = {
  ...selectClassNames,
  input:
    'bg-transparent! border-primary-text/10! shadow-[0px_-1px_0px_0px_#00000026_inset,0px_1px_0px_0px_#FFFFFF0F_inset]! text-primary-text! rounded-[20px]! py-1.5! pl-1.5! pr-8! text-[13px]! min-h-10! h-auto!',
};

const segmentedControlClassNames = {
  root: 'bg-secondary-bg/40! border border-stroke-widget! rounded-full! p-0.75!',
  indicator:
    'bg-white/10! light:bg-white! rounded-full! border border-white/14! shadow-[0px_2px_6px_0px_#00000033,0px_1px_0px_0px_#FFFFFF2E_inset]! light:border-black/5! py-2!',
  control: 'border-0!',
  label:
    'text-secondary-text! data-[active]:text-primary-text! data-[active]:font-semibold! text-[12px]! py-1!',
};

const tooltipStyles = {
  tooltip: {
    backgroundColor: 'var(--mantine-color-widget-inner-glass-bg)',
    backdropFilter: 'blur(16px)',
    WebkitBackdropFilter: 'blur(16px)',
    border: '1px solid var(--mantine-color-plus-minus-button-border)',
    borderRadius: '8px',
    padding: '6px 8px',
    lineHeight: 0.9,
    color: 'var(--color-secondary-text)',
  },
};

function toSelectData(opts?: EditorOption[]) {
  return (opts || []).map((o) => ({ value: o.value, label: o.label }));
}

// value → help map for a dropdown, so makeOptionRenderer can show each option's
// meaning under its label. EditorDestination also carries `help`.
function descsOf(opts?: { value: string; help?: string }[]) {
  return Object.fromEntries((opts || []).map((o) => [o.value, o.help]));
}

// Static explanations for the fixed structural fields Meta doesn't send copy
// for. Option-level meaning (objectives, goals, destinations) comes from the
// catalog's own `help`; this map is for the field label tooltips.
const FIELD_HELP: Record<string, string> = {
  objective:
    'What the campaign is for. It decides which conversion locations and optimization goals are available below.',
  conversion_location:
    'Where people go after clicking your ad — your website, an instant form, WhatsApp, a call, etc.',
  optimization_goal:
    'What Meta optimizes delivery toward (link clicks, conversions, reach…). The choices depend on your conversion location.',
  billing_event: 'What you are charged for — impressions shown or link clicks.',
  bid_strategy:
    'How Meta bids in the auction. Lowest cost chases the most results; cost/bid caps trade some volume for a price ceiling.',
  budget_mode:
    'Campaign (CBO) lets Meta shift budget to the best-performing ad sets automatically. Per ad set gives each ad set its own fixed budget.',
  budget_type:
    'Daily spends a set amount each day. Lifetime spends a total across the whole run and needs an end date.',
  special_ad_categories:
    'Required by Meta for ads about credit, employment, housing, or social/political issues — they restrict targeting options.',
  attribution:
    'Which conversions count toward this ad: how many days after a click (1 or 7) or a view (off or 1) an action is credited. Meta’s default is 7-day click, 1-day view. Only affects conversion ad sets.',
  frequency:
    'Caps how often one person sees your ad within a time window. Only available on the Reach optimization goal.',
};

// Standard Meta pixel conversion events offered when an optimization goal needs
// a pixel promoted_object. Comes from the catalog (meta_spec/catalog.py) like
// every other Meta vocabulary — this was the one list that had leaked into React.
// The fallback only covers a catalog payload predating that move.
const pixelEventsOf = (catalog: EditorCatalog): string[] =>
  catalog.pixel_events ?? ['PURCHASE', 'LEAD', 'COMPLETE_REGISTRATION'];

// What to do about a prerequisite the run never collected. These used to read
// "publishing will fail", which is only half true and left the user with nowhere
// to act: every one of them IS editable in this form, so the warning names the
// field that fixes it. The keys come from the matrix
// (EditorDestination.required_user_info) and each string must point at a control
// this panel actually renders — see the Website URL / App store URL fields below.
const PREREQUISITE_FIXES: Record<string, string> = {
  website_url:
    'Clicks currently go to your Facebook Page — we never got a website. Put your site in Website URL above if you want them to land there instead.',
  app_store_url:
    'We need your store link — fill in App store URL above, one ad set per store.',
};

// Meta takes ONE store URL per ad set (promoted_object.object_store_url) and one
// targeting.user_os, so covering both stores means two ad sets. Fallback covers
// a catalog payload predating the key.
const appPlatformsOf = (catalog: EditorCatalog): EditorOption[] =>
  catalog.app_platforms ?? [
    { value: 'iOS', label: 'iOS' },
    { value: 'Android', label: 'Android' },
  ];

// Server-side default for a frequency cap, so the pair is never blank on a goal
// that allows one. Mirrors meta_spec/enums.FREQUENCY_DEFAULT_*.
const frequencyCapOf = (catalog: EditorCatalog) =>
  catalog.frequency_cap ?? {
    event: 'IMPRESSIONS',
    interval_days: 7,
    max_frequency: 1,
    max_interval_days: 90,
  };

// Country names for the special-ad-category declaration. The codes come from the
// catalog like every other vocabulary; only the display name is resolved here,
// because a country name is a locale concern and the platform already knows them.
const countryNames = new Intl.DisplayNames(['en'], { type: 'region' });

// The ROAS goal's target lives in bid_constraints, scaled by `scale` (10000 == 1.0x),
// and Meta rejects a bid_amount alongside it. Defaults mirror the server so an
// older catalog payload still renders.
const roasGoalOf = (catalog: EditorCatalog) =>
  catalog.roas_goal ?? {
    bid_strategy: 'LOWEST_COST_WITH_MIN_ROAS',
    scale: 10000,
    min: 100,
    max: 10000000,
  };

export default function CampaignEditorV1({
  content,
  onConfirm,
  showLogo = false,
  isLatest = true,
}: Props) {
  const params = useParams();
  const threadId = params.threadId as string;

  const catalog = content.catalog as EditorCatalog | undefined;
  const errors = content.errors ?? {};
  const locks = content.locks ?? { geo: true, audience: true };

  const [spec, setSpec] = useState<CampaignEditorSpec | null>(
    content.spec ? structuredClone(content.spec) : null
  );
  // The editor opens in a Modal. A new pending action = a new component mount
  // (keyed by block id in ActiveWidgetRenderer), so `true` here means it opens
  // automatically on first appearance and again after every Save / rejected
  // Publish re-emit. Closing drops back to the summary card.
  const [opened, setOpened] = useState(true);
  // Which accordion section is expanded (single-open). "campaign" | "adset-N".
  const [openSection, setOpenSection] = useState<string | null>('campaign');
  // Which ad triggered the Punk-ideas overlay: { a: adsetIdx, d: adIdx } | null
  const [generating, setGenerating] = useState<{ a: number; d: number } | null>(
    null
  );
  // Which ad set is building an Instant Form, or null. Forms are per ad set —
  // every ad in one submits to the same place.
  const [buildingForm, setBuildingForm] = useState<number | null>(null);
  // Forms created from the overlay during this session. The catalog's candidate
  // list is a server snapshot taken when the plan was rendered, so a form the
  // user just made would otherwise vanish from the picker.
  const [newForms, setNewForms] = useState<{ id: string; name?: string }[]>([]);

  // ── "start from a previous campaign" copy picker ──────────────────────────
  // Which campaign is selected, its ad sets/ads once read from Meta, and what is
  // ticked. Nothing is applied until the button — picking a campaign only loads
  // the list to choose from.
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [templateTree, setTemplateTree] = useState<CampaignTreeAdSet[]>([]);
  const [templateLoading, setTemplateLoading] = useState(false);
  const [pickedAdsets, setPickedAdsets] = useState<Set<string>>(new Set());
  const [pickedAds, setPickedAds] = useState<Set<string>>(new Set());

  // Clearing happens here rather than in the effect: an effect that setStates in
  // its own body cascades renders (react-hooks/set-state-in-effect), and picking
  // a campaign is a user event that already knows everything it has to reset.
  const pickTemplate = (id: string | null) => {
    setTemplateId(id);
    setTemplateTree([]);
    setPickedAdsets(new Set());
    setPickedAds(new Set());
    setTemplateLoading(!!id);
  };

  useEffect(() => {
    if (!templateId) return;
    // `live` guards a fast re-pick: the first request must not overwrite the
    // second's result. Same pattern as PagePostPicker below.
    let live = true;
    listCampaignTreeAction(templateId)
      .then((adsets) => {
        if (!live) return;
        setTemplateTree(adsets);
        // Everything ticked by default, so "pick a campaign, press Apply" stays
        // the one-decision path it was before the picker existed.
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

  if (!spec || !catalog) return null;

  // The catalog is server data, and a checkpointed thread can hold a block
  // emitted by an older backend — its catalog keyed option lists off the
  // objective alone, before conversion location became the second axis. Reading
  // through a missing key used to throw and take the whole chat page down with
  // it, so the shape is checked once here and the widget degrades to a message
  // the user can act on.
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
  // Changing either axis invalidates everything below it. Without this the old
  // goal / billing event / CTA survived the switch and the user got a wall of
  // server validation errors on submit instead of a form that just updated.
  // A current value is kept only when the new destination still allows it.
  const keepOrFirst = (
    current: string | null | undefined,
    opts: EditorOption[]
  ) =>
    opts.some((o) => o.value === current)
      ? (current as string)
      : opts[0]?.value;

  const applyDestination = (as: EditorAdSet, dest: EditorDestination) => {
    as.destination_type = dest.value;
    as.optimization_goal = keepOrFirst(
      as.optimization_goal,
      dest.optimization_goals
    );
    applyGoal(as, dest);
  };

  // The goal is the third rule layer: it narrows billing events, bid strategies
  // and ad formats beyond what the conversion location allows, and can require a
  // video. Run on every goal change so the form stops offering pairs the server
  // rejects — that mismatch is what produced the invalid combinations.
  const applyGoal = (as: EditorAdSet, dest: EditorDestination) => {
    const goal = catalog.goal_rules?.[as.optimization_goal];

    const billing = goal
      ? dest.billing_events.filter((e) => goal.billing_events.includes(e.value))
      : dest.billing_events;
    as.billing_event =
      keepOrFirst(as.billing_event, billing) ?? as.billing_event;

    if (goal && !goal.bid_strategies.includes(as.bid_strategy)) {
      as.bid_strategy = goal.bid_strategies[0];
    }
    // Only the strategies that take one keep their companion amount.
    if (!catalog.bid_strategies_requiring_amount.includes(as.bid_strategy)) {
      as.bid_amount = null;
    }
    if (as.bid_strategy !== roasGoalOf(catalog).bid_strategy) {
      as.bid_constraints = null;
    }

    // Fields Meta only accepts for certain goals. A goal that allows a cap gets
    // the server's default seeded rather than an empty pair of boxes — the same
    // values build_campaign_spec starts from, so switching to Reach in the form
    // and starting on Reach look identical.
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

    // promoted_object shape is decided by (destination, goal). Drop one that no
    // longer applies rather than shipping a pixel id to a Page-promoted ad set.
    const kind =
      dest.promoted_object_kind_by_goal[as.optimization_goal] ?? 'none';
    if (kind === 'none') as.promoted_object = null;
    // A Page-promoting goal (Page likes, Click-to-WhatsApp) needs the Page here
    // and nothing else — switching into one from a pixel goal used to leave the
    // old pixel behind, which the server rejects.
    if (kind === 'page') {
      as.promoted_object = { page_id: spec.page_id ?? catalog.page_id ?? null };
    }

    // A form the user designed is meaningless once the ads no longer submit to
    // one, and the server strips it in the same place (meta_spec/builder).
    if (!dest.requires_lead_form) as.lead_form_draft = null;

    const formats = goal?.ad_formats
      ? dest.ad_formats.filter((f) => goal.ad_formats!.includes(f.value))
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
      if (dest) applyGoal(as, dest);
    });

  const changeObjective = (next: string) =>
    update((d) => {
      d.objective = next;
      const nextDests = catalog.destinations_by_objective[next] || [];
      const nextBids = catalog.bid_strategies_by_objective[next] || [];
      if (d.bid_strategy)
        d.bid_strategy = keepOrFirst(d.bid_strategy, nextBids);
      d.adsets.forEach((as) => {
        // Keep the same conversion location when the new objective offers it —
        // Sales → Leads on a website should not silently jump to instant forms.
        const dest =
          nextDests.find((x) => x.value === as.destination_type) ??
          nextDests[0];
        if (!dest) return;
        as.bid_strategy = keepOrFirst(as.bid_strategy, nextBids);
        applyDestination(as, dest);
      });
    });

  const changeDestination = (i: number, next: string) =>
    update((d) => {
      const dest = destinations.find((x) => x.value === next);
      if (dest) applyDestination(d.adsets[i], dest);
    });

  // ── publishing identity ───────────────────────────────────────────────────
  // The plan carries the Page it publishes as; the catalog's page_id is only the
  // default the server started from.
  const pageId = spec.page_id ?? catalog.page_id ?? null;
  const pages = catalog.page_candidates ?? [];
  const currentPage = pages.find((pg) => pg.id === pageId);

  // Everything Page-scoped has to follow the Page. An instant form or a boosted
  // post belongs to one Page and Meta rejects it against another, so they are
  // cleared rather than carried across — the pickers below re-offer the new
  // Page's own.
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

  // Clearing the categories must clear the country as well: the server rejects a
  // country with no category, and the input that held it is now hidden.
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
    setOpenSection(`adset-${spec.adsets.length}`);
  };
  const removeAdSet = (i: number) => {
    if (spec.adsets.length <= 1) return;
    update((d) => d.adsets.splice(i, 1));
    setOpenSection('adset-0');
  };
  const addAd = (a: number) =>
    update((d) => {
      const ads = d.adsets[a].ads;
      const src = ads[ads.length - 1];
      const clone: EditorAd = {
        name: `${d.adsets[a].name} Ad ${ads.length + 1}`,
        creative: {
          ...src.creative,
          media_id: null,
          image_hash: null,
          video_id: null,
          media_url: null,
        },
      };
      ads.push(clone);
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
        // Ad-set budget sharing is an ABO-only setting and the server rejects the
        // spec if it survives the switch to CBO.
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
  // Under CBO the campaign owns the strategy, but Meta still carries the target
  // on each ad set. So the ad sets mirror the campaign strategy and every one
  // gets the same target — otherwise the server rejects the spec for a field the
  // form never showed, which is exactly what it used to do.
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
        as.bid_amount = capped
          ? as.bid_amount || catalog.min_budget_cents
          : null;
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
  const submit = (action: 'save' | 'publish') => {
    if (!isLatest) return;
    // Strip client-only preview fields before sending.
    const out = structuredClone(spec);
    out.adsets.forEach((as) =>
      as.ads.forEach((ad) => {
        delete (ad.creative as { media_url?: unknown }).media_url;
      })
    );
    onConfirm(JSON.stringify({ action, spec: out }));
  };

  // "Start from a previous campaign" is the one control that cannot resolve
  // locally: the old campaign's setup lives at Meta, so the server reads it and
  // sends the overlaid plan back. The current tree rides along so edits already
  // made survive underneath the template.
  const applyTemplate = () => {
    if (!isLatest || !templateId) return;
    const out = structuredClone(spec);
    out.adsets.forEach((as) =>
      as.ads.forEach((ad) => {
        delete (ad.creative as { media_url?: unknown }).media_url;
      })
    );
    const payload: Record<string, unknown> = {
      action: 'apply_template',
      campaign_id: templateId,
      spec: out,
    };
    // Send the ticked ids only when there is a tree to have ticked. Omitting the
    // keys is how the server hears "the whole campaign", which is the right
    // answer when its structure could not be read. An empty ARRAY is a different
    // answer — "nothing at that level" — so the two must not be conflated.
    if (templateTree.length) {
      payload.adset_ids = [...pickedAdsets];
      payload.ad_ids = [...pickedAds];
    }
    onConfirm(JSON.stringify(payload));
  };

  // Ticking an ad set takes its ads with it; unticking the last ad under a
  // ticked ad set is meaningful on its own — that copies the ad set's settings
  // and keeps this run's generated copy.
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

  const rootError = err('__root__');
  const objectiveLabel =
    catalog.objectives.find((o) => o.value === spec.objective)?.label ??
    spec.objective;
  const adCount = spec.adsets.reduce((s, as) => s + as.ads.length, 0);
  const totalCents =
    budgetMode === 'cbo'
      ? spec.daily_budget || spec.lifetime_budget || 0
      : spec.adsets.reduce(
          (s, as) => s + (as.daily_budget || as.lifetime_budget || 0),
          0
        );
  const totalDollars = centsToDollars(totalCents);

  const errorBanner = rootError && (
    <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-2.5 text-[13px] text-red-400">
      {rootError}
    </div>
  );

  // A declared special ad category strips ZIP targeting, the lookalike and
  // detailed targeting. Say so — the alternative is the user discovering their
  // audience is not what they asked for after the campaign runs.
  const complianceBanner = !!spec.compliance_notes?.length && (
    <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-[13px] text-amber-300">
      <div className="font-medium">
        Special ad category restrictions applied
      </div>
      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-amber-300/80">
        {spec.compliance_notes!.map((note, i) => (
          <li key={i}>{note}</li>
        ))}
      </ul>
    </div>
  );

  return (
    <>
      {/* ── Chat summary card — short, opens the editor modal ──────────────── */}
      <WidgetLayout mode="full" showLogo={showLogo}>
        <div className="border-stroke-widget bg-primary-widget shadow-widget mb-4 flex flex-col gap-4 rounded-3xl border p-6">
          <WidgetHeaderV2
            icon={<Rocket size={15} className="text-primary-text" />}
            title={content.title ?? 'Campaign editor'}
            subtitle={content.subtitle ?? content.prompt}
          />
          {errorBanner}
          {complianceBanner}
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
            <Stat label="Campaign" value={spec.name} />
            <Stat label="Objective" value={objectiveLabel} />
            <Stat
              label="Ad sets / ads"
              value={`${spec.adsets.length} / ${adCount}`}
            />
            <Stat
              label="Budget"
              value={
                totalDollars != null
                  ? `$${totalDollars}${budgetMode === 'cbo' ? '/day · CBO' : ''}`
                  : '—'
              }
            />
          </div>
          <div className="flex justify-end">
            <PrimaryGlassBtn
              radius="xl"
              size="sm"
              leftSection={<Pencil size={14} />}
              onClick={() => setOpened(true)}
            >
              Review &amp; edit
            </PrimaryGlassBtn>
          </div>
        </div>
      </WidgetLayout>

      {/* ── Editor modal — owns its own scroll ────────────────────────────── */}
      <Modal
        opened={opened}
        onClose={() => setOpened(false)}
        centered
        size="920px"
        radius="lg"
        padding={0}
        withCloseButton={false}
        zIndex={100000}
        overlayProps={{ backgroundOpacity: 0.6, blur: 3 }}
        classNames={{
          content:
            'bg-white/4! border border-stroke-widget! text-primary-text! overflow-hidden! shadow-widget!',
          body: 'p-0!',
        }}
        styles={{
          content: {
            backdropFilter: 'blur(40px)',
            WebkitBackdropFilter: 'blur(40px)',
          },
        }}
      >
        <div className="relative flex max-h-[85vh] flex-col">
          {/* header */}
          <div className="border-underline/15 flex shrink-0 items-center justify-between border-b px-5 py-4">
            <div className="flex items-center gap-2">
              <Rocket size={15} className="text-primary-text" />
              <span className="text-primary-text text-[15px] font-semibold">
                Campaign editor
              </span>
            </div>
            <button
              onClick={() => setOpened(false)}
              className="text-secondary-text flex h-7 w-7 items-center justify-center rounded-full hover:bg-white/10"
            >
              <X size={16} />
            </button>
          </div>

          {/* scrollable body */}
          <div className="custom-scrollbar flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 py-4">
            {errorBanner}
            {complianceBanner}
            <Accordion
              value={openSection}
              onChange={setOpenSection}
              variant="separated"
              classNames={accordionClassNames}
            >
              {/* Campaign */}
              <Accordion.Item value="campaign">
                <Accordion.Control className="text-primary-text! text-sm! font-bold!">
                  Campaign
                </Accordion.Control>

                <Accordion.Panel>
                  <Box
                    pb={15}
                    className="border-primary-text/6! mx-1! border-t!"
                  />
                  {/* Three states, not two. `undefined` is a catalog from before
                      this existed — say nothing, because nothing was looked up.
                      An empty ARRAY means we asked Meta and the account has no
                      campaigns, which is worth saying: rendering absence made the
                      feature look broken on a new account, and made "none here"
                      indistinguishable from "the lookup failed". */}
                  {catalog.previous_campaigns && (
                    <div className="mx-2 mb-4">
                      <Select
                        label="Start from a previous campaign"
                        description="Reuses its objective, optimization goal, bidding and ad copy. Your geo and audience stay as they are."
                        data={catalog.previous_campaigns.map((c) => ({
                          value: c.id,
                          label: c.created_time
                            ? `${c.name} — ${c.created_time.slice(0, 10)}`
                            : c.name,
                        }))}
                        value={templateId}
                        clearable
                        disabled={!catalog.previous_campaigns.length}
                        placeholder={
                          catalog.previous_campaigns.length
                            ? 'Set up fresh'
                            : 'No previous campaigns on this ad account'
                        }
                        onChange={pickTemplate}
                        classNames={{
                          ...selectClassNames,
                          label: 'font-medium! text-xs! text-primary-text!',
                          description:
                            'text-primary-text/70! opacity-80! text-[11px]! mb-2!',
                        }}
                        comboboxProps={{ withinPortal: true, zIndex: 1000001 }}
                      />

                      {/* What to copy. Nothing has been applied yet — picking a
                          campaign only reads its structure, so unticking here is
                          free and the plan on screen is untouched until Apply. */}
                      {templateId && (
                        <div className="border-underline/15 mt-3 rounded-xl border p-3">
                          {templateLoading ? (
                            <div className="text-secondary-text flex items-center gap-2 text-[12px]">
                              <Loader size={13} /> Reading that campaign…
                            </div>
                          ) : templateTree.length === 0 ? (
                            <div className="text-secondary-text text-[12px]">
                              Couldn&apos;t read this campaign&apos;s ad sets —
                              Apply will copy the whole campaign.
                            </div>
                          ) : (
                            <>
                              <div className="text-secondary-text mb-2 text-[12px]">
                                What to copy from it
                              </div>
                              <div className="flex flex-col gap-2">
                                {templateTree.map((as) => (
                                  <div key={as.id}>
                                    <Checkbox
                                      size="xs"
                                      label={as.name}
                                      checked={pickedAdsets.has(as.id)}
                                      onChange={(e) =>
                                        toggleTemplateAdset(
                                          as,
                                          e.currentTarget.checked
                                        )
                                      }
                                      classNames={{
                                        label:
                                          'text-primary-text! text-[13px]! cursor-pointer',
                                      }}
                                    />
                                    {as.ads.length > 0 && (
                                      <div className="mt-1.5 ml-6 flex flex-col gap-1.5">
                                        {as.ads.map((ad) => (
                                          <Checkbox
                                            key={ad.id}
                                            size="xs"
                                            label={ad.name}
                                            checked={pickedAds.has(ad.id)}
                                            disabled={!pickedAdsets.has(as.id)}
                                            onChange={(e) =>
                                              toggleTemplateAd(
                                                ad.id,
                                                e.currentTarget.checked
                                              )
                                            }
                                            classNames={{
                                              label:
                                                'text-secondary-text! text-[12px]! cursor-pointer',
                                            }}
                                          />
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                ))}
                              </div>
                              <div className="text-secondary-text/70 mt-2 text-[11px]">
                                Untick every ad under an ad set to copy its
                                settings and keep your own copy.
                              </div>
                            </>
                          )}

                          <div className="mt-3 flex justify-end">
                            <SecondaryBtn
                              radius="xl"
                              size="xs"
                              disabled={
                                templateLoading ||
                                (templateTree.length > 0 &&
                                  pickedAdsets.size === 0)
                              }
                              onClick={applyTemplate}
                            >
                              Apply selection
                            </SecondaryBtn>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                  {/* Which Page the ads run as. Always shown, never hidden: the
                      Meta connection stores a single Page, and with several
                      brands on the account it is whichever one Meta happened to
                      list first — so the user has to SEE who they publish as
                      even when there is nothing to switch to. One Page → the
                      field is read-only rather than absent. */}
                  {pages.length > 0 && (
                    <div className="mx-2 mb-4">
                      <Select
                        label={
                          <InfoLabel
                            label="Facebook Page"
                            help="Who the ads are published as. Instagram placements run as this Page's linked Instagram account."
                            className="text-primary-text! text-xs! font-medium!"
                          />
                        }
                        description={
                          pages.length === 1
                            ? 'The only Page this Meta connection can see.'
                            : undefined
                        }
                        disabled={pages.length === 1}
                        data={pages.map((pg) => ({
                          value: pg.id,
                          label: pg.name || pg.id,
                        }))}
                        renderOption={makeOptionRenderer(
                          Object.fromEntries(
                            pages.map((pg) => [
                              pg.id,
                              pg.instagram?.username
                                ? `Instagram: @${pg.instagram.username}`
                                : 'No linked Instagram account',
                            ])
                          )
                        )}
                        value={pageId ?? null}
                        onChange={(v) => v && changePage(v)}
                        error={err('page_id')}
                        classNames={{
                          ...selectClassNames,
                          label: 'font-medium! text-xs! text-primary-text!',
                          description:
                            'text-primary-text/70! opacity-80! text-[11px]! mb-2!',
                        }}
                        comboboxProps={{ withinPortal: true, zIndex: 1000001 }}
                      />
                    </div>
                  )}
                  <div className="mx-2! grid grid-cols-1 items-center! gap-4 md:grid-cols-2">
                    <TextInput
                      label="Campaign name"
                      value={spec.name}
                      onChange={(e) =>
                        update((d) => (d.name = e.currentTarget.value))
                      }
                      error={err('name')}
                      classNames={selectClassNames}
                    />
                    <Select
                      label={
                        <InfoLabel
                          label="Objective"
                          help={FIELD_HELP.objective}
                        />
                      }
                      data={toSelectData(catalog.objectives)}
                      renderOption={makeOptionRenderer(
                        descsOf(catalog.objectives)
                      )}
                      value={spec.objective}
                      onChange={(v) => v && changeObjective(v)}
                      error={err('objective')}
                      classNames={selectClassNames}
                      comboboxProps={{ withinPortal: true, zIndex: 1000001 }}
                    />
                    <MultiSelect
                      label={
                        <InfoLabel
                          label="Special ad categories"
                          help={FIELD_HELP.special_ad_categories}
                        />
                      }
                      data={toSelectData(catalog.special_ad_categories)}
                      value={spec.special_ad_categories}
                      onChange={(v) => setSpecialAdCategories(v)}
                      error={err('special_ad_categories')}
                      classNames={multiSelectClassNames}
                      comboboxProps={{ withinPortal: true, zIndex: 1000001 }}
                      clearable
                    />
                    {/* Meta requires the country whose rules the declaration is
                        made under, and rejects the campaign without it. */}
                    {spec.special_ad_categories.length > 0 && (
                      <MultiSelect
                        label={
                          <InfoLabel
                            label="Category country"
                            help="The country whose special ad category rules apply — normally where your audience is."
                          />
                        }
                        data={(
                          catalog.special_ad_category_countries ?? ['US', 'CA']
                        ).map((code) => ({
                          value: code,
                          label: countryNames.of(code) ?? code,
                        }))}
                        value={spec.special_ad_category_country ?? []}
                        onChange={(v) =>
                          update((d) => (d.special_ad_category_country = v))
                        }
                        error={err('special_ad_category_country')}
                        classNames={multiSelectClassNames}
                        comboboxProps={{ withinPortal: true, zIndex: 1000001 }}
                        searchable
                      />
                    )}
                    <div>
                      <div className="text-secondary-text mb-2 text-[12px]">
                        <InfoLabel
                          label="Budget optimization"
                          help={FIELD_HELP.budget_mode}
                        />
                      </div>
                      <SegmentedControl
                        fullWidth
                        size="xs"
                        value={budgetMode}
                        onChange={(v) => switchBudgetMode(v as 'cbo' | 'adset')}
                        data={[
                          { label: 'Campaign (CBO)', value: 'cbo' },
                          { label: 'Per ad set', value: 'adset' },
                        ]}
                        classNames={segmentedControlClassNames}
                      />
                    </div>
                    {budgetMode === 'cbo' && (
                      <>
                        <div>
                          <div className="text-secondary-text mb-1 text-[12px]">
                            <InfoLabel
                              label="Campaign budget type"
                              help={FIELD_HELP.budget_type}
                            />
                          </div>
                          <SegmentedControl
                            fullWidth
                            size="xs"
                            value={spec.lifetime_budget ? 'lifetime' : 'daily'}
                            onChange={(v) =>
                              update((d) => {
                                if (v === 'lifetime') {
                                  d.lifetime_budget =
                                    d.daily_budget || catalog.min_budget_cents;
                                  d.daily_budget = null;
                                  // A campaign lifetime budget needs an end time on
                                  // every ad set, not just one.
                                  d.adsets.forEach((as) => {
                                    if (!as.end_time)
                                      as.end_time = defaultEnd(as.start_time);
                                  });
                                } else {
                                  d.daily_budget =
                                    d.lifetime_budget ||
                                    catalog.min_budget_cents;
                                  d.lifetime_budget = null;
                                }
                              })
                            }
                            data={[
                              { label: 'Daily', value: 'daily' },
                              { label: 'Lifetime', value: 'lifetime' },
                            ]}
                            classNames={segmentedControlClassNames}
                          />
                        </div>
                        <NumberInput
                          label={
                            spec.lifetime_budget
                              ? 'Campaign lifetime budget ($)'
                              : 'Campaign daily budget ($)'
                          }
                          value={centsToDollars(
                            spec.lifetime_budget ?? spec.daily_budget
                          )}
                          min={minDollars}
                          decimalScale={2}
                          onChange={(v) =>
                            update((d) => {
                              const c = dollarsToCents(v);
                              if (d.lifetime_budget != null)
                                d.lifetime_budget = c;
                              else d.daily_budget = c;
                            })
                          }
                          error={err('daily_budget') || err('lifetime_budget')}
                          classNames={selectClassNames}
                        />
                        <Select
                          label={
                            <InfoLabel
                              label="Bid strategy"
                              help={FIELD_HELP.bid_strategy}
                            />
                          }
                          data={toSelectData(bidStrategies)}
                          renderOption={makeOptionRenderer(
                            descsOf(bidStrategies)
                          )}
                          value={spec.bid_strategy ?? null}
                          onChange={(v) => v && setCampaignBidStrategy(v)}
                          error={err('bid_strategy')}
                          classNames={selectClassNames}
                          comboboxProps={{
                            withinPortal: true,
                            zIndex: 1000001,
                          }}
                        />
                        {/* The target that goes with a capped strategy. Meta asks
                            for it once under CBO, so one input writes it to every
                            ad set — where the payload actually carries it. */}
                        {cboNeedsBidAmount && (
                          <NumberInput
                            label="Cost per result goal ($)"
                            description="The average you're willing to pay per result."
                            value={centsToDollars(spec.adsets[0]?.bid_amount)}
                            min={0.01}
                            decimalScale={2}
                            onChange={(v) =>
                              setEveryAdsetBidAmount(dollarsToCents(v))
                            }
                            error={err('adsets[0].bid_amount')}
                            classNames={selectClassNames}
                          />
                        )}
                        {cboNeedsRoasFloor && (
                          <NumberInput
                            label="Minimum ROAS"
                            description="2 means $2 back for every $1 spent."
                            value={roasFloorToX(
                              spec.adsets[0]?.bid_constraints
                            )}
                            min={roasGoal.min / roasGoal.scale}
                            max={roasGoal.max / roasGoal.scale}
                            decimalScale={2}
                            onChange={(v) => setEveryAdsetRoasFloor(v)}
                            error={err(
                              'adsets[0].bid_constraints.roas_average_floor'
                            )}
                            classNames={selectClassNames}
                          />
                        )}
                        {spec.lifetime_budget != null && (
                          <div className="text-secondary-text/60 text-[11px] md:col-span-2">
                            Lifetime budget needs an end date on every ad set
                            (set it under Schedule).
                          </div>
                        )}
                      </>
                    )}
                    {/* ABO only. Meta has no default for this and rejects the
                        campaign outright without an explicit True/False. */}
                    {budgetMode === 'adset' && (
                      <Checkbox
                        className="md:col-span-2"
                        size="xs"
                        label={
                          <InfoLabel
                            label="Let ad sets share budget"
                            help="Ad sets can lend each other up to 20% of their budget when one is performing better. Off keeps every ad set on exactly the budget you set."
                          />
                        }
                        checked={!!spec.is_adset_budget_sharing_enabled}
                        onChange={(e) =>
                          update(
                            (d) =>
                              (d.is_adset_budget_sharing_enabled =
                                e.currentTarget.checked)
                          )
                        }
                        error={err('is_adset_budget_sharing_enabled')}
                        classNames={{
                          label:
                            'text-primary-text! text-[13px]! cursor-pointer',
                        }}
                      />
                    )}
                  </div>
                </Accordion.Panel>
              </Accordion.Item>

              {/* Ad sets */}
              {spec.adsets.map((as, i) => (
                <Accordion.Item key={i} value={`adset-${i}`}>
                  <Accordion.Control className="text-primary-text! text-sm! font-bold!">
                    <div className="flex items-center gap-2">
                      <span className="text-primary-text! text-sm! font-bold!">
                        {as.name || `Ad set ${i + 1}`}
                      </span>
                      <span className="text-secondary-text/60 text-[11px] font-normal!">
                        {as.ads.length} ad{as.ads.length === 1 ? '' : 's'}
                      </span>
                    </div>
                  </Accordion.Control>
                  <Accordion.Panel>
                    <Box
                      pb={15}
                      className="border-primary-text/6! mx-1! border-t!"
                    />
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
                      onAddAd={() => addAd(i)}
                      onRemoveAd={(d) => removeAd(i, d)}
                      patchAd={(d, p) => patchAd(i, d, p)}
                      patchCreative={(d, p) => patchCreative(i, d, p)}
                      onGenerate={(d) => setGenerating({ a: i, d })}
                      extraLeadForms={newForms}
                      onBuildLeadForm={() => setBuildingForm(i)}
                      pageId={pageId}
                      page={currentPage}
                    />
                  </Accordion.Panel>
                </Accordion.Item>
              ))}
            </Accordion>

            <button
              onClick={addAdSet}
              className="border-underline/15 text-secondary-text/90 flex items-center justify-center gap-1.5 rounded-xl border border-dashed py-2.5 text-[12px] font-medium hover:bg-white/5"
            >
              <Plus size={14} /> Add ad set
            </button>
          </div>

          {/* sticky footer */}
          <div className="border-underline/15 flex shrink-0 items-center justify-end gap-3 border-t px-5 py-4">
            <SecondaryBtn
              radius="xl"
              size="sm"
              leftSection={<Save size={14} />}
              onClick={() => submit('save')}
            >
              Save changes
            </SecondaryBtn>
            <PrimaryGlassBtn
              radius="xl"
              size="sm"
              leftSection={<Rocket size={14} />}
              onClick={() => submit('publish')}
            >
              Publish
            </PrimaryGlassBtn>
          </div>

          {generating && (
            <GenerateAdOverlay
              type="image"
              threadId={threadId}
              onClose={() => setGenerating(null)}
              onAdd={(generated) => {
                const asset = generated[0];
                if (!asset) return;
                patchCreative(generating.a, generating.d, {
                  media_id: asset.id ?? null,
                  media_url: asset.url ?? null,
                  // Generated creatives are images today; the goal check reads
                  // this, so state it rather than leaving it unknown.
                  media_kind: 'image',
                  image_hash: null,
                  video_id: null,
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
                // The draft IS the instruction, so any previously picked form id
                // has to go — the server rejects a spec carrying both.
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
        </div>
      </Modal>
    </>
  );
}

// ── small stat for the summary card ──────────────────────────────────────────
function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 flex-col">
      <span className="text-secondary-text/60 text-[11px]">{label}</span>
      <span className="text-primary-text truncate text-[13px] font-medium">
        {value}
      </span>
    </div>
  );
}

const accordionClassNames = {
  item: 'border border-underline/15! rounded-[18px]! mb-2! bg-[#00000003]! backdrop-blur-[103.6px]! shadow-[0px_8px_24px_0px_#00000080,0px_-1px_0px_0px_#00000066_inset,0px_1px_0px_0px_#FFFFFF1F_inset]!',
  control: 'text-primary-text! hover:bg-white/5! rounded-2xl!',
  label: 'py-[15px]! px-1! font-bold!',
  content: 'px-3! pb-3!',
  chevron: 'text-secondary-text!',
};

// ── Ad set panel ─────────────────────────────────────────────────────────────
// Reach-only frequency cap: how often one person may see the ad in a window.
// Empty inputs = no cap (onChange([])). Writing either field seeds the other
// with a sensible default so the pair always forms a valid spec.
function FrequencyCapField({
  catalog,
  value,
  onChange,
  error,
}: {
  catalog: EditorCatalog;
  value: FrequencyControlSpec[];
  onChange: (v: FrequencyControlSpec[]) => void;
  error?: string;
}) {
  const defaults = frequencyCapOf(catalog);
  const cur = value[0];
  const set = (patch: Partial<FrequencyControlSpec>) => {
    const next = {
      event: defaults.event,
      interval_days: cur?.interval_days ?? defaults.interval_days,
      max_frequency: cur?.max_frequency ?? defaults.max_frequency,
      ...patch,
    };
    onChange([next]);
  };
  return (
    <div className="flex flex-col gap-2">
      <InfoLabel label="Frequency cap" help={FIELD_HELP.frequency} />
      <div className="flex items-end gap-3">
        <NumberInput
          label="Max times shown"
          value={cur?.max_frequency ?? ''}
          placeholder={String(defaults.max_frequency)}
          min={1}
          onChange={(v) =>
            v === '' ? onChange([]) : set({ max_frequency: Number(v) })
          }
          classNames={selectClassNames}
        />
        <NumberInput
          label="Per (days)"
          value={cur?.interval_days ?? ''}
          placeholder={String(defaults.interval_days)}
          min={1}
          max={defaults.max_interval_days}
          onChange={(v) =>
            v === '' ? onChange([]) : set({ interval_days: Number(v) })
          }
          classNames={selectClassNames}
        />
      </div>
      {error && <span className="text-[11px] text-red-400">{error}</span>}
    </div>
  );
}

function AdSetPanel({
  adset,
  index,
  catalog,
  errors,
  locks,
  minDollars,
  budgetMode,
  blocksDemographics,
  destinations,
  bidStrategies,
  canRemove,
  onRemove,
  onChangeDestination,
  onChangeGoal,
  campaignIsLifetime,
  patchAdset,
  patchTargeting,
  onAddAd,
  onRemoveAd,
  patchAd,
  patchCreative,
  onGenerate,
  extraLeadForms,
  onBuildLeadForm,
  pageId,
  page,
}: {
  adset: EditorAdSet;
  index: number;
  catalog: EditorCatalog;
  errors: Record<string, string>;
  locks: { geo?: boolean; audience?: boolean };
  minDollars: number;
  budgetMode: 'cbo' | 'adset';
  blocksDemographics: boolean;
  destinations: EditorDestination[];
  bidStrategies: EditorOption[];
  canRemove: boolean;
  onRemove: () => void;
  onChangeDestination: (v: string) => void;
  onChangeGoal: (v: string) => void;
  campaignIsLifetime: boolean;
  patchAdset: (p: Partial<EditorAdSet>) => void;
  patchTargeting: (p: Record<string, unknown>) => void;
  onAddAd: () => void;
  onRemoveAd: (d: number) => void;
  patchAd: (d: number, p: Partial<EditorAd>) => void;
  patchCreative: (d: number, p: Partial<EditorAd['creative']>) => void;
  onGenerate: (d: number) => void;
  // Forms created from the overlay since the plan was rendered — the catalog's
  // candidate list is a server snapshot and does not know about them.
  extraLeadForms: { id: string; name?: string }[];
  onBuildLeadForm: () => void;
  // The Page this plan publishes as — everything Page-scoped below (instant
  // forms, the boostable post picker) has to be read against it, not against
  // whichever Page the connection stored.
  pageId: string | null;
  page?: EditorPage;
}) {
  const p = `adsets[${index}]`;
  const err = (k: string) => errors[k];
  const t = adset.targeting || {};
  const po = (adset.promoted_object || {}) as Record<string, unknown>;
  // Everything below the conversion location comes from ITS entry, not the
  // objective's. Falling back to the objective's default keeps the panel
  // renderable if a stored spec carries a destination the matrix has since
  // dropped — the server re-validates and reports it either way.
  const dest =
    destinations.find((d) => d.value === adset.destination_type) ??
    destinations[0];
  const optGoals = dest?.optimization_goals ?? [];
  const billingEvents = dest?.billing_events ?? [];
  const ctas = dest?.call_to_actions ?? [];
  const goalRules = catalog.goal_rules?.[adset.optimization_goal];
  // The goal narrows the destination's formats — ThruPlay pays for watch time,
  // so it is a single video and neither an image nor a carousel can express it.
  // applyGoal already intersects these on change; reading only the destination
  // here left the picker offering a carousel the server would reject.
  const goalFormats = goalRules?.ad_formats;
  const adFormats = (dest?.ad_formats ?? []).filter(
    (f) => !goalFormats || goalFormats.includes(f.value)
  );
  const promotedKind =
    dest?.promoted_object_kind_by_goal?.[adset.optimization_goal] ?? 'none';
  // A prerequisite this destination needs that the plan still has no answer for.
  //
  // Read from the LIVE form, not from catalog.user_info_present: that map records
  // what the run collected before the editor opened and never changes, so the
  // warning survived the user filling the field in and became a permanent piece
  // of furniture. Every key below now checks the value the user is looking at.
  const adSetUrl = adset.ads[0]?.creative.link ?? '';
  const wantsWebsiteField = (dest?.required_user_info ?? []).includes(
    'website_url'
  );
  // Destinations where the ad set carries the URL control — Website URL below,
  // or App store URL for an app (which also writes down to every ad's link).
  // With one ad that control IS the ad's link, so AdCard drops its own Link
  // input rather than showing the same field twice.
  const adSetOwnsLink = wantsWebsiteField || promotedKind === 'application';
  // The builder falls back to the connected Page when there is no website, so a
  // non-empty link does not mean a real destination — a Page URL is the tell.
  const isPageFallback =
    !!pageId && adSetUrl.includes(`facebook.com/${pageId}`);
  const missingPrerequisites = (dest?.required_user_info ?? [])
    .filter((key) => {
      if (key === 'website_url') return !adSetUrl.trim() || isPageFallback;
      if (key === 'app_store_url')
        return !String(po.object_store_url ?? '').trim();
      return catalog.user_info_present?.[key] === false;
    })
    .map((key) => PREREQUISITE_FIXES[key] ?? `Missing ${key}.`);
  const capped = catalog.bid_strategies_requiring_amount.includes(
    adset.bid_strategy
  );
  // Dayparting needs a lifetime budget; budget scheduling needs a daily one.
  // Under CBO the campaign owns the budget, so its kind decides.
  const isLifetime =
    budgetMode === 'cbo' ? campaignIsLifetime : adset.lifetime_budget != null;
  const roasGoal = roasGoalOf(catalog);
  const genderValue =
    JSON.stringify(t.genders) === JSON.stringify([1])
      ? 'male'
      : JSON.stringify(t.genders) === JSON.stringify([2])
        ? 'female'
        : 'all';

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <TextInput
          label="Ad set name"
          value={adset.name}
          onChange={(e) => patchAdset({ name: e.currentTarget.value })}
          error={err(`${p}.name`)}
          classNames={selectClassNames}
          className="flex-1"
        />
        {canRemove && (
          <button
            onClick={onRemove}
            className="text-secondary-text/60 mt-5 ml-3 flex h-8 w-8 items-center justify-center rounded-full hover:bg-red-500/10 hover:text-red-400"
          >
            <Trash2 size={15} />
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* First, because it decides every option list below it. Hidden when the
            objective offers exactly one — Ads Manager shows no conversion
            location on Awareness or App promotion ad sets, and a select with a
            single option is a decision nobody is making. The value still ships;
            it just is not presented as a choice. */}
        {destinations.length > 1 && (
          <Select
            label={
              <InfoLabel
                label="Conversion location"
                help={dest?.help ?? FIELD_HELP.conversion_location}
              />
            }
            data={toSelectData(destinations)}
            renderOption={makeOptionRenderer(descsOf(destinations))}
            value={adset.destination_type}
            onChange={(v) => v && onChangeDestination(v)}
            error={err(`${p}.destination_type`)}
            classNames={selectClassNames}
            comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
          />
        )}
        <Select
          label={
            <InfoLabel
              label="Optimization goal"
              help={FIELD_HELP.optimization_goal}
            />
          }
          data={toSelectData(optGoals)}
          renderOption={makeOptionRenderer(descsOf(optGoals))}
          value={adset.optimization_goal}
          onChange={(v) => v && onChangeGoal(v)}
          error={err(`${p}.optimization_goal`)}
          classNames={selectClassNames}
          comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
        />
        <Select
          label={
            <InfoLabel label="Billing event" help={FIELD_HELP.billing_event} />
          }
          data={toSelectData(billingEvents)}
          renderOption={makeOptionRenderer(descsOf(billingEvents))}
          value={adset.billing_event}
          onChange={(v) => v && patchAdset({ billing_event: v })}
          error={err(`${p}.billing_event`)}
          classNames={selectClassNames}
          comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
        />
        {dest?.requires_lead_form &&
          (adset.lead_form_draft ? (
            // A form the user designed here. It does not exist yet, so there is
            // no id to show — naming it and saying when it appears is the honest
            // version of a form id the user cannot look up.
            <div className="flex flex-col gap-1">
              <span className="text-secondary-text text-[12px]">
                Instant form
              </span>
              <div className="border-underline/15 flex items-center justify-between gap-2 rounded-xl border px-3 py-2">
                <div className="flex min-w-0 flex-col">
                  <span className="text-primary-text truncate text-[13px]">
                    {adset.lead_form_draft.name}
                  </span>
                  <span className="text-secondary-text/70 text-[11px]">
                    {adset.lead_form_draft.questions.length} question
                    {adset.lead_form_draft.questions.length === 1 ? '' : 's'} ·
                    created when you publish
                  </span>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <button
                    type="button"
                    onClick={onBuildLeadForm}
                    className="text-secondary-text hover:text-primary-text text-[12px]"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => patchAdset({ lead_form_draft: null })}
                    className="text-secondary-text hover:text-primary-text text-[12px]"
                  >
                    Remove
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-1">
              <Select
                label="Instant form"
                description="The form on your Page this ad submits to."
                // Leaving this empty is a real choice, not a gap: publish creates
                // a default form against the finished campaign's name and copy.
                // So the "create one" option leads, and the Page's existing forms
                // follow.
                data={[
                  { value: '', label: 'Create a default one for me' },
                  ...[
                    // The chosen Page's own forms. Falls back to the server's
                    // snapshot for a catalog that predates the Page picker.
                    ...(page?.lead_forms ??
                      catalog.lead_form?.candidates ??
                      []),
                    ...extraLeadForms,
                  ].map((f) => ({
                    value: f.id,
                    label: f.name ? `${f.name} — ${f.id}` : f.id,
                  })),
                ]}
                value={
                  (adset.ads[0]?.creative.lead_gen_form_id as string | null) ??
                  ''
                }
                onChange={(v) =>
                  adset.ads.forEach((_ad, d) =>
                    patchCreative(d, { lead_gen_form_id: v || null })
                  )
                }
                error={err(`${p}.ads[0].creative.lead_gen_form_id`)}
                classNames={selectClassNames}
                comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
              />
              <button
                type="button"
                onClick={onBuildLeadForm}
                className="text-secondary-text hover:text-primary-text flex items-center gap-1 self-start text-[12px]"
              >
                <Plus size={12} /> Build a form
              </button>
            </div>
          ))}
        {budgetMode === 'adset' && (
          <>
            <Select
              label={
                <InfoLabel
                  label="Bid strategy"
                  help={FIELD_HELP.bid_strategy}
                />
              }
              data={toSelectData(bidStrategies)}
              renderOption={makeOptionRenderer(descsOf(bidStrategies))}
              value={adset.bid_strategy}
              onChange={(v) => v && patchAdset({ bid_strategy: v })}
              error={err(`${p}.bid_strategy`)}
              classNames={selectClassNames}
              comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
            />
            {capped && (
              <NumberInput
                label="Bid amount ($)"
                value={centsToDollars(adset.bid_amount)}
                min={0.01}
                decimalScale={2}
                onChange={(v) => patchAdset({ bid_amount: dollarsToCents(v) })}
                error={err(`${p}.bid_amount`)}
                classNames={selectClassNames}
              />
            )}
            {/* The ROAS goal carries its target here, not in bid_amount. */}
            {adset.bid_strategy === roasGoal.bid_strategy && (
              <NumberInput
                label="Minimum ROAS"
                description="2 means $2 back for every $1 spent."
                value={
                  adset.bid_constraints
                    ? adset.bid_constraints.roas_average_floor / roasGoal.scale
                    : ''
                }
                min={roasGoal.min / roasGoal.scale}
                max={roasGoal.max / roasGoal.scale}
                decimalScale={2}
                onChange={(v) =>
                  patchAdset({
                    bid_constraints: {
                      roas_average_floor: Math.round(
                        Number(v || 0) * roasGoal.scale
                      ),
                    },
                  })
                }
                error={err(`${p}.bid_constraints.roas_average_floor`)}
                classNames={selectClassNames}
              />
            )}
            <div>
              <div className="text-secondary-text mb-1 text-[12px]">
                <InfoLabel
                  label="Ad set budget type"
                  help={FIELD_HELP.budget_type}
                />
              </div>
              <SegmentedControl
                fullWidth
                size="xs"
                value={adset.lifetime_budget ? 'lifetime' : 'daily'}
                onChange={(v) =>
                  patchAdset(
                    v === 'lifetime'
                      ? {
                          lifetime_budget:
                            adset.lifetime_budget ||
                            adset.daily_budget ||
                            catalog.min_budget_cents,
                          daily_budget: null,
                          end_time:
                            adset.end_time ?? defaultEnd(adset.start_time),
                        }
                      : {
                          daily_budget:
                            adset.daily_budget ||
                            adset.lifetime_budget ||
                            catalog.min_budget_cents,
                          lifetime_budget: null,
                        }
                  )
                }
                data={[
                  { label: 'Daily', value: 'daily' },
                  { label: 'Lifetime', value: 'lifetime' },
                ]}
                classNames={segmentedControlClassNames}
              />
            </div>
            <NumberInput
              label={
                adset.lifetime_budget
                  ? 'Lifetime budget ($)'
                  : 'Daily budget ($)'
              }
              value={centsToDollars(
                adset.lifetime_budget ?? adset.daily_budget
              )}
              min={minDollars}
              decimalScale={2}
              onChange={(v) =>
                patchAdset(
                  adset.lifetime_budget != null
                    ? { lifetime_budget: dollarsToCents(v) }
                    : { daily_budget: dollarsToCents(v) }
                )
              }
              error={err(`${p}.daily_budget`) || err(`${p}.lifetime_budget`)}
              classNames={selectClassNames}
            />
            {adset.lifetime_budget != null && (
              <div className="text-secondary-text/60 text-[11px] md:col-span-2">
                Lifetime budget needs an end date on this ad set (set it under
                Schedule).
              </div>
            )}
          </>
        )}
      </div>

      {/* Conversion tracking (promoted_object) */}
      {promotedKind === 'pixel' && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Select
            label="Meta Pixel"
            data={catalog.pixel_candidates.map((px) => ({
              value: px.id,
              label: px.name || px.id,
            }))}
            value={(po.pixel_id as string) ?? null}
            onChange={(v) =>
              patchAdset({ promoted_object: { ...po, pixel_id: v } })
            }
            placeholder={
              catalog.pixel_candidates.length
                ? 'Select a pixel'
                : 'No pixel found'
            }
            error={err(`${p}.promoted_object.pixel_id`)}
            classNames={selectClassNames}
            comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
          />
          <Select
            label="Conversion event"
            data={pixelEventsOf(catalog).map((e) => ({
              value: e,
              label: e
                .replace(/_/g, ' ')
                .toLowerCase()
                .replace(/^\w/, (c) => c.toUpperCase()),
            }))}
            value={(po.custom_event_type as string) ?? null}
            onChange={(v) =>
              patchAdset({ promoted_object: { ...po, custom_event_type: v } })
            }
            error={err(`${p}.promoted_object.custom_event_type`)}
            classNames={selectClassNames}
            comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
          />
        </div>
      )}
      {promotedKind === 'page' && (
        <div className="border-underline/15 text-secondary-text/70 rounded-xl border border-dashed px-3 py-2.5 text-[12px]">
          {adset.destination_type === 'WHATSAPP'
            ? `Messages go to the WhatsApp number linked to ${page?.name || 'your Facebook Page'}. Change the Page under Campaign to use a different number.`
            : `This optimization goal promotes ${page?.name || 'your Facebook Page'} — change it under Campaign.`}
        </div>
      )}
      {/* Website destinations. Meta has no ad-set website field — the URL lives on
          each ad's creative.link — but an ad set holds several ads all pointing at
          the same site, so without this the user retypes it per ad. Writes down to
          every ad here. With a single ad this IS that ad's link and AdCard hides
          its own Link input; with several, the per-ad Link becomes an override. */}
      {wantsWebsiteField && (
        <TextInput
          label={
            <InfoLabel
              label="Website URL"
              help={
                adset.ads.length > 1
                  ? 'Where clicks land. Sets the link on every ad in this ad set; you can still override an individual ad below.'
                  : 'Where clicks land.'
              }
            />
          }
          placeholder="https://example.com"
          value={adset.ads[0]?.creative.link ?? ''}
          onChange={(e) => {
            const url = e.currentTarget.value;
            adset.ads.forEach((_ad, d) => patchCreative(d, { link: url }));
          }}
          error={err(`${p}.ads[0].creative.link`)}
          classNames={selectClassNames}
        />
      )}
      {/* App promotion. Meta binds ONE store URL and ONE OS per ad set, and puts
          the promoted app on the CAMPAIGN — so a plan covering both stores
          publishes as two separate Meta campaigns, one per store. The server
          splits them at publish; this is where each side is edited (or a split is
          made by hand with "Add ad set"). The app id is bound at publish from the
          account; the store URL is not, and had no input at all. */}
      {promotedKind === 'application' && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <TextInput
            label="App store URL"
            description="The listing this ad set sends people to."
            placeholder="https://apps.apple.com/app/id…"
            value={(po.object_store_url as string) ?? ''}
            onChange={(e) => {
              const url = e.currentTarget.value;
              patchAdset({ promoted_object: { ...po, object_store_url: url } });
              // The creative's link IS the store listing for an app ad; leaving
              // it behind sent people to the other store.
              adset.ads.forEach((_ad, d) => patchCreative(d, { link: url }));
            }}
            error={err(`${p}.promoted_object.object_store_url`)}
            classNames={selectClassNames}
          />
          <Select
            label={
              <InfoLabel
                label="Device platform"
                help="Meta puts the promoted app on the campaign, and iOS installs need their own SKAdNetwork campaign that can't carry Android. Ad sets on different platforms publish as separate campaigns."
              />
            }
            data={toSelectData(appPlatformsOf(catalog))}
            value={((t.user_os as string[]) ?? [])[0] ?? null}
            onChange={(v) => patchTargeting({ user_os: v ? [v] : undefined })}
            placeholder="All devices"
            error={err(`${p}.targeting.user_os`)}
            classNames={selectClassNames}
            comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
            clearable
          />
        </div>
      )}
      {/* A prerequisite the run never collected. It used to hang off the
          conversion-location select, which is hidden when the objective offers
          only one — exactly the App-promotion case that needs the warning most. */}
      {missingPrerequisites.length > 0 && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-[12px] text-amber-300">
          {missingPrerequisites.join(' ')}
        </div>
      )}

      {/* Schedule */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <DateTimePicker
          label="Start"
          valueFormat="MMM D, YYYY h:mm A"
          value={toLocalString(adset.start_time)}
          onChange={(v) =>
            patchAdset({ start_time: fromPicker(v) ?? adset.start_time })
          }
          error={err(`${p}.start_time`)}
          classNames={selectClassNames}
          popoverProps={{ withinPortal: true, zIndex: 1000000 }}
        />
        {/* A lifetime budget is spread over a window, so Meta (and CampaignSpec)
            require the end. Not clearable then — the × emptied the one field that
            is mandatory, and the label still said "optional". */}
        <DateTimePicker
          label={isLifetime ? 'End' : 'End (optional)'}
          required={isLifetime}
          valueFormat="MMM D, YYYY h:mm A"
          value={toLocalString(adset.end_time)}
          onChange={(v) => patchAdset({ end_time: fromPicker(v) })}
          clearable={!isLifetime}
          error={err(`${p}.end_time`)}
          classNames={selectClassNames}
          popoverProps={{ withinPortal: true, zIndex: 1000000 }}
        />
      </div>

      {/* Demographics */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <NumberInput
          label="Min age"
          value={(t.age_min as number) ?? 18}
          min={13}
          max={65}
          disabled={blocksDemographics}
          onChange={(v) => patchTargeting({ age_min: Number(v) || 18 })}
          classNames={selectClassNames}
        />
        <NumberInput
          label="Max age"
          value={(t.age_max as number) ?? 65}
          min={13}
          max={65}
          disabled={blocksDemographics}
          onChange={(v) => patchTargeting({ age_max: Number(v) || 65 })}
          classNames={selectClassNames}
        />
        <Select
          label="Gender"
          data={toSelectData(catalog.genders)}
          value={genderValue}
          disabled={blocksDemographics}
          onChange={(v) =>
            patchTargeting({
              genders: v === 'male' ? [1] : v === 'female' ? [2] : [],
            })
          }
          classNames={selectClassNames}
          comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
        />
      </div>
      {blocksDemographics && (
        <div className="text-secondary-text/60 -mt-2 flex items-center gap-1.5 text-[11px]">
          <Lock size={11} /> Age &amp; gender are locked for special ad
          categories.
        </div>
      )}

      {/* Placements */}
      <PlacementsField
        catalog={catalog}
        targeting={t}
        patchTargeting={patchTargeting}
      />

      {/* Interests / behaviors */}
      <InterestField targeting={t} patchTargeting={patchTargeting} />

      {/* Detailed-targeting exclusions */}
      <ExclusionField targeting={t} patchTargeting={patchTargeting} />

      {/* Attribution window — needs a conversion to attribute, which is a
          property of the optimization goal, not of the promoted object. */}
      {goalRules?.allows_attribution_spec !== false && (
        <AttributionField
          label="Attribution window"
          help={FIELD_HELP.attribution}
          value={(adset.attribution_spec as AttributionWindow[]) ?? []}
          onChange={(v) =>
            patchAdset({ attribution_spec: v.length ? v : null })
          }
          clickWindows={catalog.attribution.click_windows}
          viewWindows={catalog.attribution.view_windows}
          error={err(`${p}.attribution_spec`)}
        />
      )}

      {/* Frequency cap — Meta honours it on Reach and ThruPlay ad sets. */}
      {goalRules?.allows_frequency_control && (
        <FrequencyCapField
          catalog={catalog}
          value={adset.frequency_control_specs ?? []}
          onChange={(v) =>
            patchAdset({ frequency_control_specs: v.length ? v : null })
          }
          error={err(`${p}.frequency_control_specs`)}
        />
      )}

      {/* Scheduling. The two are opposites and each belongs to one budget kind,
          so only the applicable one is offered — showing both and erroring after
          submit is what made this inconsistent. */}
      {isLifetime ? (
        <DaypartingField
          label="Ad scheduling (dayparting)"
          help="Run ads only in chosen day/time windows. Lifetime budgets only."
          value={(adset.adset_schedule as DayPart[]) ?? []}
          onChange={(v) => patchAdset({ adset_schedule: v.length ? v : null })}
          error={err(`${p}.adset_schedule`)}
        />
      ) : (
        <BudgetScheduleField
          catalog={catalog}
          value={adset.budget_schedule_specs ?? []}
          onChange={(v) =>
            patchAdset({ budget_schedule_specs: v.length ? v : null })
          }
          error={err(`${p}.budget_schedule_specs`)}
        />
      )}

      {/* Advantage+ audience. The builder sets this per audience role and the
          user could never see or change it — including the fact that it turns
          their interests into suggestions rather than constraints. */}
      <AdvantageAudienceField targeting={t} patchTargeting={patchTargeting} />

      {/* Locked geo + audience */}
      {(locks.geo || locks.audience) && (
        <div className="border-underline/15 flex items-start gap-2 rounded-xl border border-dashed px-3 py-2.5">
          <Lock size={13} className="text-secondary-text/60 mt-0.5" />
          <div className="text-secondary-text/70 text-[12px]">
            <div className="text-secondary-text font-medium">
              Location &amp; audience (locked)
            </div>
            {adset.audience_role && <div>Audience: {adset.audience_role}</div>}
            <div>{summarizeGeo(t)}</div>
            <div className="text-secondary-text/50 mt-0.5">
              Confirmed earlier on the map — edit there if needed.
            </div>
          </div>
        </div>
      )}

      {/* Ads */}
      <div className="mt-1 flex items-center justify-between">
        <span className="text-secondary-text/80 text-[11px] font-medium tracking-wide uppercase">
          Ads
        </span>
        <button
          onClick={onAddAd}
          className="border-stroke-widget text-secondary-text/90 flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] hover:bg-white/5"
        >
          <Plus size={12} /> Add ad
        </button>
      </div>
      <div className="flex flex-col gap-3">
        {adset.ads.map((ad, d) => (
          <AdCard
            key={d}
            ad={ad}
            pathPrefix={`${p}.ads[${d}]`}
            errors={errors}
            ctas={ctas}
            adFormats={adFormats}
            limits={catalog.creative_limits}
            canRemove={adset.ads.length > 1}
            onRemove={() => onRemoveAd(d)}
            patchAd={(patch) => patchAd(d, patch)}
            patchCreative={(patch) => patchCreative(d, patch)}
            onGenerate={() => onGenerate(d)}
            requiresVideo={goalRules?.media_kind === 'video'}
            // With a single ad the ad-set URL control already IS this ad's link.
            hideLink={adSetOwnsLink && adset.ads.length === 1}
            objectStoryKind={dest?.object_story_kind}
            pageId={pageId}
          />
        ))}
      </div>
    </div>
  );
}

// ── Budget scheduling (high demand periods) ──────────────────────────────────
// Ads Manager's counterpart to dayparting: raise a *daily* budget over a window
// for a sale or a launch. Meta caps the raised budget at 8x.
function BudgetScheduleField({
  catalog,
  value,
  onChange,
  error,
}: {
  catalog: EditorCatalog;
  value: BudgetScheduleSpec[];
  onChange: (v: BudgetScheduleSpec[]) => void;
  error?: string;
}) {
  const cfg = catalog.budget_schedule;
  const scale = cfg?.multiplier_scale ?? 100;
  const maxX = (cfg?.max_multiplier ?? 800) / scale;

  const patch = (i: number, p: Partial<BudgetScheduleSpec>) =>
    onChange(value.map((r, idx) => (idx === i ? { ...r, ...p } : r)));

  const add = () => {
    const start = new Date();
    start.setDate(start.getDate() + 1);
    const end = new Date(start);
    end.setDate(end.getDate() + 1);
    onChange([
      ...value,
      {
        time_start: start.toISOString(),
        time_end: end.toISOString(),
        budget_value: 2 * scale,
        budget_value_type: 'MULTIPLIER',
      },
    ]);
  };

  return (
    <div className="flex flex-col gap-2">
      <InfoLabel
        label="Budget scheduling"
        help={`Temporarily raise the daily budget for a sale or launch. Up to ${maxX}x.`}
      />
      {value.map((row, i) => (
        <div
          key={i}
          className="border-underline/15 flex flex-wrap items-end gap-3 rounded-xl border p-3"
        >
          <DateTimePicker
            label="From"
            valueFormat="MMM D, YYYY h:mm A"
            value={toLocalString(row.time_start)}
            onChange={(v) =>
              patch(i, { time_start: fromPicker(v) ?? row.time_start })
            }
            classNames={selectClassNames}
            popoverProps={{ withinPortal: true, zIndex: 1000000 }}
          />
          <DateTimePicker
            label="To"
            valueFormat="MMM D, YYYY h:mm A"
            value={toLocalString(row.time_end)}
            onChange={(v) =>
              patch(i, { time_end: fromPicker(v) ?? row.time_end })
            }
            classNames={selectClassNames}
            popoverProps={{ withinPortal: true, zIndex: 1000000 }}
          />
          <NumberInput
            label="Multiplier"
            value={row.budget_value / scale}
            min={1.1}
            max={maxX}
            decimalScale={1}
            className="w-28"
            onChange={(v) =>
              patch(i, { budget_value: Math.round(Number(v || 1) * scale) })
            }
            classNames={selectClassNames}
          />
          <button
            onClick={() => onChange(value.filter((_, idx) => idx !== i))}
            className="text-secondary-text/60 mb-1 flex h-8 w-8 items-center justify-center rounded-full hover:bg-red-500/10 hover:text-red-400"
          >
            <Trash2 size={14} />
          </button>
        </div>
      ))}
      <button
        onClick={add}
        className="border-stroke-widget text-secondary-text/90 self-start rounded-full border px-2.5 py-1 text-[11px] hover:bg-white/5"
      >
        + Add a high-demand period
      </button>
      {error && <span className="text-[11px] text-red-400">{error}</span>}
    </div>
  );
}

// ── Advantage+ audience ──────────────────────────────────────────────────────
// targeting.targeting_automation.advantage_audience. The builder sets it (off
// for the MAID seed, on for prospecting) and the editor never showed it, so the
// user could not turn it off and was not told that with it on their interests
// and demographics become suggestions rather than limits.
function AdvantageAudienceField({
  targeting,
  patchTargeting,
}: {
  targeting: Record<string, unknown>;
  patchTargeting: (p: Record<string, unknown>) => void;
}) {
  const automation =
    (targeting.targeting_automation as { advantage_audience?: number }) || {};
  const on = automation.advantage_audience === 1;

  return (
    <div>
      <div className="text-secondary-text mb-1 text-[12px]">
        <InfoLabel
          label="Advantage+ audience"
          help="Meta looks beyond your targeting when it finds better results. Your age, gender and interests become suggestions rather than limits."
        />
      </div>
      <SegmentedControl
        fullWidth
        size="xs"
        value={on ? 'on' : 'off'}
        onChange={(v) =>
          patchTargeting({
            targeting_automation: { advantage_audience: v === 'on' ? 1 : 0 },
          })
        }
        data={[
          { label: 'Advantage+ (expand)', value: 'on' },
          { label: 'Use my targeting only', value: 'off' },
        ]}
        classNames={segmentedControlClassNames}
      />
      {on && (
        <div className="text-secondary-text/60 mt-1.5 text-[11px]">
          Interests and demographics below are suggestions — Meta may deliver
          outside them.
        </div>
      )}
    </div>
  );
}

// ── Placements ───────────────────────────────────────────────────────────────
function PlacementsField({
  catalog,
  targeting,
  patchTargeting,
}: {
  catalog: EditorCatalog;
  targeting: Record<string, unknown>;
  patchTargeting: (p: Record<string, unknown>) => void;
}) {
  const platforms = (targeting.publisher_platforms as string[]) || undefined;
  const mode = platforms ? 'manual' : 'advantage_plus';
  const posFieldBy = catalog.placements.position_field_by_platform;

  const setMode = (m: string) => {
    if (m === 'advantage_plus') {
      const cleared: Record<string, unknown> = {
        publisher_platforms: undefined,
      };
      Object.values(posFieldBy).forEach((f) => (cleared[f] = undefined));
      patchTargeting(cleared);
    } else {
      patchTargeting({
        publisher_platforms: catalog.placements.publisher_platforms.map(
          (o) => o.value
        ),
      });
    }
  };

  return (
    <div>
      <div className="text-secondary-text mb-1 text-[12px]">Placements</div>
      <SegmentedControl
        fullWidth
        size="xs"
        value={mode}
        onChange={setMode}
        data={[
          { label: 'Advantage+ (auto)', value: 'advantage_plus' },
          { label: 'Manual', value: 'manual' },
        ]}
        classNames={segmentedControlClassNames}
      />
      {mode === 'manual' && (
        <div className="mt-3 flex flex-col gap-3">
          <MultiSelect
            label="Platforms"
            data={toSelectData(catalog.placements.publisher_platforms)}
            value={platforms || []}
            onChange={(v) => patchTargeting({ publisher_platforms: v })}
            classNames={multiSelectClassNames}
            comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
          />
          {(platforms || []).map((plat) => {
            const field = posFieldBy[plat];
            const opts = catalog.placements.positions[plat];
            if (!field || !opts) return null;
            return (
              <MultiSelect
                key={plat}
                label={`${plat} positions`}
                data={toSelectData(opts)}
                value={(targeting[field] as string[]) || []}
                onChange={(v) => patchTargeting({ [field]: v })}
                classNames={multiSelectClassNames}
                comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
                clearable
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Interests / behaviors typeahead ──────────────────────────────────────────
type FlexEntry = {
  interests?: { id: string; name: string }[];
  behaviors?: { id: string; name: string }[];
};

function readSelected(
  targeting: Record<string, unknown>
): { id: string; name: string; flex_field: 'interests' | 'behaviors' }[] {
  const flex = (targeting.flexible_spec as FlexEntry[]) || [];
  const out: {
    id: string;
    name: string;
    flex_field: 'interests' | 'behaviors';
  }[] = [];
  flex.forEach((entry) => {
    (entry.interests || []).forEach((i) =>
      out.push({ id: i.id, name: i.name, flex_field: 'interests' })
    );
    (entry.behaviors || []).forEach((b) =>
      out.push({ id: b.id, name: b.name, flex_field: 'behaviors' })
    );
  });
  return out;
}

function writeSelected(
  selected: {
    id: string;
    name: string;
    flex_field: 'interests' | 'behaviors';
  }[]
): FlexEntry[] | undefined {
  const interests = selected
    .filter((s) => s.flex_field === 'interests')
    .map((s) => ({ id: s.id, name: s.name }));
  const behaviors = selected
    .filter((s) => s.flex_field === 'behaviors')
    .map((s) => ({ id: s.id, name: s.name }));
  const entry: FlexEntry = {};
  if (interests.length) entry.interests = interests;
  if (behaviors.length) entry.behaviors = behaviors;
  return Object.keys(entry).length ? [entry] : undefined;
}

function InterestField({
  targeting,
  patchTargeting,
}: {
  targeting: Record<string, unknown>;
  patchTargeting: (p: Record<string, unknown>) => void;
}) {
  const selected = readSelected(targeting);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<TargetingSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [suggested, setSuggested] = useState<TargetingSuggestion[]>([]);
  const [prefilled, setPrefilled] = useState(false);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  // One prefill per mount. A ref, not state, because removing a prefilled chip
  // changes `seeds` and re-runs the effect — without this the field would keep
  // putting back what the user just deleted.
  const didPrefill = useRef(false);

  const combobox = useCombobox({
    onDropdownClose: () => combobox.resetSelectedOption(),
  });

  useEffect(() => {
    if (results.length > 0) {
      combobox.openDropdown();
    } else {
      combobox.closeDropdown();
    }
  }, [results, combobox]);

  // Autofill options. With interests already picked the backend asks Meta for
  // "more like this"; with none it derives them from the session's business
  // context — a SaaS advertiser gets SaaS interests, not the field's example.
  const threadId = (useParams().threadId as string) || '';
  const seeds = selected
    .filter((s) => s.flex_field === 'interests')
    .map((s) => s.name)
    .join(',');
  useEffect(() => {
    let stale = false;
    suggestTargetingAction(threadId, seeds).then((res) => {
      if (stale) return;
      setSuggested(res);
      // Prefill the top few on open, but only into a field the user has left
      // completely empty — never overwrite or extend a choice they made.
      if (!didPrefill.current && selected.length === 0 && res.length) {
        didPrefill.current = true;
        const top = res.slice(0, 3);
        patchTargeting({
          flexible_spec: writeSelected(
            top.map((s) => ({
              id: s.id,
              name: s.name,
              flex_field: s.flex_field,
            }))
          ),
        });
        setPrefilled(true);
      }
    });
    return () => {
      stale = true;
    };
    // `selected` / `patchTargeting` are read fresh on each run; adding them
    // would refire the fetch on every keystroke elsewhere in the editor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId, seeds]);

  const runSearch = (q: string) => {
    setQuery(q);
    if (debounce.current) clearTimeout(debounce.current);
    if (!q.trim()) {
      setResults([]);
      return;
    }
    debounce.current = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await searchTargetingAction(q, 'interests');
        setResults(res);
      } finally {
        setLoading(false);
      }
    }, 300);
  };

  const add = (s: TargetingSuggestion) => {
    if (selected.some((x) => x.id === s.id)) return;
    patchTargeting({
      flexible_spec: writeSelected([
        ...selected,
        { id: s.id, name: s.name, flex_field: s.flex_field },
      ]),
    });
    setQuery('');
    setResults([]);
  };
  const remove = (id: string) =>
    patchTargeting({
      flexible_spec: writeSelected(selected.filter((s) => s.id !== id)),
    });

  const suggestedUnpicked = suggested
    .filter((s) => !selected.some((x) => x.id === s.id))
    .slice(0, 12);

  return (
    <div>
      <div className="text-secondary-text mb-1 text-[12px]">
        Detailed targeting (interests &amp; behaviors)
      </div>
      <Combobox
        store={combobox}
        withinPortal
        zIndex={1000001}
        onOptionSubmit={(val) => {
          const matched = results.find((r) => r.id === val);
          if (matched) add(matched);
          combobox.closeDropdown();
        }}
      >
        <Combobox.Target>
          <div className="border-primary-text/10! text-primary-text! flex min-h-10! w-full! flex-col! gap-2! rounded-[20px]! border! bg-transparent! p-3! shadow-[0px_-1px_0px_0px_#00000026_inset,0px_1px_0px_0px_#FFFFFF0F_inset]!">
            <div className="flex w-full items-center gap-2">
              <Search size={14} className="text-secondary-text/60 shrink-0" />
              <input
                value={query}
                onChange={(e) => {
                  runSearch(e.target.value);
                  combobox.openDropdown();
                }}
                placeholder="Search interests and behaviors…"
                className="text-primary-text min-w-0 flex-1 border-none bg-transparent py-0.5 text-[13px] outline-none"
              />
              {loading && <Loader size={13} />}
            </div>
            {selected.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1.5">
                {selected.map((s) => (
                  <Box
                    key={s.id}
                    className="bg-primary-bg! border-stroke-widget! flex h-6.5! items-center! gap-1! rounded-full! border py-0! pr-1! pl-2 shadow-[0px_1.5px_3px_#00000040]!"
                  >
                    <Text className="text-primary-text! mb-px! text-[11px]!">
                      {s.name}
                    </Text>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        remove(s.id);
                      }}
                      className="text-secondary-text! flex size-4! items-center justify-center! p-0! transition-colors! hover:bg-transparent! hover:text-red-400!"
                    >
                      <X size={12} />
                    </button>
                  </Box>
                ))}
              </div>
            )}
          </div>
        </Combobox.Target>

        <Combobox.Dropdown classNames={{ dropdown: selectClassNames.dropdown }}>
          <Combobox.Options className="custom-textarea-scrollbar max-h-56 overflow-y-auto p-1">
            {results.map((r) => (
              <Combobox.Option
                key={r.id}
                value={r.id}
                className="text-primary-text/80 flex w-full cursor-pointer items-center justify-between rounded-lg px-3 py-2 text-left text-[13px] hover:bg-white/5"
              >
                <span>{r.name}</span>
                {r.path && (
                  <span className="text-secondary-text/50 ml-2 truncate text-[11px]">
                    {r.path.join(' › ')}
                  </span>
                )}
              </Combobox.Option>
            ))}
          </Combobox.Options>
        </Combobox.Dropdown>
      </Combobox>
      {/* A prefill narrows the audience without the user asking, so it has to
          announce itself — otherwise it silently ships in the published plan. */}
      {prefilled && selected.length > 0 && (
        <div className="text-secondary-text/60 mt-1.5 text-[11px]">
          Added from your business details — remove any that don&apos;t fit.
        </div>
      )}
      {suggestedUnpicked.length > 0 && (
        <div className="mt-2">
          <div className="text-secondary-text/60 mb-1 text-[11px]">
            Suggested
          </div>
          <div className="flex flex-wrap gap-1.5">
            {suggestedUnpicked.map((s) => (
              <button
                key={s.id}
                onClick={() => add(s)}
                className="border-stroke-widget/60 text-secondary-text hover:text-primary-text flex items-center gap-1 rounded-full border border-dashed px-2.5 py-1 text-[11px] hover:bg-white/5"
              >
                <Plus size={10} />
                {s.name}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Detailed-targeting exclusions ────────────────────────────────────────────
// Writes targeting.exclusions = { interests: [...], behaviors: [...] } — the
// "Exclude people" side of detailed targeting. Same search backend as includes.
function ExclusionField({
  targeting,
  patchTargeting,
}: {
  targeting: Record<string, unknown>;
  patchTargeting: (p: Record<string, unknown>) => void;
}) {
  const excl = (targeting.exclusions as FlexEntry) || {};
  const selected: {
    id: string;
    name: string;
    flex_field: 'interests' | 'behaviors';
  }[] = [
    ...(excl.interests || []).map((i) => ({
      ...i,
      flex_field: 'interests' as const,
    })),
    ...(excl.behaviors || []).map((b) => ({
      ...b,
      flex_field: 'behaviors' as const,
    })),
  ];
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<TargetingSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const combobox = useCombobox({
    onDropdownClose: () => combobox.resetSelectedOption(),
  });

  useEffect(() => {
    if (results.length > 0) {
      combobox.openDropdown();
    } else {
      combobox.closeDropdown();
    }
  }, [results, combobox]);

  const write = (
    next: { id: string; name: string; flex_field: 'interests' | 'behaviors' }[]
  ) => {
    const interests = next
      .filter((s) => s.flex_field === 'interests')
      .map((s) => ({ id: s.id, name: s.name }));
    const behaviors = next
      .filter((s) => s.flex_field === 'behaviors')
      .map((s) => ({ id: s.id, name: s.name }));
    const entry: FlexEntry = {};
    if (interests.length) entry.interests = interests;
    if (behaviors.length) entry.behaviors = behaviors;
    patchTargeting({
      exclusions: Object.keys(entry).length ? entry : undefined,
    });
  };

  const runSearch = (q: string) => {
    setQuery(q);
    if (debounce.current) clearTimeout(debounce.current);
    if (!q.trim()) {
      setResults([]);
      return;
    }
    debounce.current = setTimeout(async () => {
      setLoading(true);
      try {
        setResults(await searchTargetingAction(q, 'interests'));
      } finally {
        setLoading(false);
      }
    }, 300);
  };

  const add = (s: TargetingSuggestion) => {
    if (selected.some((x) => x.id === s.id)) return;
    write([...selected, { id: s.id, name: s.name, flex_field: s.flex_field }]);
    setQuery('');
    setResults([]);
  };
  const remove = (id: string) => write(selected.filter((s) => s.id !== id));

  return (
    <div>
      <div className="text-secondary-text mb-1 text-[12px]">
        Exclude people (interests &amp; behaviors)
      </div>
      <Combobox
        store={combobox}
        withinPortal
        zIndex={1000001}
        onOptionSubmit={(val) => {
          const matched = results.find((r) => r.id === val);
          if (matched) add(matched);
          combobox.closeDropdown();
        }}
      >
        <Combobox.Target>
          <div className="border-primary-text/10! text-primary-text! flex min-h-10! w-full! flex-col! gap-2! rounded-[20px]! border! bg-transparent! p-3! shadow-[0px_-1px_0px_0px_#00000026_inset,0px_1px_0px_0px_#FFFFFF0F_inset]!">
            <div className="flex w-full items-center gap-2">
              <Search size={14} className="text-secondary-text/60 shrink-0" />
              <input
                value={query}
                onChange={(e) => {
                  runSearch(e.target.value);
                  combobox.openDropdown();
                }}
                placeholder="Search interests to exclude…"
                className="text-primary-text min-w-0 flex-1 border-none bg-transparent py-0.5 text-[13px] outline-none"
              />
              {loading && <Loader size={13} />}
            </div>
            {selected.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1.5">
                {selected.map((s) => (
                  <Box
                    key={s.id}
                    className="bg-primary-bg! border-stroke-widget! flex h-6.5! items-center! gap-1! rounded-full! border py-0! pr-1! pl-2 shadow-[0px_1.5px_3px_#00000040]!"
                  >
                    <Text className="text-primary-text! mb-0.5! text-[11px]!">
                      {s.name}
                    </Text>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        remove(s.id);
                      }}
                      className="text-secondary-text! flex size-4! items-center justify-center! p-0! transition-colors! hover:bg-transparent! hover:text-red-400!"
                    >
                      <X size={12} />
                    </button>
                  </Box>
                ))}
              </div>
            )}
          </div>
        </Combobox.Target>

        <Combobox.Dropdown classNames={{ dropdown: selectClassNames.dropdown }}>
          <Combobox.Options className="custom-textarea-scrollbar max-h-56 overflow-y-auto p-1">
            {results.map((r) => (
              <Combobox.Option
                key={r.id}
                value={r.id}
                className="text-primary-text/80 flex w-full cursor-pointer items-center justify-between rounded-lg px-3 py-2 text-left text-[13px] hover:bg-white/5"
              >
                <span>{r.name}</span>
                {r.path && (
                  <span className="text-secondary-text/50 ml-2 truncate text-[11px]">
                    {r.path.join(' › ')}
                  </span>
                )}
              </Combobox.Option>
            ))}
          </Combobox.Options>
        </Combobox.Dropdown>
      </Combobox>
    </div>
  );
}

// One editable copy field (headline or body) with its AI suggestions folded into
// the SAME control: type/edit freely, or click the chevron to pick a suggestion
// (which fills the field). No separate dropdown + text box — one combined input.
function CopyField({
  label,
  value,
  suggestions,
  maxLength,
  error,
  multiline,
  onChange,
}: {
  label: string;
  value: string;
  suggestions: string[];
  maxLength: number;
  error?: string;
  multiline?: boolean;
  onChange: (v: string) => void;
}) {
  const combobox = useCombobox();
  const options = suggestions
    .filter((s) => s && s !== value)
    .map((s) => (
      <Combobox.Option value={s} key={s}>
        {s}
      </Combobox.Option>
    ));
  const hasOptions = options.length > 0;
  const rightSection = hasOptions ? (
    <Combobox.Chevron
      onClick={() => combobox.toggleDropdown()}
      style={{ cursor: 'pointer' }}
    />
  ) : null;
  const common = {
    label: `${label} (${(value || '').length}/${maxLength})`,
    value,
    maxLength,
    error,
    classNames: selectClassNames,
    rightSection,
    rightSectionPointerEvents: hasOptions
      ? ('all' as const)
      : ('none' as const),
  };
  const target = multiline ? (
    <Textarea
      {...common}
      autosize
      minRows={2}
      maxRows={4}
      onChange={(e) => onChange(e.currentTarget.value)}
    />
  ) : (
    <TextInput {...common} onChange={(e) => onChange(e.currentTarget.value)} />
  );
  return (
    <Combobox
      store={combobox}
      withinPortal
      zIndex={1000000}
      onOptionSubmit={(v) => {
        onChange(v);
        combobox.closeDropdown();
      }}
    >
      <Combobox.Target>{target}</Combobox.Target>
      <Combobox.Dropdown>
        <Combobox.Options>{options}</Combobox.Options>
      </Combobox.Dropdown>
    </Combobox>
  );
}

// ── Ad card ──────────────────────────────────────────────────────────────────
function AdCard({
  ad,
  pathPrefix,
  errors,
  ctas,
  adFormats,
  limits,
  canRemove,
  onRemove,
  patchAd,
  patchCreative,
  onGenerate,
  requiresVideo,
  hideLink,
  objectStoryKind,
  pageId,
}: {
  ad: EditorAd;
  pathPrefix: string;
  errors: Record<string, string>;
  ctas: EditorOption[];
  adFormats: EditorOption[];
  limits: {
    title_max: number;
    body_max: number;
    carousel_min_cards: number;
    carousel_max_cards: number;
  };
  canRemove: boolean;
  onRemove: () => void;
  patchAd: (p: Partial<EditorAd>) => void;
  patchCreative: (p: Partial<EditorAd['creative']>) => void;
  onGenerate: () => void;
  // The optimization goal demands a video (ThruPlay). Constrains the file picker
  // and rules out AI generation, which produces images.
  requiresVideo?: boolean;
  // The ad set owns the URL and this is its only ad, so the Link input here
  // would be the same field rendered twice. Shown again as soon as the ad set
  // has more than one ad, where a per-ad link is a real override.
  hideLink?: boolean;
  objectStoryKind?: string;
  pageId?: string | null;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const c = ad.creative;
  const err = (k: string) => errors[`${pathPrefix}.${k}`];
  const format = c.format ?? 'SINGLE';
  const isCarousel = format === 'CAROUSEL';
  const cards = c.cards ?? [];

  // A carousel carries its media per card, a single ad on the creative — so
  // switching format has to move the fields, not just flip a flag, or the server
  // rejects the spec (CreativeSpec._format_matches_media).
  const changeFormat = (next: string) => {
    if (next === format) return;
    if (next === 'CAROUSEL') {
      const seeded: EditorCarouselCard[] = Array.from(
        { length: limits.carousel_min_cards },
        (_, i) => ({
          title: c.title,
          body: c.body,
          link: c.link,
          // The existing image becomes the first card's.
          media_id: i === 0 ? (c.media_id ?? null) : null,
          media_url: i === 0 ? (c.media_url ?? null) : null,
        })
      );
      patchCreative({
        format: next,
        cards: seeded,
        media_id: null,
        image_hash: null,
        video_id: null,
        media_url: null,
      });
    } else {
      const first = cards[0];
      patchCreative({
        format: next,
        cards: null,
        media_id: first?.media_id ?? null,
        media_url: first?.media_url ?? null,
      });
    }
  };

  const patchCard = (i: number, patch: Partial<EditorCarouselCard>) =>
    patchCreative({
      cards: cards.map((card, idx) =>
        idx === i ? { ...card, ...patch } : card
      ),
    });

  // AI copy candidates the CopyField folds into its own dropdown. The user edits
  // the field freely or picks a suggestion; only the single title/body is
  // published. Current value included so a hand-edited pick still lists.
  const titleSuggestions = Array.from(
    new Set([...(c.title_suggestions ?? []), c.title].filter(Boolean))
  ) as string[];
  const bodySuggestions = Array.from(
    new Set([...(c.body_suggestions ?? []), c.body].filter(Boolean))
  ) as string[];

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await uploadMediaAction(fd);
      if (res.success && res.data) {
        patchCreative({
          media_id: res.data.id,
          media_url: res.data.file_path,
          media_kind: res.data.media_type === 'video' ? 'video' : 'image',
          image_hash: null,
          video_id: null,
        });
      }
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  return (
    <div className="border-underline/15 rounded-xl border p-3">
      <div className="flex items-center justify-between">
        <TextInput
          value={ad.name}
          onChange={(e) => patchAd({ name: e.currentTarget.value })}
          placeholder="Ad name"
          classNames={{ input: `${selectClassNames.input} font-medium` }}
          className="flex-1"
          variant="unstyled"
        />
        {canRemove && (
          <button
            onClick={onRemove}
            className="text-secondary-text/60 flex h-7 w-7 items-center justify-center rounded-full hover:bg-red-500/10 hover:text-red-400"
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>

      {/* Boost destinations replace the whole composer: the ad IS an existing
          Page post, so there is no copy, media or format to choose. */}
      {objectStoryKind ? (
        <PagePostPicker
          kind={objectStoryKind}
          pageId={pageId}
          value={c.object_story_id ?? null}
          onChange={(id) => patchCreative({ object_story_id: id })}
          error={err('creative.object_story_id')}
        />
      ) : (
        <>
          {/* Ad setup. Only the formats this conversion location supports — Messenger
          renders one card, catalog sales is always a carousel. */}
          {adFormats.length > 1 && (
            <SegmentedControl
              fullWidth
              size="xs"
              className="mt-2"
              value={format}
              onChange={changeFormat}
              data={adFormats.map((f) => ({ value: f.value, label: f.label }))}
              classNames={segmentedControlClassNames}
            />
          )}
          {err('creative.format') && (
            <span className="mt-1 block text-[11px] text-red-400">
              {err('creative.format')}
            </span>
          )}

          <div className="mt-2 grid grid-cols-1 gap-3 md:grid-cols-[1fr_120px]">
            <div className="flex flex-col gap-3">
              {/* Headline — edit inline; chevron reveals AI suggestions to pick from */}
              <CopyField
                label="Headline"
                value={c.title}
                suggestions={titleSuggestions}
                maxLength={limits.title_max}
                error={err('creative.title')}
                onChange={(v) => patchCreative({ title: v })}
              />

              {/* Body — edit inline; chevron reveals AI suggestions to pick from */}
              <CopyField
                label="Body"
                value={c.body}
                suggestions={bodySuggestions}
                maxLength={limits.body_max}
                error={err('creative.body')}
                multiline
                onChange={(v) => patchCreative({ body: v })}
              />

              {/* Call to action */}
              <Select
                label="Call to action"
                data={toSelectData(ctas)}
                value={c.call_to_action}
                onChange={(v) => v && patchCreative({ call_to_action: v })}
                error={err('creative.call_to_action')}
                classNames={selectClassNames}
                comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
              />

              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {!hideLink && (
                  <TextInput
                    label="Link"
                    value={c.link}
                    onChange={(e) =>
                      patchCreative({ link: e.currentTarget.value })
                    }
                    error={err('creative.link')}
                    classNames={selectClassNames}
                  />
                )}
                <TextInput
                  label="URL parameters (optional)"
                  placeholder="utm_source=facebook&utm_medium=paid"
                  value={c.url_tags ?? ''}
                  onChange={(e) =>
                    patchCreative({ url_tags: e.currentTarget.value || null })
                  }
                  error={err('creative.url_tags')}
                  classNames={selectClassNames}
                />
              </div>
            </div>

            {/* Image — a carousel's media lives on its cards instead */}
            {!isCarousel && (
              <div className="flex flex-col items-center gap-2">
                <div className="border-underline/15 flex h-28 w-full items-center justify-center overflow-hidden rounded-xl border">
                  {c.media_url ? (
                    <img
                      src={c.media_url}
                      alt="ad"
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <ImageIcon size={22} className="text-secondary-text/40" />
                  )}
                </div>
                <div className="flex w-full gap-1.5">
                  <Tooltip
                    label={requiresVideo ? 'Upload video' : 'Upload image'}
                    styles={tooltipStyles}
                  >
                    <button
                      onClick={() => fileRef.current?.click()}
                      className="border-stroke-widget text-secondary-text/90 flex flex-1 items-center justify-center gap-1 rounded-lg border py-1.5 text-[11px] hover:bg-white/5"
                    >
                      {uploading ? <Loader size={11} /> : <Upload size={12} />}
                    </button>
                  </Tooltip>
                  {/* Generation produces images, so it can only ever build an ad this
                  goal rejects. Say why rather than letting them find out at publish. */}
                  <Tooltip
                    label={
                      requiresVideo
                        ? 'This goal pays for watch time, so the ad needs a video — upload one'
                        : 'Generate with Punk ideas'
                    }
                    styles={tooltipStyles}
                  >
                    <button
                      onClick={onGenerate}
                      disabled={requiresVideo}
                      className="border-stroke-widget text-secondary-text/90 flex flex-1 items-center justify-center gap-1 rounded-lg border py-1.5 text-[11px] hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
                    >
                      <Sparkles size={12} />
                    </button>
                  </Tooltip>
                </div>
                <input
                  ref={fileRef}
                  type="file"
                  accept={requiresVideo ? 'video/*' : 'image/*'}
                  className="hidden"
                  onChange={onFile}
                />
              </div>
            )}
          </div>

          {isCarousel && (
            <CarouselCards
              cards={cards}
              pathPrefix={pathPrefix}
              errors={errors}
              limits={limits}
              patchCard={patchCard}
              onAdd={() =>
                patchCreative({
                  cards: [
                    ...cards,
                    { title: c.title, body: c.body, link: c.link },
                  ],
                })
              }
              onRemove={(i) =>
                patchCreative({ cards: cards.filter((_x, idx) => idx !== i) })
              }
            />
          )}
        </>
      )}
    </div>
  );
}

// ── Page post picker ─────────────────────────────────────────────────────────
// Engagement's "On your post / video / event" ads promote something that already
// exists on the Page — the ad is that post, with the reactions and comments it
// has already collected. Publishing one needs its object_story_id, so the user
// has to choose it; we never had a way to ask, which is why those destinations
// could be selected but not honoured.
function PagePostPicker({
  kind,
  pageId,
  value,
  onChange,
  error,
}: {
  kind: string;
  pageId?: string | null;
  value: string | null;
  onChange: (id: string | null) => void;
  error?: string;
}) {
  const [items, setItems] = useState<PageObject[]>([]);
  // Starts true so the first render shows the loader without the effect having
  // to set state synchronously.
  const [loading, setLoading] = useState(true);

  // Fetched on demand: only a boost destination opens this, so a plan that never
  // uses one costs no Graph call.
  useEffect(() => {
    if (!pageId) return;
    let live = true;
    listPageObjectsAction(pageId, kind as 'post' | 'video' | 'event')
      .then((res) => live && setItems(res))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [pageId, kind]);

  const noun = kind === 'video' ? 'video' : kind === 'event' ? 'event' : 'post';

  return (
    <div className="mt-3 flex flex-col gap-2">
      <InfoLabel
        label={`Which ${noun} do you want to promote?`}
        help={`The ad is this ${noun} — its image, its caption, and the reactions it already has. There is no separate copy to write.`}
      />
      {!pageId && (
        <span className="text-[11px] text-red-400">
          Connect a Facebook Page to pick a {noun}.
        </span>
      )}
      {loading && <Loader size="xs" />}
      {!loading && pageId && !items.length && (
        <span className="text-secondary-text/60 text-[11px]">
          No {noun}s found on your Page. Publish one first, then come back.
        </span>
      )}
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
        {items.map((item) => {
          const selected = item.id === value;
          return (
            <button
              key={item.id}
              onClick={() => onChange(selected ? null : item.id)}
              className={`flex flex-col overflow-hidden rounded-xl border text-left transition ${
                selected
                  ? 'border-purple-400 ring-1 ring-purple-400/40'
                  : 'border-underline/15 hover:border-underline/40'
              }`}
            >
              <div className="bg-primary-widget aspect-video w-full overflow-hidden">
                {item.image && (
                  <img
                    src={item.image}
                    alt=""
                    className="h-full w-full object-cover"
                  />
                )}
              </div>
              <span className="text-secondary-text/80 line-clamp-2 px-2 py-1.5 text-[11px]">
                {item.label || item.id}
              </span>
            </button>
          );
        })}
      </div>
      {error && <span className="text-[11px] text-red-400">{error}</span>}
    </div>
  );
}

// ── Carousel cards ───────────────────────────────────────────────────────────
// Each card is its own image, headline, description and link — N mini-ads, not
// one ad with extra pictures. Meta renders them in order, so the list is
// reorderable.
function CarouselCards({
  cards,
  pathPrefix,
  errors,
  limits,
  patchCard,
  onAdd,
  onRemove,
}: {
  cards: EditorCarouselCard[];
  pathPrefix: string;
  errors: Record<string, string>;
  limits: {
    title_max: number;
    body_max: number;
    carousel_min_cards: number;
    carousel_max_cards: number;
  };
  patchCard: (i: number, p: Partial<EditorCarouselCard>) => void;
  onAdd: () => void;
  onRemove: (i: number) => void;
}) {
  return (
    <div className="mt-3 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-secondary-text/80 text-[11px] font-medium tracking-wide uppercase">
          Cards ({cards.length}/{limits.carousel_max_cards})
        </span>
        {cards.length < limits.carousel_max_cards && (
          <button
            onClick={onAdd}
            className="border-stroke-widget text-secondary-text/90 flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px]! hover:bg-white/5"
          >
            <Plus size={12} /> Add card
          </button>
        )}
      </div>
      {errors[`${pathPrefix}.creative.cards`] && (
        <span className="text-[11px] text-red-400">
          {errors[`${pathPrefix}.creative.cards`]}
        </span>
      )}
      {/* Horizontal, like Meta renders it. Scrolls inside itself so the modal
          body never scrolls sideways. */}
      <div className="flex gap-2 overflow-x-auto pb-1">
        {cards.map((card, i) => (
          <div
            key={i}
            className="border-underline/15 flex w-56 shrink-0 flex-col gap-2 rounded-xl border p-2"
          >
            <div className="flex items-center justify-between">
              <span className="text-secondary-text/60 text-[11px]">
                Card {i + 1}
              </span>
              {cards.length > limits.carousel_min_cards && (
                <button
                  onClick={() => onRemove(i)}
                  className="text-secondary-text/60 flex h-6 w-6 items-center justify-center rounded-full hover:bg-red-500/10 hover:text-red-400"
                >
                  <Trash2 size={12} />
                </button>
              )}
            </div>
            <div className="border-underline/15 flex h-20 items-center justify-center overflow-hidden rounded-lg border">
              {card.media_url ? (
                <img
                  src={card.media_url}
                  alt={`card ${i + 1}`}
                  className="h-full w-full object-cover"
                />
              ) : (
                <ImageIcon size={18} className="text-secondary-text/40" />
              )}
            </div>
            <CardMediaButton onPicked={(p) => patchCard(i, p)} />
            <TextInput
              placeholder="Headline"
              value={card.title}
              maxLength={limits.title_max}
              onChange={(e) => patchCard(i, { title: e.currentTarget.value })}
              error={errors[`${pathPrefix}.creative.cards[${i}].title`]}
              classNames={selectClassNames}
            />
            <TextInput
              placeholder="Description"
              value={card.body ?? ''}
              maxLength={limits.body_max}
              onChange={(e) =>
                patchCard(i, { body: e.currentTarget.value || null })
              }
              classNames={selectClassNames}
            />
            <TextInput
              placeholder="Link"
              value={card.link}
              onChange={(e) => patchCard(i, { link: e.currentTarget.value })}
              error={errors[`${pathPrefix}.creative.cards[${i}].link`]}
              classNames={selectClassNames}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function CardMediaButton({
  onPicked,
}: {
  onPicked: (p: Partial<EditorCarouselCard>) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await uploadMediaAction(fd);
      if (res.success && res.data) {
        onPicked({
          media_id: res.data.id,
          media_url: res.data.file_path,
          media_kind: res.data.media_type === 'video' ? 'video' : 'image',
          image_hash: null,
          video_id: null,
        });
      }
    } finally {
      setBusy(false);
      if (ref.current) ref.current.value = '';
    }
  };
  return (
    <>
      <button
        onClick={() => ref.current?.click()}
        className="border-stroke-widget text-secondary-text/90 flex items-center justify-center gap-1 rounded-lg border py-1 text-[11px] hover:bg-white/5"
      >
        {busy ? <Loader size={11} /> : <Upload size={12} />}
      </button>
      <input
        ref={ref}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={onFile}
      />
    </>
  );
}

function summarizeGeo(t: Record<string, unknown>): string {
  const geo = (t.geo_locations as Record<string, unknown>) || {};
  const zips = (geo.zips as { key: string }[]) || [];
  const cities = (geo.cities as { name: string }[]) || [];
  if (zips.length) return `${zips.length} ZIP code(s) targeted`;
  if (cities.length) return cities.map((c) => c.name).join(', ');
  return 'Geo targeting from the map step';
}
