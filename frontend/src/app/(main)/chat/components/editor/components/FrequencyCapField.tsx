import { NumberInput } from '@mantine/core';
import type { EditorCatalog, FrequencyControlSpec } from '@/types/chat';
import { InfoLabel } from '../../forms/InfoLabel';
import { selectClassNames, FIELD_HELP, frequencyCapOf } from './editorUtils';

interface Props {
  catalog: EditorCatalog;
  value: FrequencyControlSpec[];
  onChange: (v: FrequencyControlSpec[]) => void;
  error?: string;
}

export default function FrequencyCapField({
  catalog,
  value,
  onChange,
  error,
}: Props) {
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
      <div className="flex flex-col sm:flex-row items-stretch sm:items-end gap-3">
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
