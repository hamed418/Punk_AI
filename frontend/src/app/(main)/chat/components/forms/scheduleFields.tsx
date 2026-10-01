'use client'

// Shared ad-set scheduling / attribution field editors.
// Extracted from DynamicForm so both the intake DynamicForm and the bespoke
// CampaignEditor render the same controls against the same wire shapes:
//   DayPart          → AdSetSpec.adset_schedule  (DayPartSpec)
//   AttributionWindow→ AdSetSpec.attribution_spec (AttributionWindow)

import { Text } from '@mantine/core'
import PrimarySelect from '@/components/PrimarySelect'
import { InfoLabel } from './InfoLabel'

// ── dayparting ──────────────────────────────────────────────────────────────

export type DayPart = { days: number[]; start_minute: number; end_minute: number }

const DAYS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']

export function minutesToHHMM(m: number): string {
  const h = Math.floor(m / 60)
  const min = m % 60
  return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`
}
export function hhmmToMinutes(v: string): number {
  const [h, m] = v.split(':').map((x) => parseInt(x, 10) || 0)
  return h * 60 + m
}

export function DaypartingField({
  label,
  help,
  value,
  onChange,
  error,
}: {
  label: string
  help?: string
  value: DayPart[]
  onChange: (v: DayPart[]) => void
  error?: string
}) {
  const rows = value.length ? value : []
  const update = (i: number, patch: Partial<DayPart>) => {
    const next = rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r))
    onChange(next)
  }
  return (
    <div className="flex flex-col gap-2">
      <InfoLabel label={label} help={help} />
      {rows.map((row, i) => (
        <div key={i} className="border-stroke-widget flex flex-col gap-2 rounded-lg border p-2">
          <div className="flex flex-wrap gap-1">
            {DAYS.map((d, di) => {
              const on = row.days.includes(di)
              return (
                <button
                  type="button"
                  key={di}
                  onClick={() =>
                    update(i, {
                      days: on ? row.days.filter((x) => x !== di) : [...row.days, di].sort(),
                    })
                  }
                  className={`rounded-full px-2 py-1 text-[11px] font-semibold transition-colors ${
                    on
                      ? 'bg-plus-minus-button-bg text-primary-text'
                      : 'text-secondary-text/50 hover:text-primary-text/70'
                  }`}
                >
                  {d}
                </button>
              )
            })}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="time"
              value={minutesToHHMM(row.start_minute)}
              onChange={(e) => update(i, { start_minute: hhmmToMinutes(e.target.value) })}
              className="border-stroke-widget bg-primary-widget/40 text-primary-text rounded border px-2 py-1 text-[12px]"
            />
            <span className="text-secondary-text/60 text-[12px]">to</span>
            <input
              type="time"
              value={minutesToHHMM(row.end_minute)}
              onChange={(e) => update(i, { end_minute: hhmmToMinutes(e.target.value) })}
              className="border-stroke-widget bg-primary-widget/40 text-primary-text rounded border px-2 py-1 text-[12px]"
            />
            <button
              type="button"
              onClick={() => onChange(rows.filter((_, idx) => idx !== i))}
              className="text-red-400 text-[12px]"
            >
              Remove
            </button>
          </div>
        </div>
      ))}
      <button
        type="button"
        onClick={() =>
          onChange([...rows, { days: [1, 2, 3, 4, 5], start_minute: 540, end_minute: 1020 }])
        }
        className="text-primary-text self-start text-[12px] underline"
      >
        + Add a schedule window
      </button>
      {error && <Text className="text-red-400 text-[11px]">{error}</Text>}
    </div>
  )
}

// ── attribution ─────────────────────────────────────────────────────────────

export type AttributionEvent =
  | 'CLICK_THROUGH'
  | 'ENGAGED_VIDEO_VIEW'
  | 'VIEW_THROUGH'

export type AttributionWindow = {
  event_type: AttributionEvent
  window_days: number
}

// Meta's own default since March 2026, mirrored from the server's
// ATTRIBUTION_DEFAULT. Only a fallback — the live values arrive on
// catalog.attribution.default.
const DEFAULT_WINDOWS: AttributionWindow[] = [
  { event_type: 'CLICK_THROUGH', window_days: 7 },
  { event_type: 'ENGAGED_VIDEO_VIEW', window_days: 1 },
  { event_type: 'VIEW_THROUGH', window_days: 1 },
]

export function AttributionField({
  label,
  help,
  value,
  onChange,
  clickWindows = [1, 7],
  viewWindows = [0, 1],
  engagedViewWindows = [0, 1],
  defaults = DEFAULT_WINDOWS,
  error,
}: {
  label: string
  help?: string
  value: AttributionWindow[]
  onChange: (v: AttributionWindow[]) => void
  clickWindows?: number[]
  viewWindows?: number[]
  engagedViewWindows?: number[]
  defaults?: AttributionWindow[]
  error?: string
}) {
  // Unset shows Meta's default rather than blanks or "Off" — the field used to
  // render View as "Off" while a 1-day view was in fact running.
  const shown = (event: AttributionEvent) =>
    value.find((w) => w.event_type === event)?.window_days ??
    defaults.find((w) => w.event_type === event)?.window_days ??
    0

  const click = shown('CLICK_THROUGH')
  const engage = shown('ENGAGED_VIDEO_VIEW')
  const view = shown('VIEW_THROUGH')

  // Every select rebuilds the whole array from the three DISPLAYED values, so the
  // first edit writes all three at once. That is what keeps "show the default but
  // send nothing" honest: the user can never commit a partial spec that means
  // something different from the row they were looking at. 0 = off = no entry.
  const rebuild = (next: Partial<Record<AttributionEvent, number>>) => {
    const days: Record<AttributionEvent, number> = {
      CLICK_THROUGH: click,
      ENGAGED_VIDEO_VIEW: engage,
      VIEW_THROUGH: view,
      ...next,
    }
    onChange(
      DEFAULT_WINDOWS.map((w) => w.event_type)
        .filter((event) => days[event] > 0)
        .map((event) => ({ event_type: event, window_days: days[event] })),
    )
  }

  const opts = (windows: number[]) =>
    windows.map((d) => ({ value: String(d), label: d === 0 ? 'Off' : `${d}-day` }))

  return (
    <div className="flex flex-col gap-2">
      <InfoLabel label={label} help={help} />
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <PrimarySelect
          label="Click"
          data={opts(clickWindows)}
          value={String(click)}
          onChange={(v) => rebuild({ CLICK_THROUGH: Number(v) })}
          comboboxProps={{ zIndex: 1000001 }}
        />
        <PrimarySelect
          label="Engage"
          data={opts(engagedViewWindows)}
          value={String(engage)}
          onChange={(v) => rebuild({ ENGAGED_VIDEO_VIEW: Number(v) })}
          comboboxProps={{ zIndex: 1000001 }}
        />
        <PrimarySelect
          label="View"
          data={opts(viewWindows)}
          value={String(view)}
          onChange={(v) => rebuild({ VIEW_THROUGH: Number(v) })}
          comboboxProps={{ zIndex: 1000001 }}
        />
      </div>
      {/* Nothing set means we send no attribution_spec at all and Meta applies its
          own — so the selects above show that default rather than pretending the
          field is empty. Saying so keeps the campaign following Meta if the
          default moves again (it moved twice in 2026). */}
      {value.length === 0 && (
        <Text className="text-secondary-text/60 text-[11px]">
          Not set — Meta uses its default, shown above: 7-day click, 1-day
          engage-through, 1-day view. Change any of them to override it.
        </Text>
      )}
      {error && <Text className="text-red-400 text-[11px]">{error}</Text>}
    </div>
  )
}
