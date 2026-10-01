import { NumberInput } from '@mantine/core';
import { DateTimePicker } from '@mantine/dates';
import { Trash2 } from 'lucide-react';
import type { EditorCatalog, BudgetScheduleSpec } from '@/types/chat';
import { InfoLabel } from '../../forms/InfoLabel';
import { selectClassNames, toLocalString, fromPicker } from './editorUtils';

interface Props {
  catalog: EditorCatalog;
  value: BudgetScheduleSpec[];
  onChange: (v: BudgetScheduleSpec[]) => void;
  error?: string;
}

export default function BudgetScheduleField({
  catalog,
  value,
  onChange,
  error,
}: Props) {
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
          className="border-underline/15 flex flex-wrap gap-x-4 gap-y-3 rounded-xl border p-3"
        >
          <DateTimePicker
            label="From"
            placeholder="Select start date & time"
            valueFormat="MMM D, YYYY h:mm A"
            value={toLocalString(row.time_start)}
            onChange={(v) => patch(i, { time_start: fromPicker(v) ?? row.time_start })}
            classNames={selectClassNames}
            popoverProps={{ withinPortal: true, zIndex: 1000000 }}
          />
          <DateTimePicker
            label="To"
            placeholder="Select end date & time"
            valueFormat="MMM D, YYYY h:mm A"
            value={toLocalString(row.time_end)}
            onChange={(v) => patch(i, { time_end: fromPicker(v) ?? row.time_end })}
            classNames={selectClassNames}
            popoverProps={{ withinPortal: true, zIndex: 1000000 }}
          />
          <NumberInput
            label="Multiplier"
            placeholder="e.g. 1.5"
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
            className="text-secondary-text/60 ml-auto mt-7.75 flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-full hover:bg-red-500/10 hover:text-red-400"
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
