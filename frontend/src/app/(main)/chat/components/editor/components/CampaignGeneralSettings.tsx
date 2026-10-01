import { useEffect } from 'react';
import {
  Select,
  MultiSelect,
  TextInput,
  NumberInput,
  SegmentedControl,
  Checkbox,
  Input,
} from '@mantine/core';
import type {
  CampaignEditorSpec,
  EditorCatalog,
  EditorOption,
  EditorPage,
} from '@/types/chat';
import { InfoLabel, makeOptionRenderer } from '../../forms/InfoLabel';
import {
  selectClassNames,
  multiSelectClassNames,
  segmentedControlClassNames,
  toSelectData,
  descsOf,
  FIELD_HELP,
  countryNames,
  centsToDollars,
  dollarsToCents,
  defaultEnd,
  pageSubtitle,
} from './editorUtils';
import BudgetScheduleField from './BudgetScheduleField';

interface Props {
  spec: CampaignEditorSpec;
  catalog: EditorCatalog;
  errors: Record<string, string>;
  pages: EditorPage[];
  pageId: string | null;
  budgetMode: 'cbo' | 'adset';
  bidStrategies: EditorOption[];
  minDollars: number;
  cboNeedsBidAmount: boolean;
  cboNeedsRoasFloor: boolean;
  roasGoal: { bid_strategy: string; scale: number; min: number; max: number };
  roasFloorToX: (c?: { roas_average_floor: number } | null) => number | string;
  // Not on the spec: how conversions reach Meta is a Punk setting, and
  // CampaignSpec publishes every field it holds. It rides beside the spec.
  trackingMethod: string;
  setTrackingMethod: (next: string) => void;
  update: (fn: (draft: CampaignEditorSpec) => void) => void;
  changePage: (next: string) => void;
  changeObjective: (next: string) => void;
  setSpecialAdCategories: (next: string[]) => void;
  switchBudgetMode: (mode: 'cbo' | 'adset') => void;
  setCampaignBidStrategy: (next: string) => void;
  setEveryAdsetBidAmount: (cents: number | null) => void;
  setEveryAdsetRoasFloor: (x: number | string) => void;
}

export default function CampaignGeneralSettings({
  spec,
  catalog,
  errors,
  pages,
  pageId,
  budgetMode,
  bidStrategies,
  minDollars,
  cboNeedsBidAmount,
  cboNeedsRoasFloor,
  roasGoal,
  roasFloorToX,
  trackingMethod,
  setTrackingMethod,
  update,
  changePage,
  changeObjective,
  setSpecialAdCategories,
  switchBudgetMode,
  setCampaignBidStrategy,
  setEveryAdsetBidAmount,
  setEveryAdsetRoasFloor,
}: Props) {
  const err = (path: string) => errors[path];

  // The same rule the backend uses (_PIXEL_OBJECTIVES): only Sales and Leads
  // deliver against a conversion event, so only they have anything to report.
  const usesConversions =
    spec.objective === 'OUTCOME_SALES' || spec.objective === 'OUTCOME_LEADS';

  // Seed the default rather than faking it in the Select's `value`. The select
  // used to display `trackingMethod || 'pixel_and_server'` while the parent
  // submitted the raw '' it was initialized with — and '' is a member of BOTH
  // _METHODS_WITH_PIXEL and _METHODS_WITH_SERVER on the backend, so an untouched
  // form showed "pixel and server" and then handed the user an ingest key and a
  // "keep this secret" warning they never asked for. pixel_only is the same
  // answer _derived_tracking_method lands on for a pixel-promoted ad set.
  // Non-conversion objectives stay '' on purpose: none of the four methods
  // describes an awareness campaign.
  useEffect(() => {
    if (usesConversions && !trackingMethod) setTrackingMethod('pixel_only');
  }, [usesConversions, trackingMethod, setTrackingMethod]);

  // Every Instagram account this connection can see, plus the empty default that
  // lets Meta use whatever the Page is linked to.
  const igAccounts = [
    { value: '', label: "Use the Page's linked account" },
    ...Array.from(
      new Map(
        pages
          .filter((pg) => pg.instagram?.id)
          .map((pg) => [
            pg.instagram!.id,
            {
              value: pg.instagram!.id,
              label: pg.instagram!.username
                ? `@${pg.instagram!.username}`
                : pg.instagram!.id,
            },
          ])
      ).values()
    ),
  ];

  return (
    <>
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
              Object.fromEntries(pages.map((pg) => [pg.id, pageSubtitle(pg)]))
            )}
            value={pageId ?? null}
            onChange={(v) => v && changePage(v)}
            error={err('page_id')}
            classNames={{
              ...selectClassNames,
              label: 'font-medium! text-xs! text-primary-text!',
              description:
                'text-primary-text/70! opacity-80! text-[11px]! mb-2!',
              input: 'px-2.5 py-3.5 rounded-full!',
            }}
            comboboxProps={{ withinPortal: true, zIndex: 1000001 }}
          />
          {/* Instagram placements default to the chosen Page's linked account,
              but an advertiser running several brands off one Page can point
              them at any Instagram account this connection can see. Hidden when
              there is nothing to choose between. */}
          {(igAccounts.length > 1 || err('instagram_user_id')) && (
            <Select
              mt="sm"
              label={
                <InfoLabel
                  label="Instagram account"
                  help="The identity Instagram placements run as. Defaults to the account linked to the Page above."
                  className="text-primary-text! text-xs! font-medium!"
                />
              }
              data={igAccounts}
              withAsterisk={!!err('instagram_user_id')}
              value={spec.instagram_user_id ?? ''}
              onChange={(v) =>
                update((d) => {
                  d.instagram_user_id = v || null;
                })
              }
              error={err('instagram_user_id')}
              classNames={{
                ...selectClassNames,
                label: 'font-medium! text-xs! text-primary-text!',
                input: 'px-2.5 py-3.5 rounded-full!',
              }}
              comboboxProps={{ withinPortal: true, zIndex: 1000001 }}
            />
          )}
        </div>
      )}
      <div className="mx-2! grid grid-cols-1 items-center! gap-4 md:grid-cols-2">
        <TextInput
          label="Campaign name"
          withAsterisk
          placeholder="e.g. Summer Promo Campaign"
          value={spec.name}
          onChange={(e) => {
            const val = e.currentTarget.value;
            update((d) => {
              d.name = val;
            });
          }}
          error={err('name')}
          classNames={{
            ...selectClassNames,
          }}
        />
        <Select
          label={<InfoLabel label="Objective" help={FIELD_HELP.objective} />}
          placeholder="Select campaign objective"
          data={toSelectData(catalog.objectives)}
          renderOption={makeOptionRenderer(descsOf(catalog.objectives))}
          value={spec.objective}
          onChange={(v) => v && changeObjective(v)}
          error={err('objective')}
          classNames={{
            ...selectClassNames,
          }}
          comboboxProps={{ withinPortal: true, zIndex: 1000001 }}
        />
        <div className="special-ad-categories-multiselect">
          <MultiSelect
            label={
              <InfoLabel
                label="Special ad categories"
                help={FIELD_HELP.special_ad_categories}
              />
            }
            placeholder={
              spec.special_ad_categories && spec.special_ad_categories.length > 0
                ? ''
                : 'Select categories if applicable'
            }
            data={toSelectData(catalog.special_ad_categories)}
            value={spec.special_ad_categories}
            onChange={(v) => setSpecialAdCategories(v)}
            error={err('special_ad_categories')}
            classNames={{
              ...multiSelectClassNames,
              pill: 'bg-white/8! border! border-white/10!',
            }}
            comboboxProps={{ withinPortal: true, zIndex: 1000001 }}
            clearable
          />
        </div>
        {spec.special_ad_categories.length > 0 && (
          <MultiSelect
            label={
              <InfoLabel
                label="Category country"
                help="The country whose special ad category rules apply — normally where your audience is."
              />
            }
            placeholder={
              spec.special_ad_category_country &&
              spec.special_ad_category_country.length > 0
                ? ''
                : 'Select country (e.g. US)'
            }
            data={(catalog.special_ad_category_countries ?? ['US', 'CA']).map(
              (code) => ({
                value: code,
                label: countryNames.of(code) ?? code,
              })
            )}
            withAsterisk
            value={spec.special_ad_category_country ?? []}
            onChange={(v) => update((d) => (d.special_ad_category_country = v))}
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
            size="sm"
            value={budgetMode}
            onChange={(v) => switchBudgetMode(v as 'cbo' | 'adset')}
            data={[
              { label: 'Campaign (CBO)', value: 'cbo' },
              { label: 'Per ad set', value: 'adset' },
            ]}
            classNames={{
              ...segmentedControlClassNames,
              root: `${segmentedControlClassNames.root} w-full min-h-[40px]! h-10! flex items-center!`,
              control: 'border-0! overflow-hidden! cursor-pointer h-full flex items-center!',
              label:
                'text-secondary-text! data-[active]:text-primary-text! data-[active]:font-semibold! text-[11px]! sm:text-[11.5px]! lg:text-[11px]! xl:text-[13px]! py-1.5! xl:py-1! px-1.5! sm:px-2! tracking-tight truncate flex items-center justify-center h-full w-full cursor-pointer',
            }}
          />
        </div>
        {budgetMode === 'cbo' && (
          <>
            <Input.Wrapper
              label={
                <InfoLabel
                  label="Campaign budget type"
                  help={FIELD_HELP.budget_type}
                />
              }
              classNames={selectClassNames}
            >
              <SegmentedControl
                fullWidth
                size="sm"
                value={spec.lifetime_budget ? 'lifetime' : 'daily'}
                onChange={(v) =>
                  update((d) => {
                    if (v === 'lifetime') {
                      d.lifetime_budget =
                        d.daily_budget || catalog.min_budget_cents;
                      d.daily_budget = null;
                      d.adsets.forEach((as) => {
                        if (!as.end_time)
                          as.end_time = defaultEnd(as.start_time);
                      });
                    } else {
                      d.daily_budget =
                        d.lifetime_budget || catalog.min_budget_cents;
                      d.lifetime_budget = null;
                    }
                  })
                }
                data={[
                  { label: 'Daily Budget', value: 'daily' },
                  { label: 'Total Budget', value: 'lifetime' },
                ]}
                classNames={segmentedControlClassNames}
              />
            </Input.Wrapper>
            <NumberInput
              label={
                spec.lifetime_budget
                  ? 'Campaign total budget ($)'
                  : 'Campaign daily budget ($)'
              }
              placeholder="e.g. 50.00"
              value={centsToDollars(spec.lifetime_budget ?? spec.daily_budget)}
              min={minDollars}
              decimalScale={2}
              onChange={(v) =>
                update((d) => {
                  const c = dollarsToCents(v);
                  if (d.lifetime_budget != null) d.lifetime_budget = c;
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
              placeholder="Select bid strategy"
              data={toSelectData(bidStrategies)}
              renderOption={makeOptionRenderer(descsOf(bidStrategies))}
              value={spec.bid_strategy ?? null}
              onChange={(v) => v && setCampaignBidStrategy(v)}
              error={err('bid_strategy')}
              classNames={selectClassNames}
              comboboxProps={{ withinPortal: true, zIndex: 1000001 }}
            />
            {cboNeedsBidAmount && (
              <NumberInput
                label="Cost per result goal ($)"
                withAsterisk
                description="The average you're willing to pay per result."
                placeholder="e.g. 15.00"
                value={centsToDollars(spec.adsets[0]?.bid_amount)}
                min={0.01}
                decimalScale={2}
                onChange={(v) => setEveryAdsetBidAmount(dollarsToCents(v))}
                error={err('adsets[0].bid_amount')}
                classNames={selectClassNames}
              />
            )}
            {cboNeedsRoasFloor && (
              <NumberInput
                label="Minimum ROAS"
                withAsterisk
                description="2 means $2 back for every $1 spent."
                placeholder="e.g. 2.0"
                value={roasFloorToX(spec.adsets[0]?.bid_constraints)}
                min={roasGoal.min / roasGoal.scale}
                max={roasGoal.max / roasGoal.scale}
                decimalScale={2}
                onChange={(v) => setEveryAdsetRoasFloor(v)}
                error={
                  err('adsets[0].bid_constraints.roas_average_floor') ??
                  err('adsets[0].bid_constraints')
                }
                classNames={selectClassNames}
              />
            )}
            {spec.lifetime_budget != null && (
              <div className="text-secondary-text/60 text-[11px] md:col-span-2">
                Lifetime budget needs an end date on every ad set (set it under
                Schedule).
              </div>
            )}
            {/* Budget scheduling raises the DAILY budget over a window, and
                under a campaign budget the campaign is what holds it — an ad set
                carries none, so the window had nowhere to apply. */}
            {spec.daily_budget != null && (
              <div className="md:col-span-2">
                <BudgetScheduleField
                  catalog={catalog}
                  value={spec.budget_schedule_specs ?? []}
                  onChange={(v) =>
                    update((d) => {
                      d.budget_schedule_specs = v.length ? v : null;
                    })
                  }
                  error={err('budget_schedule_specs')}
                />
              </div>
            )}
          </>
        )}
        {/* Campaign-level, unlike the dataset and the event, which are per ad
            set. Only shown when the plan actually optimizes toward a conversion —
            an awareness campaign has nothing to report back. */}
        {!!catalog.tracking_methods?.length && usesConversions && (
          <Select
            className="md:col-span-2"
            label={
              <InfoLabel
                label="How your conversions reach Meta"
                help="Decides what you get handed to install: a website snippet, a server endpoint and key, or neither. You can change it later on your Meta connection settings."
              />
            }
            data={catalog.tracking_methods.map((m) => ({
              value: m.value,
              label: m.label,
            }))}
            value={trackingMethod}
            onChange={(v) => setTrackingMethod(v || '')}
            classNames={selectClassNames}
            comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
          />
        )}
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
            onChange={(e) => {
              const checked = e.currentTarget.checked;
              update((d) => {
                d.is_adset_budget_sharing_enabled = checked;
              });
            }}
            error={err('is_adset_budget_sharing_enabled')}
            classNames={{
              label: 'text-primary-text! text-[13px]! cursor-pointer',
            }}
          />
        )}
      </div>
    </>
  );
}
