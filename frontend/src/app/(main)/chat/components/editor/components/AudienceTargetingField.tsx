'use client';

import { useMemo, useState } from 'react';
import { Button, MultiSelect, Modal, NumberInput, Select, TextInput, Textarea } from '@mantine/core';
import { Plus } from 'lucide-react';
import type { EditorAudience, EditorCatalog } from '@/types/chat';
import {
  addAudienceUsersAction,
  createAudienceAction,
} from '@/actions/ads.actions';
import { InfoLabel } from '../../forms/InfoLabel';
import { selectClassNames } from './editorUtils';

interface Props {
  attached: string[];
  excluded: string[];
  catalog: EditorCatalog;
  // The dataset this ad set optimizes against. An audience is built from one
  // dataset's events, so with none resolved there is nothing to build from —
  // the picker still lists what already exists.
  datasetId: string;
  onChange: (patch: {
    attached_audience_ids?: string[];
    excluded_audience_ids?: string[];
  }) => void;
  error?: string;
}

/** "1,234 people" / "" when Meta has not counted yet. */
function sizeLabel(a: EditorAudience): string {
  if (a.size === null || a.size === undefined) return '';
  return `${a.size.toLocaleString()} people`;
}

/**
 * Audience targeting for one ad set: who to reach, and who to leave out.
 *
 * This is the other end of conversion tracking. The pixel and the Conversions
 * API fill a dataset; without these two controls nothing could advertise to the
 * people in it, and no ad set could exclude the customers who already bought —
 * so prospecting kept being sold to people who had converted last week.
 *
 * An audience Meta will not deliver is still listed rather than hidden: the user
 * made it, and a list their own audience vanished from reads as a bug. It says
 * why instead, and cannot be picked.
 */
export default function AudienceTargetingField({
  attached,
  excluded,
  catalog,
  datasetId,
  onChange,
  error,
}: Props) {
  const [audiences, setAudiences] = useState<EditorAudience[]>(
    catalog.audience_candidates ?? []
  );
  const [building, setBuilding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState('');

  // New-audience form.
  const [name, setName] = useState('');
  const [event, setEvent] = useState<string>('');
  const [days, setDays] = useState<number>(180);
  const [list, setList] = useState('');

  const options = useMemo(
    () =>
      audiences.map((a) => {
        const parts = [a.subtype, sizeLabel(a)].filter(Boolean);
        return {
          value: a.id,
          label: parts.length ? `${a.name} — ${parts.join(' · ')}` : a.name,
          // Meta's own verdict. Selecting one of these publishes an ad set that
          // does not deliver, which surfaces days later as a spend problem.
          disabled: a.usable === false,
        };
      }),
    [audiences]
  );

  const unusable = audiences.filter((a) => a.usable === false);

  const build = async () => {
    setBusy(true);
    setFailure('');
    const created = await createAudienceAction({
      name: name.trim(),
      dataset_id: datasetId,
      event_name: event,
      retention_days: days,
    });
    if ('error' in created) {
      setFailure(created.error);
      setBusy(false);
      return;
    }

    // A pasted customer list, if there is one. Emails only — one column keeps
    // the parse honest, and email is the identifier Meta matches best.
    const emails = list
      .split(/[\s,;]+/)
      .map((e) => e.trim())
      .filter((e) => e.includes('@'));
    if (emails.length) {
      const uploaded = await addAudienceUsersAction(
        created.id,
        ['EMAIL'],
        emails.map((e) => [e])
      );
      if ('error' in uploaded) {
        // The audience exists; only the list failed. Say exactly that rather
        // than leaving the user unsure which half happened.
        setFailure(`Audience created, but the list did not upload: ${uploaded.error}`);
      }
    }

    setAudiences((prev) => [created, ...prev.filter((a) => a.id !== created.id)]);
    setBusy(false);
    setBuilding(false);
    setName('');
    setList('');
  };

  return (
    <div className="border-underline/15 rounded-xl border p-3">
      <div className="text-secondary-text/70 mb-3 text-[11px] font-bold tracking-wide uppercase">
        Audience
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <MultiSelect
          label={
            <InfoLabel
              label="Reach these people"
              help="Saved audiences to advertise to — website visitors, a customer list, a lookalike. Leave empty to use the location and interest targeting below on its own."
            />
          }
          data={options}
          value={attached}
          onChange={(v) => onChange({ attached_audience_ids: v })}
          placeholder={options.length ? 'Everyone in your targeting' : 'No saved audiences yet'}
          searchable
          clearable
          error={error}
          classNames={selectClassNames}
          comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
        />
        <MultiSelect
          label={
            <InfoLabel
              label="Leave these people out"
              help="Nobody in these audiences sees this ad set. Excluding people who already converted is what stops you paying twice for the same customer."
            />
          }
          data={options}
          value={excluded}
          onChange={(v) => onChange({ excluded_audience_ids: v })}
          placeholder="Nobody excluded"
          searchable
          clearable
          classNames={selectClassNames}
          comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button
          size="xs"
          variant="light"
          leftSection={<Plus size={14} />}
          disabled={!datasetId}
          onClick={() => setBuilding(true)}
        >
          Build one from my data
        </Button>
        {!datasetId && (
          <span className="text-secondary-text/60 text-[11px]">
            Pick a Meta Pixel above first — an audience is built from its events.
          </span>
        )}
      </div>

      {unusable.length > 0 && (
        <div className="text-secondary-text/60 mt-2 text-[11px]">
          {unusable.length === 1
            ? `${unusable[0].name} can't be used: ${unusable[0].status || 'Meta says it is not ready'}.`
            : `${unusable.length} of your audiences can't be used yet — Meta lists them as too small or still building.`}
        </div>
      )}

      <Modal
        opened={building}
        onClose={() => setBuilding(false)}
        title="Build an audience"
        centered
        zIndex={1000001}
      >
        <div className="flex flex-col gap-4">
          <div className="text-secondary-text/70 text-[12px]">
            Meta builds this from the people your dataset has already seen. It
            fills up as events arrive, so a brand-new one starts empty.
          </div>
          <TextInput
            label="Name"
            placeholder="Website visitors — 180 days"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            classNames={selectClassNames}
          />
          <Select
            label={
              <InfoLabel
                label="Who goes in"
                help="Everyone the dataset saw, or only the people who triggered one event. The event version is how you build the list of people who already converted — the one worth excluding."
              />
            }
            data={[
              { value: '', label: 'Everyone who visited' },
              ...(catalog.pixel_events ?? []).map((e) => ({
                value: e,
                label: `People who triggered ${e}`,
              })),
            ]}
            value={event}
            onChange={(v) => setEvent(v ?? '')}
            classNames={selectClassNames}
            comboboxProps={{ withinPortal: true, zIndex: 1000002 }}
          />
          <NumberInput
            label={
              <InfoLabel
                label="Look back how many days"
                help="How recently someone had to visit to stay in the audience. Longer keeps more people; shorter keeps warmer ones. Meta's maximum is 365."
              />
            }
            min={1}
            max={365}
            value={days}
            onChange={(v) => setDays(Number(v) || 180)}
            classNames={selectClassNames}
          />
          <Textarea
            label={
              <InfoLabel
                label="Add a customer list (optional)"
                help="Paste email addresses to add your own customers to this audience. They are hashed before they reach Meta and are never stored."
              />
            }
            placeholder="ada@example.com, grace@example.com"
            autosize
            minRows={2}
            maxRows={6}
            value={list}
            onChange={(e) => setList(e.currentTarget.value)}
            classNames={selectClassNames}
          />
          {failure && (
            <div className="text-[12px] text-red-400">{failure}</div>
          )}
          <div className="flex justify-end gap-2">
            <Button size="xs" variant="subtle" onClick={() => setBuilding(false)}>
              Cancel
            </Button>
            <Button
              size="xs"
              loading={busy}
              disabled={!name.trim() || !datasetId}
              onClick={build}
            >
              Build it
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
