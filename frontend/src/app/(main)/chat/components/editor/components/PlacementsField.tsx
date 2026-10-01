import { SegmentedControl, MultiSelect } from '@mantine/core';
import type { EditorCatalog } from '@/types/chat';
import {
  toSelectData,
  multiSelectClassNames,
  segmentedControlClassNames,
} from './editorUtils';

interface Props {
  catalog: EditorCatalog;
  targeting: Record<string, unknown>;
  patchTargeting: (p: Record<string, unknown>) => void;
}

export default function PlacementsField({
  catalog,
  targeting,
  patchTargeting,
}: Props) {
  const platforms = (targeting.publisher_platforms as string[]) || undefined;
  const mode = platforms ? 'manual' : 'advantage_plus';
  const posFieldBy = catalog.placements.position_field_by_platform;

  const setMode = (m: string) => {
    if (m === 'advantage_plus') {
      const cleared: Record<string, unknown> = { publisher_platforms: undefined };
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

  // Dropping a platform has to drop its positions with it. The positions control
  // unmounts, but the key stayed in targeting — and the server rejects
  // "facebook_positions requires 'facebook' in publisher_platforms", pointing at
  // a field that is no longer on screen for the user to fix.
  const setPlatforms = (next: string[]) => {
    const patch: Record<string, unknown> = { publisher_platforms: next };
    Object.entries(posFieldBy).forEach(([platform, field]) => {
      if (!next.includes(platform)) patch[field] = undefined;
    });
    patchTargeting(patch);
  };

  return (
    <div>
      <div className="text-secondary-text mb-1 text-[12px]">Placements</div>
      <SegmentedControl
        fullWidth
        size="sm"
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
            placeholder={platforms && platforms.length > 0 ? '' : 'All platforms (or select specific ones)'}
            data={toSelectData(catalog.placements.publisher_platforms)}
            value={platforms || []}
            onChange={setPlatforms}
            classNames={multiSelectClassNames}
            comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
          />
          {(platforms || []).map((plat) => {
            const field = posFieldBy[plat];
            const opts = catalog.placements.positions[plat];
            if (!field || !opts) return null;
            const curVal = (targeting[field] as string[]) || [];
            return (
              <MultiSelect
                key={plat}
                label={`${plat} positions`}
                placeholder={curVal.length > 0 ? '' : `All ${plat} positions (or select specific ones)`}
                data={toSelectData(opts)}
                value={curVal}
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
