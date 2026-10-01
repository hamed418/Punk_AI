'use client';

/**
 * PreviewPanes — the Preview & Publish body content: a detail column
 * (placements, budget/schedule, the selected ad's name/format, and the Meta
 * Setup & Tracking modal) beside the Meta ad-preview iframe column. Split out
 * of the standalone `WidgetCampaignPreview` widget so the same body can also
 * render inside `CampaignEditor`'s `phase: "preview"` pane — the campaign
 * editor's own shell/nav owns the ad pager there (see `EditorNav`
 * `phase="preview"`); `WidgetCampaignPreview` keeps its own arrows for
 * transcripts still on the legacy `campaign_preview` action type.
 *
 * Selection is fully external: `selectedAdId` decides which ad's preview
 * loads. This component only reads it and fetches/renders — it never changes
 * it, so callers can drive selection from an ad pager, a nav tree, or a
 * fixed single ad, without this component knowing the difference.
 */
import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  ChevronDown,
  Check,
  ExternalLink,
  TriangleAlert,
  EyeIcon,
  Copy,
  Settings,
  ChevronRight,
} from 'lucide-react';
import { Flex, Loader, Menu, Modal } from '@mantine/core';
import type { AdPreview, PendingActionBlock, TrackingMethod } from '@/types/chat';
import { listAdPreviewsAction } from '@/actions/ads.actions';
import { MetaFixItList } from '@/components/MetaFixItCard';
import { TRACKING_PLANE } from '@/constant/trackingPlane';

// Must match GO_LIVE_OPTIONS in backend/app/graph/prompts_registry.py — the
// server resolves the answer by the prefix before the em-dash.
export const SET_LIVE = 'Set it live — start delivering this campaign now';
export const STAY_PAUSED =
  "Leave it paused — I'll switch it on myself in Ads Manager";

export const PLATFORM_LABEL: Record<string, string> = {
  facebook: 'Facebook',
  instagram: 'Instagram',
  audience_network: 'Audience Network',
  messenger: 'Messenger',
  threads: 'Threads',
};

// Currencies Meta gives an offset of 1 — the stored amount is already whole yen,
// not hundredths. Mirrors ZERO_DECIMAL_CURRENCIES in meta_spec/parsing.py; keep
// the two in step. Intl is NOT a substitute: it follows ISO, which puts HUF and
// TWD at two decimals where Meta puts them at zero.
const ZERO_DECIMAL = new Set([
  'CLP',
  'COP',
  'CRC',
  'HUF',
  'ISK',
  'IDR',
  'JPY',
  'KRW',
  'PYG',
  'TWD',
  'VND',
]);

// Meta returns budgets in the account's minor unit. Intl handles the symbol and
// the decimal rules per currency, so nothing here assumes USD.
export const money = (minor: number, currency: string) => {
  const scale = ZERO_DECIMAL.has((currency || '').toUpperCase()) ? 1 : 100;
  const amount = (minor || 0) / scale;
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: currency || 'USD',
    }).format(amount);
  } catch {
    return `${currency} ${amount.toFixed(scale === 1 ? 0 : 2)}`;
  }
};

export const day = (raw?: string) => {
  if (!raw) return null;
  const d = new Date(raw);
  return Number.isNaN(d.getTime())
    ? raw
    : d.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      });
};

// One paste-me box. The setup is worthless if the advertiser cannot get it out
// of the page, and a <pre> full of pixel code is not something anyone retypes.
function CopyBox({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <div className="mt-2">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-secondary-text/70 text-[11px] font-bold tracking-wide uppercase">
          {label}
        </span>
        <button
          type="button"
          onClick={() => {
            navigator.clipboard?.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 1600);
          }}
          className="text-secondary-text/70 hover:text-primary-text flex items-center gap-1 text-[11px]"
        >
          {copied ? <Check size={11} /> : <Copy size={11} />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="border-underline/15 max-h-40 overflow-auto rounded-lg border bg-black/20 p-2 text-[11px] leading-relaxed break-all whitespace-pre-wrap">
        {value}
      </pre>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-underline/15 bg-primary-bg/30 overflow-hidden rounded-2xl border">
      <div className="text-secondary-text/60 border-underline/15 border-b px-3 py-2 text-[11px] tracking-wide uppercase">
        {title}
      </div>
      <div className="divide-underline/10 divide-y">{children}</div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 px-3 py-2.5">
      <span className="text-primary-text text-[12px]">{label}</span>
      {children}
    </div>
  );
}

interface PreviewPanesProps {
  content: PendingActionBlock['content'];
  selectedAdId: string | null;
}

export default function PreviewPanes({ content, selectedAdId }: PreviewPanesProps) {
  const [modalOpened, setModalOpened] = useState(false);
  const [previews, setPreviews] = useState<AdPreview[] | null>(null);
  const [activeFormat, setActiveFormat] = useState<string | null>(null);

  const ads = content.ads ?? [];
  const summary = content.summary ?? {};
  const tracking = content.tracking;
  const audienceNotice = content.audience_notice;
  const remediation = content.remediation ?? [];

  const hasNotices =
    remediation.length > 0 || !!audienceNotice?.dropped || !!tracking;
  const hasActionNeeded =
    remediation.length > 0 ||
    !!audienceNotice?.dropped ||
    (!!tracking &&
      tracking.event_match_quality != null &&
      tracking.event_match_quality < 6) ||
    (!!tracking && !tracking.last_fired_time);
  const selectedAd =
    ads.find((ad) => ad.ad_id === selectedAdId) ?? ads[0] ?? null;

  const detailBadges = ['basic info', 'setup', 'assets'] as const;

  // Reset immediately on ad switch so the previous ad's preview never
  // flashes while the new one loads — render-time adjustment (not inside the
  // fetch effect below: setState synchronously in an effect body is what
  // react-hooks/set-state-in-effect exists to catch), same pattern
  // CampaignEditor uses to re-seed state when its `content` prop changes.
  const [seenAdId, setSeenAdId] = useState(selectedAdId);
  if (selectedAdId !== seenAdId) {
    setSeenAdId(selectedAdId);
    setPreviews(null);
    setActiveFormat(null);
  }

  useEffect(() => {
    if (!selectedAdId) return;
    // `live` guards a fast ad switch — the first response must not overwrite the
    // second's. Same pattern as the editor's template picker.
    let live = true;
    listAdPreviewsAction(selectedAdId)
      // The action swallows its own lookup failures, but the call to it can
      // still reject (transport, auth redirect). Without this the preview pane
      // keeps spinning forever instead of saying there is nothing to show.
      .catch(() => [] as AdPreview[])
      .then((result) => {
        if (!live) return;
        setPreviews(result);
        setActiveFormat(result[0]?.format ?? null);
      });
    return () => {
      live = false;
    };
  }, [selectedAdId]);

  const activeSrc = previews?.find((p) => p.format === activeFormat)?.src;
  const previewOptions = previews ?? [];

  const rows: [string, string | null][] = [
    [
      summary.budget?.type === 'lifetime' ? 'Lifetime budget' : 'Daily budget',
      summary.budget ? money(summary.budget.amount, summary.budget.currency) : null,
    ],
    ['Start date', day(summary.start_date)],
    ['End date', day(summary.end_date) ?? 'Ongoing'],
  ];

  return (
    <div className="grid min-h-0 w-full md:w-198.5 flex-1 gap-0 overflow-y-auto grid-cols-1 xl:grid-cols-[minmax(0,1.05fr)_minmax(290px,0.95fr)]">
      <div className="flex flex-col gap-3.5 px-3 sm:px-4 py-3.5">
        <div className="flex flex-wrap items-center gap-2 py-2">
          {detailBadges.map((badge) => (
            <span
              key={badge}
              className="text-secondary-text/80 flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] font-medium capitalize"
            >
              <Check size={12} className="" />
              {badge}
            </span>
          ))}
        </div>

        <Section title="Placements & platforms">
          {(summary.placements?.length ?? 0) > 0 ? (
            summary.placements!.map((p) => (
              <Row key={p.platform} label={PLATFORM_LABEL[p.platform] || p.platform}>
                <span className="text-secondary-text/70 text-[12px]">
                  {p.positions.join(', ')}
                </span>
              </Row>
            ))
          ) : (
            <p className="text-secondary-text/70 px-3 py-2 text-[12px]">
              No placement details were returned for this campaign.
            </p>
          )}
        </Section>

        <Section title="Budget & schedule">
          {rows.map(([label, value]) =>
            value ? (
              <Row key={label} label={label}>
                <span className="text-primary-text text-[12px] font-medium">
                  {value}
                </span>
              </Row>
            ) : null
          )}
        </Section>

        <Section title="Ad detail">
          {selectedAd ? (
            <>
              <Row label="Name">
                <span className="text-primary-text text-[12px] font-medium">
                  {selectedAd.name}
                </span>
              </Row>
              <Row label="Format">
                <span className="text-primary-text text-[12px] font-medium">
                  {previewOptions.find((p) => p.format === activeFormat)?.label ||
                    'Selected preview'}
                </span>
              </Row>
              <Row label="CTA">
                <span className="text-primary-text text-[12px] font-medium">
                  Preview on the right
                </span>
              </Row>
            </>
          ) : (
            <p className="text-secondary-text/70 px-3 py-2 text-[12px]">
              No ads were published in this campaign.
            </p>
          )}
        </Section>

        {hasNotices && (
          <>
            <div className="">
              <button
                type="button"
                onClick={() => setModalOpened(true)}
                className="border-underline/15 text-secondary-text/90 flex w-full cursor-pointer items-center justify-between rounded-xl border bg-white/5 px-2.5 py-3 text-[13px] font-medium transition-colors hover:bg-white/10"
              >
                <Flex justify={'space-between'} align={'center'} w="100%">
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center gap-2 text-start! text-xs text-nowrap">
                      <Settings size={16} className="text-secondary-text/70" />
                      Meta Setup & Tracking Details
                    </div>

                    {hasActionNeeded && (
                      <div className="flex items-center gap-2 text-amber-300">
                        <TriangleAlert size={16} />
                        <span className="text-xs font-medium tracking-wide uppercase">
                          Action Needed
                        </span>
                      </div>
                    )}
                  </div>
                  <ChevronRight size={20} className="opacity-50" />
                </Flex>
              </button>
            </div>

            <Modal
              opened={modalOpened}
              onClose={() => setModalOpened(false)}
              title={
                <span className="text-primary-text text-[15px] font-semibold">
                  Meta Setup & Tracking Details
                </span>
              }
              centered
              size="lg"
              zIndex={1000000}
              classNames={{
                content:
                  'bg-primary-widget! border-stroke-widget! shadow-widget! light:shadow-lg! rounded-[26px]! border!',
                header: 'bg-transparent! border-b! border-underline/15!',
                body: 'p-0! bg-transparent! max-h-[75vh]! overflow-y-auto! custom-scrollbar!',
                close: 'text-secondary-text hover:bg-white/10 rounded-full transition-colors',
              }}
              styles={{ content: { backdropFilter: 'blur(75.9px)' } }}
            >
              <div className="flex flex-col gap-4 p-5">
                {remediation.length > 0 && (
                  // Everything Meta will not let Punk do on the user's behalf,
                  // gathered from all three places it can be noticed: the
                  // account read at connect, whatever Meta refused during the
                  // publish, and the plan-vs-Page check that catches what Meta
                  // never complains about at all. Above the fold, because this
                  // is the last screen before money moves.
                  <Section title="Needs you in Meta">
                    <div className="px-3 py-2.5">
                      <MetaFixItList fixes={remediation} />
                    </div>
                  </Section>
                )}

                {audienceNotice?.dropped && (
                  // The one thing on this screen the user did not decide: the
                  // audience was built, Meta refused to hold it, and the ads
                  // went out on Advantage+ instead. Last chance to see that
                  // before anything spends.
                  <Section title="Audience">
                    <div className="flex items-start gap-2 px-3 py-2.5 text-[12px] text-amber-300">
                      <TriangleAlert size={13} className="mt-0.5 shrink-0" />
                      <span>
                        {audienceNotice.reason} These ads are running on Meta&apos;s
                        Advantage+ audience inside the same locations.{' '}
                        {audienceNotice.fix}
                      </span>
                    </div>
                  </Section>
                )}

                {tracking && (
                  <Section title="Conversion tracking">
                    <Row label={tracking.pixel_name}>
                      <a
                        href={tracking.events_manager_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-secondary-text/80 hover:text-primary-text flex items-center gap-1 text-[12px] underline"
                      >
                        {tracking.created_by_punk ? 'Finish setup' : 'Open in Meta'}
                        <ExternalLink size={11} />
                      </a>
                    </Row>
                    {/* Which half of this Punk actually touches. The same
                    sentence the settings card carries, repeated on the
                    screen a first-timer actually reads — that card is
                    buried in the profile modal and this is the last thing
                    before money moves. */}
                    <div className="text-secondary-text/70 px-3 py-2.5 text-[12px]">
                      {TRACKING_PLANE[
                        (tracking.tracking_method ?? '') as TrackingMethod | ''
                      ] ?? TRACKING_PLANE['']}
                    </div>
                    {/* What delivery is actually optimized toward — a standard
                    event, or the name of the advertiser's own rule. */}
                    {tracking.conversion_event && (
                      <Row label="Optimizing for">
                        <span className="text-secondary-text/70 text-[12px]">
                          {tracking.conversion_event
                            .replace(/_/g, ' ')
                            .toLowerCase()
                            .replace(/^\w/, (ch) => ch.toUpperCase())}
                        </span>
                      </Row>
                    )}
                    {/* Event Match Quality. A dataset that fires constantly but
                    matches almost nobody optimizes nearly as badly as one
                    that never fires, and this is the last screen before
                    money moves. */}
                    {tracking.event_match_quality != null && (
                      <Row label="Event match quality">
                        <span
                          className={`text-[12px] ${
                            tracking.event_match_quality >= 6
                              ? 'text-secondary-text/70'
                              : 'text-amber-300'
                          }`}
                        >
                          {tracking.event_match_quality.toFixed(1)} / 10
                          {tracking.event_match_quality < 6 &&
                            ' — send an email or phone number with each event to raise it'}
                        </span>
                      </Row>
                    )}
                    {!tracking.last_fired_time && (
                      // The whole reason this section exists. A Pixel that has
                      // never fired still publishes cleanly, then optimizes
                      // toward an event Meta never receives.
                      <div className="flex items-start gap-2 px-3 py-2.5 text-[12px] text-amber-300">
                        <TriangleAlert size={13} className="mt-0.5 shrink-0" />
                        <span>
                          This Pixel hasn&apos;t received any events yet.
                          {tracking.created_by_punk
                            ? ' I created it for you — install'
                            : ' Install'}{' '}
                          it on your site so Meta can measure results. You can
                          still go live; until it fires, delivery is optimizing
                          without conversion data.
                        </span>
                      </div>
                    )}
                    {/* The install helper itself, not directions to a settings
                    page. This is the screen the advertiser is on while the
                    setup is fresh, and the server half of a pixel+server
                    setup died in the walk to Profile › Connections. Only
                    the halves this tracking_method uses are ever sent. */}
                    {!!tracking.setup && (
                      <div className="px-3 py-2.5">
                        {!!tracking.setup.instructions?.length && (
                          <ol className="text-secondary-text/80 mb-1 list-decimal space-y-1 pl-4 text-[12px]">
                            {tracking.setup.instructions.map((step) => (
                              <li key={step}>{step}</li>
                            ))}
                          </ol>
                        )}
                        {!!tracking.setup.pixel_snippet && (
                          <CopyBox label="Website snippet" value={tracking.setup.pixel_snippet} />
                        )}
                        {!!tracking.setup.ingest_url && (
                          <CopyBox label="Server endpoint" value={tracking.setup.ingest_url} />
                        )}
                        {!!tracking.setup.ingest_key && (
                          <CopyBox
                            label="Tracking key — treat as a password"
                            value={tracking.setup.ingest_key}
                          />
                        )}
                        <Link
                          href="/profile"
                          className="text-secondary-text/70 hover:text-primary-text mt-2 inline-flex items-center gap-1 text-[11px]"
                        >
                          Manage this on your Meta connection settings
                          <ExternalLink size={11} />
                        </Link>
                      </div>
                    )}
                  </Section>
                )}
              </div>
            </Modal>
          </>
        )}
      </div>

      <div className="border-t border-white/8 lg:border-t-0 lg:border-l lg:border-white/8">
        <div className="flex items-center justify-between gap-3 border-b border-white/8 px-4 py-3.5">
          <div className="flex min-w-0 items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-white/8">
              <EyeIcon size={14} className="text-secondary-text shrink-0" />
            </div>
            <div className="min-w-0">
              <p className="text-[13px] font-semibold">Ad Preview</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Menu width={240} position="bottom-end" withinPortal zIndex={1000000}>
              <Menu.Target>
                <button
                  type="button"
                  className="border-underline/15 text-secondary-text inline-flex shrink-0 items-center gap-1 rounded-full border bg-white/5 px-2 py-0.5 text-[10px] transition-colors hover:bg-white/8"
                >
                  <span className="max-w-30 truncate text-[14px]!">
                    {previewOptions.find((p) => p.format === activeFormat)?.label ||
                      'Select preview format'}
                  </span>
                  <ChevronDown size={7} className="shrink-0" />
                </button>
              </Menu.Target>
              <Menu.Dropdown>
                {previewOptions.map((p) => (
                  <Menu.Item key={p.format} onClick={() => setActiveFormat(p.format)}>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-[14px]!">{p.label}</span>
                      {p.format === activeFormat && (
                        <Check size={12} className="text-secondary-text" />
                      )}
                    </div>
                  </Menu.Item>
                ))}
              </Menu.Dropdown>
            </Menu>
          </div>
        </div>

        <div className="p-3.5">
          {previews === null ? (
            <div className="flex min-h-120 items-center justify-center rounded-[20px] border border-white/8 bg-black/10">
              <Loader size="sm" />
            </div>
          ) : previews.length === 0 ? (
            <div className="flex min-h-120 items-center justify-center rounded-[20px] border border-white/8 bg-black/10 px-8 text-center">
              <p className="text-secondary-text/80 text-[13px]">
                Meta isn&apos;t rendering a preview for this ad yet. It usually
                appears a minute or two after publishing.
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-3.5">
              {activeSrc && (
                <div className="w-full overflow-hidden rounded-[20px] p-2.5">
                  <iframe
                    key={activeSrc}
                    src={activeSrc}
                    title="Meta ad preview"
                    sandbox="allow-scripts allow-same-origin allow-popups"
                    className="bg-primary-bg! block h-125 w-full overflow-hidden rounded-[18px] p-2"
                    scrolling="no"
                  />
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
