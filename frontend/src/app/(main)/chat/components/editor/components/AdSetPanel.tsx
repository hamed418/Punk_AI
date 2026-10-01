import {
  Select,
  TextInput,
  NumberInput,
  SegmentedControl,
} from '@mantine/core';
import { DateTimePicker } from '@mantine/dates';
import { Trash2, Plus, Lock } from 'lucide-react';
import type {
  EditorAdSet,
  EditorCatalog,
  EditorDestination,
  EditorOption,
  EditorAd,
  EditorLocks,
  EditorPage,
} from '@/types/chat';
import {
  AttributionField,
  DaypartingField,
  type AttributionWindow,
  type DayPart,
} from '../../forms/scheduleFields';
import { InfoLabel, makeOptionRenderer } from '../../forms/InfoLabel';
import AudienceTargetingField from './AudienceTargetingField';
import {
  centsToDollars,
  dollarsToCents,
  toLocalString,
  fromPicker,
  selectClassNames,
  segmentedControlClassNames,
  toSelectData,
  descsOf,
  FIELD_HELP,
  pixelEventsOf,
  PREREQUISITE_FIXES,
  appPlatformsOf,
  roasGoalOf,
  summarizeGeo,
  defaultEnd,
  isPageFallbackLink,
  pageWhatsAppLinked,
  AUDIENCE_ROLE_COPY,
} from './editorUtils';
import FrequencyCapField from './FrequencyCapField';
import BudgetScheduleField from './BudgetScheduleField';
import AdvantageAudienceField from './AdvantageAudienceField';
import PlacementsField from './PlacementsField';
import InterestField from './InterestField';
import ExclusionField from './ExclusionField';
import AdCard from './AdCard';

interface Props {
  adset: EditorAdSet;
  index: number;
  catalog: EditorCatalog;
  errors: Record<string, string>;
  locks: EditorLocks;
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
  onAddAd: (patches?: Partial<EditorAd['creative']>[]) => void;
  onRemoveAd: (d: number) => void;
  patchAd: (d: number, p: Partial<EditorAd>) => void;
  patchCreative: (d: number, p: Partial<EditorAd['creative']>) => void;
  onGenerate: (d: number) => void;
  extraLeadForms: { id: string; name?: string }[];
  onBuildLeadForm: () => void;
  pageId: string | null;
  creativeSource?: string;
  page?: EditorPage;
  // Which half of the panel to render — the tree nav shows the ad-set settings
  // and each ad as separate nodes, so CampaignEditor asks for one at a time.
  // Omitted (both) is what the old single-pane accordion used.
  show?: 'settings' | 'ad';
  // With `show="ad"`, which ad to render alone. Omitted renders every ad —
  // used by nothing today but keeps the component correct if that changes.
  adIndex?: number;
}

export default function AdSetPanel({
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
  creativeSource,
  page,
  show,
  adIndex,
}: Props) {
  const p = `adsets[${index}]`;
  const err = (k: string) => errors[k];
  const t = adset.targeting || {};
  const po = (adset.promoted_object || {}) as Record<string, unknown>;

  const dest =
    destinations.find((d) => d.value === adset.destination_type) ??
    destinations[0];
  const optGoals = dest?.optimization_goals ?? [];
  const ctas = dest?.call_to_actions ?? [];
  const goalRules = catalog.goal_rules?.[adset.optimization_goal];

  // Every list below is the INTERSECTION of what the conversion location allows
  // and what the goal allows — the destination's list alone offered pairs the
  // server rejects (Sales → Website → Conversions never bills per link click,
  // and only the ROAS goal takes the minimum-ROAS bid strategy).
  const goalBilling = goalRules?.billing_events;
  const billingEvents = (dest?.billing_events ?? []).filter(
    (e) => !goalBilling || goalBilling.includes(e.value)
  );
  const goalBids = goalRules?.bid_strategies;
  const goalBidStrategies = bidStrategies.filter(
    (s) => !goalBids || goalBids.includes(s.value)
  );
  const goalFormats = goalRules?.ad_formats;
  const adFormats = (dest?.ad_formats ?? []).filter(
    (f) => !goalFormats || goalFormats.includes(f.value)
  );
  const promotedKind =
    dest?.promoted_object_kind_by_goal?.[adset.optimization_goal] ?? 'none';
  // The nearest pixel-promoting goal THIS destination offers, if any — the
  // escape hatch below switches to it so the Conversion tracking block (which
  // only renders on promotedKind === 'pixel') becomes reachable again after a
  // cold-dataset account got stepped down onto a non-pixel goal.
  const pixelGoal = optGoals.find(
    (g) => dest?.promoted_object_kind_by_goal?.[g.value] === 'pixel'
  )?.value;
  // Surfaced where the user actually picks, not only at publish — a cold
  // pixel optimizes exactly as badly as no pixel at all.
  const pixelOptions = catalog.pixel_candidates.map((px) => ({
    value: px.id,
    label: px.name || px.id,
    help: px.last_fired_time
      ? `Last fired ${px.last_fired_time}`
      : "Never fired — won't optimize",
  }));

  const adSetUrl = adset.ads[0]?.creative.link ?? '';
  const wantsWebsiteField = (dest?.required_user_info ?? []).includes(
    'website_url'
  );

  // The note explains; validateSpec is what marks the field and stops Publish.
  const isPageFallback = isPageFallbackLink(adSetUrl, pageId);
  const missingPrerequisites = (dest?.required_user_info ?? [])
    .filter((key) => {
      if (key === 'website_url') return !adSetUrl.trim() || isPageFallback;
      if (key === 'app_store_url')
        return !String(po.object_store_url ?? '').trim();
      // Answered by the Page, not by the run — and only a definite `false` is an
      // answer. `undefined` means the token could not read the field.
      if (key === 'page_whatsapp') return pageWhatsAppLinked(page) === false;
      return catalog.user_info_present?.[key] === false;
    })
    .map((key) => PREREQUISITE_FIXES[key] ?? `Missing ${key}.`);
  const capped = catalog.bid_strategies_requiring_amount.includes(
    adset.bid_strategy
  );

  const isLifetime =
    budgetMode === 'cbo' ? campaignIsLifetime : adset.lifetime_budget != null;
  const roasGoal = roasGoalOf(catalog);
  const genderValue =
    JSON.stringify(t.genders) === JSON.stringify([1])
      ? 'male'
      : JSON.stringify(t.genders) === JSON.stringify([2])
        ? 'female'
        : 'all';

  const demographicsBlock = (
    <div className="flex flex-col gap-4">
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
    </div>
  );

  return (
    <div className={show === 'ad' ? 'flex h-full min-h-0 w-full flex-1 flex-col overflow-hidden' : 'flex flex-col gap-4'}>
      {/* Ad set settings. The tree nav renders this pane and the ads below as
          separate nodes (`show="settings"` / `show="ad"`); a locked ad set
          ("do it for me", pre-unlock) never reaches this component with
          show="settings" at all — CampaignEditor renders LockedSummary
          instead, so there is nothing to gate on `locks.adset` here anymore. */}
      {show !== 'ad' && (
        <>
      <div className="flex items-center justify-between">
        <TextInput
          label="Ad set name"
          withAsterisk
          placeholder="e.g. Broad Audience - US"
          value={adset.name}
          onChange={(e) => patchAdset({ name: e.currentTarget.value })}
          error={err(`${p}.name`)}
          classNames={selectClassNames}
          className="flex-1"
        />
        {canRemove && (
          <button
            onClick={onRemove}
            className="text-secondary-text/60 mt-5 ml-3 flex h-8 w-8 cursor-pointer items-center justify-center rounded-full hover:bg-red-500/10 hover:text-red-400"
          >
            <Trash2 size={15} />
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {destinations.length > 1 && (
          <Select
            label={
              <InfoLabel
                label="Conversion location"
                help={dest?.help ?? FIELD_HELP.conversion_location}
              />
            }
            placeholder="Select conversion location"
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
          placeholder="Select optimization goal"
          data={toSelectData(optGoals)}
          renderOption={makeOptionRenderer(descsOf(optGoals))}
          value={adset.optimization_goal}
          onChange={(v) => v && onChangeGoal(v)}
          error={err(`${p}.optimization_goal`)}
          classNames={selectClassNames}
          comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
        />
        {/* The way into the Pixel picker below: a Sales/Leads campaign with no
            warm dataset opens on a non-pixel goal (media_detect_pixel /
            _resolve_goal step it down), so the conversion-tracking block never
            renders unless something switches the goal first. Offered only when
            THIS destination actually has a pixel-promoting goal to switch to. */}
        {promotedKind !== 'pixel' && pixelGoal && (
          <button
            type="button"
            onClick={() => onChangeGoal(pixelGoal)}
            className="text-secondary-text hover:text-primary-text -mt-2 flex cursor-pointer items-center self-start text-[12px] md:col-span-2"
          >
            Optimize for conversions instead
          </button>
        )}
        <Select
          label={
            <InfoLabel label="Billing event" help={FIELD_HELP.billing_event} />
          }
          placeholder="Select billing event"
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
                data={[
                  { value: '', label: 'Create a default one for me' },
                  ...[
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
                className="text-secondary-text hover:text-primary-text flex cursor-pointer items-center gap-1 self-start text-[12px]"
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
              placeholder="Select bid strategy"
              data={toSelectData(goalBidStrategies)}
              renderOption={makeOptionRenderer(descsOf(goalBidStrategies))}
              value={adset.bid_strategy}
              onChange={(v) => v && patchAdset({ bid_strategy: v })}
              error={err(`${p}.bid_strategy`)}
              classNames={selectClassNames}
              comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
            />
            {capped && (
              <NumberInput
                label="Bid amount ($)"
                withAsterisk
                placeholder="e.g. 10.00"
                value={centsToDollars(adset.bid_amount)}
                min={0.01}
                decimalScale={2}
                onChange={(v) => patchAdset({ bid_amount: dollarsToCents(v) })}
                error={err(`${p}.bid_amount`)}
                classNames={selectClassNames}
              />
            )}
            {adset.bid_strategy === roasGoal.bid_strategy && (
              <NumberInput
                label="Minimum ROAS"
                withAsterisk
                description="2 means $2 back for every $1 spent."
                placeholder="e.g. 2.0"
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
                error={
                  // Two keys: the server's field_validator reports the whole
                  // `bid_constraints` object, validateSpec names the number.
                  err(`${p}.bid_constraints.roas_average_floor`) ??
                  err(`${p}.bid_constraints`)
                }
                classNames={selectClassNames}
              />
            )}
            <div className="flex flex-col sm:flex-row items-stretch sm:items-start gap-4 md:col-span-2">
              <div className="flex flex-1 flex-col">
                <div className="font-medium! text-xs! text-primary-text/80! mb-2! leading-[1.55]">
                  <InfoLabel
                    label="Ad set budget type"
                    help={FIELD_HELP.budget_type}
                  />
                </div>
                <SegmentedControl
                  fullWidth
                  size="sm"
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
                    { label: 'Daily Budget', value: 'daily' },
                    { label: 'Total Budget', value: 'lifetime' },
                  ]}
                  classNames={segmentedControlClassNames}
                />
                {adset.lifetime_budget != null && (
                  <div className="text-secondary-text/60 text-[11px] mt-1.5">
                    Total budget needs an end date on this ad set (set it under
                    Schedule).
                  </div>
                )}
              </div>
              <NumberInput
                label={
                  adset.lifetime_budget
                    ? 'Total budget ($)'
                    : 'Daily budget ($)'
                }
                placeholder="e.g. 25.00"
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
                className="flex-1"
              />
            </div>
          </>
        )}
      </div>

      {promotedKind === 'pixel' && (
        <div className="border-underline/15 rounded-xl border p-3">
          {/* Grouped and named, because this is where a campaign quietly decides
              what it optimizes toward. Two loose selects in the middle of an
              ad-set panel is a thing nobody reads before publishing. */}
          <div className="text-secondary-text/70 mb-3 text-[11px] font-bold tracking-wide uppercase">
            Conversion tracking
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 md:items-end">
          <Select
            label="Meta Pixel"
            withAsterisk
            data={[
              ...pixelOptions,
              // Only when there is nothing to pick. An empty account used to get
              // a dead 'No pixel found' placeholder and no way forward; an account
              // that already has a dataset should use THAT one, not start a second
              // cold one beside it.
              ...(catalog.create_dataset_value && !catalog.pixel_candidates.length
                ? [{
                    value: catalog.create_dataset_value,
                    label: 'Create one for me',
                  }]
                : []),
            ]}
            value={(po.pixel_id as string) ?? null}
            onChange={(v) =>
              patchAdset({ promoted_object: { ...po, pixel_id: v } })
            }
            placeholder={
              catalog.pixel_candidates.length
                ? 'Select a pixel'
                : 'Create one for me'
            }
            renderOption={makeOptionRenderer(descsOf(pixelOptions))}
            error={err(`${p}.promoted_object.pixel_id`)}
            classNames={selectClassNames}
            comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
          />
          {/* One select, two kinds of answer to the same question. A custom
              conversion is a rule the advertiser already defined over their
              dataset ("URL contains /thank-you"), and for someone with the base
              pixel and no event code it is the only conversion they can actually
              optimize toward. It carries its own event definition, so picking one
              replaces custom_event_type rather than joining it. */}
          <Select
            label="Conversion event"
            withAsterisk
            placeholder="Select an event"
            data={[
              {
                group: 'Standard events',
                items: pixelEventsOf(catalog).map((e) => ({
                  value: e,
                  label: e
                    .replace(/_/g, ' ')
                    .toLowerCase()
                    .replace(/^\w/, (c) => c.toUpperCase()),
                })),
              },
              ...(catalog.custom_conversions?.length
                ? [
                    {
                      group: 'Your custom conversions',
                      items: catalog.custom_conversions.map((cc) => ({
                        value: `cc:${cc.id}`,
                        label: cc.name,
                      })),
                    },
                  ]
                : []),
            ]}
            value={
              po.custom_conversion_id
                ? `cc:${po.custom_conversion_id}`
                : ((po.custom_event_type as string) ?? null)
            }
            onChange={(v) =>
              patchAdset({
                promoted_object: v?.startsWith('cc:')
                  ? {
                      ...po,
                      custom_conversion_id: v.slice(3),
                      custom_event_type: null,
                    }
                  : {
                      ...po,
                      custom_event_type: v,
                      custom_conversion_id: null,
                    },
              })
            }
            error={err(`${p}.promoted_object.custom_event_type`)}
            classNames={selectClassNames}
            comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
          />
          </div>
        </div>
      )}
      {/* Who this ad set reaches and who it leaves out. Sits under conversion
          tracking because the two are one story: the dataset above collects the
          people, and this is where they get advertised to — or excluded, which
          is what stops the campaign selling to customers who already bought. */}
      <AudienceTargetingField
        attached={adset.attached_audience_ids ?? []}
        excluded={adset.excluded_audience_ids ?? []}
        catalog={catalog}
        datasetId={(po.pixel_id as string) || ''}
        onChange={patchAdset}
        error={err(`${p}.attached_audience_ids`) || err(`${p}.excluded_audience_ids`)}
      />
      {promotedKind === 'page' && (
        <div className="border-underline/15 text-secondary-text/70 rounded-xl border border-dashed px-3 py-2.5 text-[12px]">
          {adset.destination_type === 'WHATSAPP'
            ? `Messages go to the WhatsApp number linked to ${page?.name || 'your Facebook Page'}. Change the Page under Campaign to use a different number.`
            : `This optimization goal promotes ${page?.name || 'your Facebook Page'} — change it under Campaign.`}
        </div>
      )}
      {wantsWebsiteField && (
        <TextInput
          label={
            <InfoLabel
              label="Website URL"
              help="Where clicks land. Sets the link on every ad in this ad set; each ad below can still override it."
            />
          }
          withAsterisk
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
      {promotedKind === 'application' && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 md:items-end">
          <TextInput
            label="App store URL"
            withAsterisk
            description="The listing this ad set sends people to."
            placeholder="https://apps.apple.com/app/id…"
            value={(po.object_store_url as string) ?? ''}
            onChange={(e) => {
              const url = e.currentTarget.value;
              patchAdset({ promoted_object: { ...po, object_store_url: url } });
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
      {missingPrerequisites.length > 0 && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-[12px] text-amber-300">
          {missingPrerequisites.join(' ')}
        </div>
      )}

      {/* Schedule */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <DateTimePicker
          label="Start"
          placeholder="Select start date & time"
          valueFormat="MMM D, YYYY h:mm A"
          value={toLocalString(adset.start_time)}
          onChange={(v) =>
            patchAdset({ start_time: fromPicker(v) ?? adset.start_time })
          }
          error={err(`${p}.start_time`)}
          classNames={selectClassNames}
          popoverProps={{
            withinPortal: true,
            zIndex: 1000000,
            classNames: {
              dropdown: 'bg-[#FFFFFF03]! backdrop-blur-[75.9000015258789px]! rounded-[18px]! shadow-[0px_8px_24px_0px_#00000080,0px_-1px_0px_0px_#00000066_inset,0px_1px_0px_0px_#FFFFFF1F_inset]!',
            },
            styles: {
              dropdown: {
                backgroundColor: '#FFFFFF03',
                background: '#FFFFFF03',
              },
            },
          }}
        />
        <DateTimePicker
          label={isLifetime ? 'End' : 'End (optional)'}
          required={isLifetime}
          placeholder="Select end date & time"
          valueFormat="MMM D, YYYY h:mm A"
          value={toLocalString(adset.end_time)}
          onChange={(v) => patchAdset({ end_time: fromPicker(v) })}
          clearable={!isLifetime}
          error={err(`${p}.end_time`)}
          classNames={selectClassNames}
          popoverProps={{
            withinPortal: true,
            zIndex: 1000000,
            classNames: {
              dropdown: 'bg-[#FFFFFF03]! backdrop-blur-[75.9000015258789px]! rounded-[18px]! shadow-[0px_8px_24px_0px_#00000080,0px_-1px_0px_0px_#00000066_inset,0px_1px_0px_0px_#FFFFFF1F_inset]!',
            },
            styles: {
              dropdown: {
                backgroundColor: '#FFFFFF03',
                background: '#FFFFFF03',
              },
            },
          }}
        />
      </div>

      {/* Placements */}
      <PlacementsField
        catalog={catalog}
        targeting={t}
        patchTargeting={patchTargeting}
      />

      {/* Attribution window */}
      {goalRules?.allows_attribution_spec !== false && (
        <AttributionField
          label="Attribution window"
          help={FIELD_HELP.attribution}
          value={(adset.attribution_spec as AttributionWindow[]) ?? []}
          onChange={(v: AttributionWindow[]) =>
            patchAdset({ attribution_spec: v.length ? v : null })
          }
          clickWindows={catalog.attribution.click_windows}
          viewWindows={catalog.attribution.view_windows}
          engagedViewWindows={catalog.attribution.engaged_view_windows}
          defaults={catalog.attribution.default}
          error={err(`${p}.attribution_spec`)}
        />
      )}

      {/* Frequency cap */}
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

      {/* Scheduling. Budget scheduling raises *a budget*, and under a campaign
          budget the ad set has none — the payload strips it — so the window
          belongs on the campaign, where it is now offered. Dayparting stays here
          either way: it restricts when this ad set runs. */}
      {isLifetime ? (
        <DaypartingField
          label="Ad scheduling (dayparting)"
          help={
            catalog.ad_account_timezone
              ? `Run ads only in chosen day/time windows. Times are in your ad account's timezone (${catalog.ad_account_timezone}), not your own. Lifetime budgets only.`
              : "Run ads only in chosen day/time windows. Times are in your ad account's timezone, not your own. Lifetime budgets only."
          }
          value={(adset.adset_schedule as DayPart[]) ?? []}
          onChange={(v: DayPart[]) =>
            patchAdset({ adset_schedule: v.length ? v : null })
          }
          error={err(`${p}.adset_schedule`)}
        />
      ) : budgetMode === 'adset' ? (
        <BudgetScheduleField
          catalog={catalog}
          value={adset.budget_schedule_specs ?? []}
          onChange={(v) =>
            patchAdset({ budget_schedule_specs: v.length ? v : null })
          }
          error={err(`${p}.budget_schedule_specs`)}
        />
      ) : null}

      {/* Advantage+ audience */}
      <AdvantageAudienceField targeting={t} patchTargeting={patchTargeting}>
        {demographicsBlock}
        {/* Detailed targeting is forbidden outright for a special ad category —
            the server rejects a flexible_spec or exclusions on one. Leaving these
            on screen was worse than useless: InterestField AUTOFILLS on mount, so
            a housing/employment plan became unsubmittable over a field the user
            never touched. */}
        {!blocksDemographics && (
          <>
            <InterestField
              targeting={t}
              patchTargeting={patchTargeting}
              blocked={blocksDemographics}
            />
            <ExclusionField targeting={t} patchTargeting={patchTargeting} />
          </>
        )}
      </AdvantageAudienceField>

      {/* Locked geo + audience */}
      {(locks.geo || locks.audience) && (
        <div className="border-primary-text/8 bg-primary-bg/3 flex items-start gap-3 rounded-[14px] border px-3 py-3 backdrop-blur-[103.6px] shadow-[0px_8px_24px_0px_#00000080,0px_1px_0px_0px_#FFFFFF1F_inset]">
          <Lock size={13} className="text-secondary-text/60 mt-0.5" />
          <div className="text-secondary-text/70 text-[12px]">
            <div className="text-primary-text/70 font-bold">
              Location &amp; audience (locked)
            </div>
            {/* "Audience: seed" meant nothing to anyone who had not read the
                builder. Same field, said in the user's words. */}
            {adset.audience_role && AUDIENCE_ROLE_COPY[adset.audience_role] && (
              <>
                <div className="text-primary-text/55 mt-1">
                  Audience: {AUDIENCE_ROLE_COPY[adset.audience_role].label}
                </div>
                <div className="text-primary-text/35">
                  {AUDIENCE_ROLE_COPY[adset.audience_role].help}
                </div>
              </>
            )}
            <div className='text-primary-text/55'>{summarizeGeo(t)}</div>
            <div className="text-primary-text/35 mt-0.5">
              Confirmed earlier on the map — edit there if needed.
            </div>
          </div>
        </div>
      )}
        </>
      )}

      {/* Ads. `adIndex` set (a single ad node picked in the tree) renders just
          that one; otherwise every ad in the set (the old single-pane view,
          unused by the current caller — CampaignEditor always passes an
          adIndex alongside show="ad"). "Add ad" itself lives in the tree nav
          now, under this ad set's node — it needs to select the new ad once
          it's added, which only the nav (owner of the selected node) can do. */}
      {show !== 'settings' && (
        <>
      <div className="flex h-full min-h-0 w-full flex-1 flex-col">
        {(adIndex != null
          ? [[adIndex, adset.ads[adIndex]] as const]
          : adset.ads.map((ad, d) => [d, ad] as const)
        )
          .filter(([, ad]) => !!ad)
          .map(([d, ad]) => (
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
            onAddAds={onAddAd}
            onGenerate={() => onGenerate(d)}
            requiresVideo={goalRules?.media_kind === 'video'}
            objectStoryKind={dest?.object_story_kind}
            allowsExistingPost={dest?.allows_existing_post}
            pageId={pageId}
            pageName={page?.name}
            creativeSource={creativeSource}
            expressMode={locks.campaign && locks.adset}
            label={
              locks.campaign && locks.adset ? `Ad ${d + 1}` : undefined
            }
          />
        ))}
      </div>
        </>
      )}
    </div>
  );
}
