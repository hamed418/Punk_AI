import { SegmentedControl } from '@mantine/core';
import { InfoLabel } from '../../forms/InfoLabel';
import { segmentedControlClassNames } from './editorUtils';

interface Props {
  targeting: Record<string, unknown>;
  patchTargeting: (p: Record<string, unknown>) => void;
  children?: React.ReactNode;
}

const advantageSegmentedControlClassNames = {
  ...segmentedControlClassNames,
  root: `${segmentedControlClassNames.root} w-full!`,
  control: `${segmentedControlClassNames.control} min-w-0! overflow-hidden!`,
  label:
    'text-secondary-text! data-[active]:text-primary-text! data-[active]:font-semibold! text-[11px]! min-[380px]:text-[12px]! sm:text-[13px]! py-1.5! px-1! min-[380px]:px-2! sm:px-3! truncate! block! text-center!',
  innerLabel: 'truncate! block! max-w-full!',
};

export default function AdvantageAudienceField({
  targeting,
  patchTargeting,
  children,
}: Props) {
  const automation =
    (targeting.targeting_automation as { advantage_audience?: number }) || {};
  const on = automation.advantage_audience === 1;

  return (
    <div className="flex flex-col gap-3">
      <div>
        <div className="text-secondary-text mb-1 text-[12px]">
          <InfoLabel
            label="Advantage+ audience"
            help="Meta looks beyond your targeting when it finds better results. Your age, gender and interests become suggestions rather than limits."
          />
        </div>
        <SegmentedControl
          fullWidth
          size="sm"
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
          classNames={advantageSegmentedControlClassNames}
        />
        {on && (
          <div className="text-secondary-text/60 mt-1.5 text-[11px]">
            Interests and demographics below are suggestions — Meta may deliver
            outside them.
          </div>
        )}
      </div>
      {on && children}
    </div>
  );
}
