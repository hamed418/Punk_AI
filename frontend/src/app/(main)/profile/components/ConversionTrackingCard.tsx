'use client';

import { useEffect, useState } from 'react';
import {
  Box,
  Button,
  CopyButton,
  Loader,
  Select,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Check, Copy, ExternalLink, RefreshCw } from 'lucide-react';
import {
  createCustomConversionAction,
  rotateTrackingKeyAction,
  setTrackingDatasetAction,
  setTrackingMethodAction,
  setTrackingTokenAction,
  trackingDatasetsAction,
  trackingHealthAction,
  trackingSnippetAction,
} from '@/actions/tracking.actions';
import { MetaFixItList } from '@/components/MetaFixItCard';
import { TRACKING_PLANE } from '@/constant/trackingPlane';
import type {
  TrackingDatasets,
  TrackingHealth,
  TrackingMethod,
  TrackingSnippet,
} from '@/types/chat';

// Mirrors TRACKING_METHODS in the backend catalog, ordered the same way — the
// recommended answer first. Each label says where the conversion data actually
// travels, because that is the part of this choice nothing else in the product
// tells them. Values are single-sourced server-side by TRACKING_METHOD_VALUES;
// only the copy lives here, and the settings card wants different words from the
// intake form.
const METHOD_OPTIONS: { value: TrackingMethod; label: string }[] = [
  { value: 'pixel_only', label: 'Website pixel only — nothing reaches Punk' },
  {
    value: 'pixel_and_server',
    label: 'Pixel + server events — your server posts through Punk',
  },
  {
    value: 'lead_forms',
    label: 'Instant form leads — Meta pushes leads to Punk',
  },
  { value: 'offline_crm', label: 'Offline / CRM sales — posted through Punk' },
];

// Methods whose conversions travel through Punk. Switching away from one stops
// the ingest endpoint accepting them, which breaks a live integration — so the
// switch asks first rather than finding out in the customer's checkout.
const SERVER_METHODS: TrackingMethod[] = [
  'pixel_and_server',
  'lead_forms',
  'offline_crm',
];

// One dataset as the two pickers show it. A dataset nobody ever installed is
// worth saying out loud — it is the difference between a working setup and one
// that will never receive an event.
const datasetOptions = (d: TrackingDatasets | null) =>
  (d?.datasets ?? []).map((set) => ({
    value: set.id,
    label:
      (set.name || 'Unnamed') + (set.last_fired_time ? '' : ' — never fired'),
  }));

/**
 * Conversion tracking for the connected Meta account.
 *
 * Two halves, and the point of showing them together is that the second is
 * invisible otherwise: the browser pixel reports what the visitor's browser is
 * willing to report, and the server endpoint reports what actually happened. An
 * advertiser whose dataset has never fired is optimizing blind, and until this
 * card existed nothing in Punk said so outside the publish gate.
 *
 * The dataset is theirs, in their own Meta business. The ingest key is a
 * password: anyone holding it can report conversions to that dataset.
 */
export default function ConversionTrackingCard({
  className,
}: {
  className?: string;
} = {}) {
  const [health, setHealth] = useState<TrackingHealth | null>(null);
  const [snippet, setSnippet] = useState<TrackingSnippet | null>(null);
  const [loading, setLoading] = useState(true);
  const [showSetup, setShowSetup] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [rechecking, setRechecking] = useState(false);
  const [switching, setSwitching] = useState(false);
  // Never populated from the server — the token is write-only, so the field
  // starts empty and `tokenSet` is all the UI ever learns about it.
  const [token, setToken] = useState('');
  const [tokenSet, setTokenSet] = useState(false);
  const [savingToken, setSavingToken] = useState(false);
  const [datasets, setDatasets] = useState<TrackingDatasets | null>(null);
  const [attaching, setAttaching] = useState(false);

  useEffect(() => {
    let live = true;
    Promise.all([
      trackingHealthAction(),
      trackingSnippetAction(),
      trackingDatasetsAction(),
    ])
      .then(([h, s, d]) => {
        if (!live) return;
        setHealth(h);
        setSnippet(s);
        setDatasets(d);
      })
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, []);

  const saveToken = async () => {
    setSavingToken(true);
    try {
      setTokenSet(await setTrackingTokenAction(token));
      setToken('');
      // The token is what server events authenticate with, so whether it works
      // is a health question — re-read it rather than claiming success.
      setHealth(await trackingHealthAction());
    } finally {
      setSavingToken(false);
    }
  };

  // "I've done it" on a fix-it card. Only the health read changes when someone
  // installs the pixel or mints a system user token — the snippet is the same
  // either way, so this re-reads the half that can have moved.
  const recheck = async () => {
    setRechecking(true);
    try {
      setHealth(await trackingHealthAction());
    } finally {
      setRechecking(false);
    }
  };

  // The snippet arrives naming the account's own conversion event. Picking a
  // different one re-reads it rather than string-editing the snippet here: the
  // eventID derivation and the server example have to move with it, and those
  // live on the server.
  // "Define a conversion from a URL" — the repair for the setup that breaks most
  // often: the base pixel is installed site-wide so PageView arrives, no event
  // code was ever added to the thank-you page, and the campaign is optimizing
  // toward an event that will never fire. A URL rule turns the PageViews Meta
  // already receives into the conversion, with no change to their site at all.
  const [ruleUrl, setRuleUrl] = useState('');
  const [ruleName, setRuleName] = useState('');
  const [ruleBusy, setRuleBusy] = useState(false);
  const [ruleResult, setRuleResult] = useState('');

  const createRule = async () => {
    setRuleBusy(true);
    setRuleResult('');
    const created = await createCustomConversionAction({
      name: ruleName.trim() || `${snippet?.event_name || 'Conversion'} page`,
      url_contains: ruleUrl.trim(),
      custom_event_type: snippet?.event_name
        ? snippet.event_name.replace(/([a-z])([A-Z])/g, '$1_$2').toUpperCase()
        : 'PURCHASE',
    });
    setRuleBusy(false);
    if ('error' in created) {
      setRuleResult(created.error);
      return;
    }
    setRuleUrl('');
    setRuleName('');
    setRuleResult(
      `Created "${created.name}". Pick it as the conversion event in your campaign plan.`
    );
  };

  const pickEvent = async (name: string | null) => {
    if (!name || name === snippet?.event_name) return;
    setSwitching(true);
    try {
      const next = await trackingSnippetAction(name);
      if (next) setSnippet(next);
    } finally {
      setSwitching(false);
    }
  };

  // Attaching a dataset changes what every other read means — health gains its
  // stats and fix-it cards, the snippet gains the id it prints into the pixel
  // code — so both are re-read rather than patched locally.
  const attach = async (datasetId: string | null) => {
    if (!datasetId || datasetId === datasets?.selected) return;
    setAttaching(true);
    try {
      await setTrackingDatasetAction(datasetId);
      const [h, s, d] = await Promise.all([
        trackingHealthAction(),
        trackingSnippetAction(),
        trackingDatasetsAction(),
      ]);
      setHealth(h);
      setSnippet(s);
      setDatasets(d);
    } finally {
      setAttaching(false);
    }
  };

  // The switch pixel_only's own instructions promise and nothing could deliver.
  // Which blocks the server returns changes entirely with the method — key,
  // endpoint, example, snippet — so this re-reads instead of editing anything
  // here, the same rule pickEvent already follows.
  const pickMethod = async (method: string | null) => {
    if (!method || method === snippet?.tracking_method) return;
    // The backend refuses server events once the method has no server half, so a
    // switch away from one is not cosmetic — whatever is posting conversions
    // today starts getting 409s. Only asked when something actually is: an
    // account that never sent a server event has nothing to break.
    const leavingServer =
      SERVER_METHODS.includes(snippet?.tracking_method as TrackingMethod) &&
      !SERVER_METHODS.includes(method as TrackingMethod);
    if (leavingServer && health?.server_events_seen) {
      const ok = window.confirm(
        'Your server is currently sending conversions to Punk. Switching to ' +
          'pixel-only stops us accepting them, and those conversions will no ' +
          'longer reach Meta until you switch back or post to Meta directly. ' +
          'Your tracking key stays valid either way.\n\nSwitch anyway?'
      );
      if (!ok) return;
    }
    // Meta deduplicates by event_id inside ONE sender's id namespace and never
    // across two. A store already running Meta's Shopify, WooCommerce or
    // BigCommerce app has its own pixel+server pair firing at this same dataset
    // under that platform's ids; adding ours makes two conversions per real
    // sale, a ROAS that reads about double, and bidding that optimizes on the
    // inflated number. Nothing detects it — fetch_dataset_event_stats returns
    // one total per event name with no source split — so this asks at the only
    // deterministic moment there is. Phrased as a statement rather than a
    // question: "does your store already send events? [OK] [Cancel]" is
    // genuinely ambiguous on a two-button native dialog.
    if (method === 'pixel_and_server') {
      const ok = window.confirm(
        'Only turn this on if nothing else is already sending conversions to ' +
          'this dataset.\n\n' +
          "If your store runs Shopify, WooCommerce or BigCommerce with Meta's " +
          'own app or sales channel, that app is already sending the server ' +
          'half. Running both counts every purchase twice — Meta reports two ' +
          'conversions per sale and your ROAS reads about double what it is.' +
          '\n\nCancel and stay where you are if that is you.'
      );
      if (!ok) return;
    }
    setSwitching(true);
    try {
      await setTrackingMethodAction(method as TrackingMethod);
      const [h, s] = await Promise.all([
        trackingHealthAction(),
        trackingSnippetAction(),
      ]);
      setHealth(h);
      setSnippet(s);
    } finally {
      setSwitching(false);
    }
  };

  const rotate = async () => {
    setRotating(true);
    try {
      const key = await rotateTrackingKeyAction();
      setSnippet((prev) => (prev ? { ...prev, ingest_key: key } : prev));
    } finally {
      setRotating(false);
    }
  };

  if (loading)
    return (
      <Box className="flex items-center justify-center gap-2 px-4 py-3 text-sm text-[#FAF9F599]">
        <Loader size="xs" /> Loading conversion tracking...
      </Box>
    );

  // Nothing resolved yet is a normal state, not an error: the dataset is chosen
  // when a conversion campaign is built.
  // No dataset is a normal state — one is resolved when a conversion campaign is
  // built. It used to dead-end here in prose, including for accounts whose leads
  // Meta is actively pushing at us and being dropped for want of a destination, so
  // the picker and any fix-it card belong on this branch too.
  if (!health || health.status === 'no_dataset')
    return (
      <Box className={className ?? 'px-4 pb-4'}>
        <Text fw={700} fz={10} className="mb-2 tracking-wider text-[#FAF9F54D]">
          CONVERSION TRACKING
        </Text>
        <Box className="flex flex-col gap-2">
          <Text fz={12} className="text-[#FAF9F54D]">
            No dataset attached yet. Build a Sales or Leads campaign and Punk
            picks one of your Meta datasets — or attach one here.
          </Text>

          {!!health?.remediation?.length && (
            <MetaFixItList
              fixes={health.remediation}
              retrying={rechecking}
              onRetry={recheck}
            />
          )}

          {datasets?.datasets.length ? (
            <Select
              size="xs"
              label="Your Meta datasets"
              description="Read from your ad account. Create one in Events Manager and it appears here."
              data={datasetOptions(datasets)}
              value={datasets.selected || null}
              onChange={attach}
              disabled={attaching}
              searchable
              className="w-full max-w-[320px]"
              comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
            />
          ) : (
            <Text fz={11} className="text-[#FAF9F54D]">
              This ad account has no datasets. Create one in Events Manager,
              then reload this page.
            </Text>
          )}
        </Box>
      </Box>
    );

  const emq = health.event_match_quality;

  return (
    <Box className={className ?? 'px-4 pb-4'}>
      <Text fw={700} fz={10} className="mb-2! tracking-wider text-[#FAF9F54D]">
        CONVERSION TRACKING
      </Text>

      <Box className="border-underline/15 flex flex-col gap-2 rounded-xl border px-3 py-2.5">
        <Box className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center sm:gap-3">
          <Box className="flex flex-col">
            <Text fz={13} fw={500} className="text-primary-text leading-tight">
              {health.dataset_name || 'Your dataset'}
            </Text>
            <Text fz={11} className="mt-0.5 leading-tight text-[#FAF9F54D]">
              {health.dataset_id}
              {health.business_id ? ` · business ${health.business_id}` : ''}
            </Text>
          </Box>
          <a
            href={health.events_manager_url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 self-start text-[12px] text-[#FAF9F54D] underline hover:text-white sm:self-auto"
          >
            Events Manager
            <ExternalLink size={11} />
          </a>
        </Box>

        {/* Which half of this Punk actually touches. Nothing in the product
            said so, and the answer differs per method — for pixel_only, the
            express default, none of it passes through Punk at all. Read off
            health rather than the snippet: the method Select lives behind "Show
            setup", and this sentence has to be true on the collapsed card.
            Above the fix-its because it holds whether or not anything is broken
            — below them it would jump position with account health. */}
        <Text fz={12} className="text-[#FAF9F54D]">
          {TRACKING_PLANE[health.tracking_method ?? ''] ?? TRACKING_PLANE['']}
        </Text>

        {/* Replaces the one-line warnings that used to sit here. Both said what
            was wrong and neither said what to do about it — an expired token
            needs a system user token minted in Business settings, not a
            reconnect that expires again in sixty days. */}
        <MetaFixItList
          fixes={health.remediation}
          retrying={rechecking}
          onRetry={recheck}
        />

        {health.last_fired_time && (
          <Text fz={12} className="text-[#FAF9F54D]">
            Last event {new Date(health.last_fired_time).toLocaleString()}
            {health.server_events_seen ? ' · server events enabled' : ''}
          </Text>
        )}

        {!!health.events?.length && (
          <Text fz={12} className="text-[#FAF9F54D]">
            Last 7 days:{' '}
            {health.events
              .slice(0, 4)
              .map((e) => `${e.name} ${e.count.toLocaleString()}`)
              .join(' · ')}
          </Text>
        )}

        {emq != null && (
          <Text
            fz={12}
            className={emq >= 6 ? 'text-[#FAF9F54D]' : 'text-amber-300'}
          >
            Event match quality {emq.toFixed(1)} / 10
            {emq < 6 &&
              ' — send a hashed email or phone with each conversion to raise it'}
          </Text>
        )}

        <Button
          variant=""
          size="compact-xs"
          className="w-fit cursor-pointer"
          onClick={() => setShowSetup((v) => !v)}
        >
          {showSetup ? 'Hide setup' : 'Show setup'}
        </Button>

        {showSetup && snippet && (
          <Box className="flex flex-col gap-3 pt-1">
            <Select
              size="xs"
              label="Conversion event"
              description="Defaults to what your campaigns optimize for. The pixel and your server must send the same name."
              data={snippet.event_names}
              value={snippet.event_name}
              onChange={pickEvent}
              disabled={switching}
              searchable
              allowDeselect={false}
              className="w-full max-w-full sm:max-w-65"
              comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
            />

            {/* No event code on the site? Define the conversion from the URL of
                the page that confirms it. Meta counts a PageView on that page
                as the conversion, so nothing has to be installed. */}
            <Box className="border-underline/15 flex flex-col gap-2 rounded-lg border p-3">
              <Text size="xs" fw={600}>
                No event code on your site?
              </Text>
              <Text size="xs" c="dimmed">
                Name the page people land on after converting. Meta will count a
                visit to it as a conversion — nothing to install.
              </Text>
              <TextInput
                size="xs"
                label="Page URL contains"
                placeholder="/thank-you"
                value={ruleUrl}
                onChange={(e) => setRuleUrl(e.currentTarget.value)}
                className="w-full max-w-full sm:max-w-65"
              />
              <TextInput
                size="xs"
                label="Name it"
                placeholder="Order confirmed"
                value={ruleName}
                onChange={(e) => setRuleName(e.currentTarget.value)}
                className="w-full max-w-full sm:max-w-65"
              />
              <Button
                size="compact-xs"
                className="w-fit cursor-pointer"
                loading={ruleBusy}
                disabled={!ruleUrl.trim()}
                onClick={createRule}
              >
                Create conversion
              </Button>
              {ruleResult && (
                <Text size="xs" c="dimmed">
                  {ruleResult}
                </Text>
              )}
            </Box>

            <Select
              size="xs"
              label="Change how conversions reach Meta"
              description="Changes what you need to install. Switching does not invalidate your tracking key."
              data={METHOD_OPTIONS}
              value={snippet.tracking_method || null}
              onChange={pickMethod}
              disabled={switching}
              allowDeselect={false}
              className="w-full max-w-full sm:max-w-65"
              comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
            />

            {!!datasets?.datasets.length && (
              <Select
                size="xs"
                label="Dataset"
                description="Where conversions are reported. Only datasets this ad account can write to."
                data={datasetOptions(datasets)}
                value={datasets.selected || null}
                onChange={attach}
                disabled={attaching}
                searchable
                allowDeselect={false}
                className="w-full max-w-full sm:max-w-[320px]"
                comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
              />
            )}

            {snippet.instructions.map((line) => (
              <Text key={line} fz={12} className="text-[#FAF9F54D]">
                • {line}
              </Text>
            ))}

            {/* The server returns only what this account's tracking_method
                uses — a CRM setup gets no browser snippet, a pixel-only setup no
                key — so an empty string means "not part of this setup" rather
                than "failed to load". */}
            {!!snippet.pixel_snippet && (
              <SetupBlock label="Pixel snippet" value={snippet.pixel_snippet} />
            )}
            {!!snippet.ingest_url && (
              <SetupBlock label="Server endpoint" value={snippet.ingest_url} />
            )}
            {!!snippet.ingest_key && (
              <SetupBlock
                label="Tracking key (keep it secret)"
                value={snippet.ingest_key}
              />
            )}
            {!!snippet.server_example && (
              <SetupBlock
                label="Example request — through Punk"
                value={snippet.server_example}
              />
            )}
            {/* The same conversion with Punk taken out of the path. Shown beside
                the one above rather than buried: routing through us is a
                convenience, and an advertiser who would rather we never saw their
                customers' details should be able to see exactly what to send. */}
            {!!snippet.server_direct_example && (
              <SetupBlock
                label="Or post straight to Meta — Punk never sees it"
                value={snippet.server_direct_example}
              />
            )}
            <Text fz={11} className="text-[#FAF9F54D]">
              What Punk keeps: the shape of each conversion it forwards — event
              name, value, and whether Meta accepted it. Never who made it.
              Emails and phone numbers are hashed on the way out and no copy is
              stored.
            </Text>

            {/* The other half of tracking_token_expired. That fix-it card tells
                the user to mint a system user token in their own Business
                Settings, and until now there was nowhere to put it — so server
                events kept riding an OAuth token that expires. */}
            {!!snippet.ingest_url && (
              <Box className="flex flex-col gap-1">
                <TextInput
                  size="xs"
                  type="password"
                  label="System user token (optional)"
                  description="Generate one in your own Meta Business Settings. Without it, server events use your login's token, which expires. Leave blank to clear."
                  placeholder={
                    tokenSet ? '\u2022'.repeat(24) : 'Paste your token'
                  }
                  value={token}
                  onChange={(e) => setToken(e.currentTarget.value)}
                  className="w-full max-w-full sm:max-w-105"
                />
                <Button
                  variant="subtle"
                  size="compact-xs"
                  className="w-fit cursor-pointer"
                  loading={savingToken}
                  onClick={saveToken}
                >
                  {token.trim() ? 'Save token' : 'Clear token'}
                </Button>
              </Box>
            )}

            <Tooltip
              label="Breaks whatever is posting conversions today until you install the new key"
              multiline
              w={260}
              zIndex={1000000}
            >
              <Button
                variant="subtle"
                color="red"
                size="compact-xs"
                className="w-fit cursor-pointer"
                loading={rotating}
                leftSection={<RefreshCw size={12} />}
                onClick={rotate}
              >
                Rotate key
              </Button>
            </Tooltip>
          </Box>
        )}
      </Box>
    </Box>
  );
}

function SetupBlock({ label, value }: { label: string; value: string }) {
  return (
    <Box className="flex flex-col gap-1">
      <Box className="flex items-center justify-between gap-2">
        <Text fz={11} className="tracking-wider text-[#FAF9F54D]">
          {label}
        </Text>
        <CopyButton value={value}>
          {({ copied, copy }) => (
            <Button
              variant="subtle"
              size="compact-xs"
              className="cursor-pointer"
              onClick={copy}
              leftSection={copied ? <Check size={12} /> : <Copy size={12} />}
            >
              {copied ? 'Copied' : 'Copy'}
            </Button>
          )}
        </CopyButton>
      </Box>
      <pre className="border-underline/15 text-secondary-text/80 max-h-40 overflow-auto rounded-lg border px-2 py-1.5 text-[11px] whitespace-pre-wrap">
        {value}
      </pre>
    </Box>
  );
}
