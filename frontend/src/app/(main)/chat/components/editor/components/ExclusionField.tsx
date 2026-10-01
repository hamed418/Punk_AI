import { useEffect, useRef, useState } from 'react';
import { Combobox, useCombobox, Loader, Box, Text, SegmentedControl } from '@mantine/core';
import { Search, X } from 'lucide-react';
import { searchTargetingAction } from '@/actions/ads.actions';
import type { TargetingSuggestion } from '@/types/chat';
import { selectClassNames, segmentedControlClassNames } from './editorUtils';
import type { FlexEntry } from './InterestField';

interface Props {
  targeting: Record<string, unknown>;
  patchTargeting: (p: Record<string, unknown>) => void;
}

export default function ExclusionField({
  targeting,
  patchTargeting,
}: Props) {
  // Behaviors were unreachable: the search was hardcoded to 'interests', so the
  // behaviors half of the write path was dead and the label lied. The endpoint
  // has taken kind=behaviors all along.
  const [kind, setKind] = useState<'interests' | 'behaviors'>('interests');
  const excl = (targeting.exclusions as FlexEntry) || {};
  const selected: { id: string; name: string; flex_field: 'interests' | 'behaviors' }[] = [
    ...(excl.interests || []).map((i) => ({ ...i, flex_field: 'interests' as const })),
    ...(excl.behaviors || []).map((b) => ({ ...b, flex_field: 'behaviors' as const })),
  ];
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<TargetingSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const combobox = useCombobox({
    onDropdownClose: () => combobox.resetSelectedOption(),
  });

  useEffect(() => {
    if (results.length > 0) {
      combobox.openDropdown();
    } else {
      combobox.closeDropdown();
    }
  }, [results, combobox]);

  const write = (
    next: { id: string; name: string; flex_field: 'interests' | 'behaviors' }[]
  ) => {
    const interests = next
      .filter((s) => s.flex_field === 'interests')
      .map((s) => ({ id: s.id, name: s.name }));
    const behaviors = next
      .filter((s) => s.flex_field === 'behaviors')
      .map((s) => ({ id: s.id, name: s.name }));
    const entry: FlexEntry = {};
    if (interests.length) entry.interests = interests;
    if (behaviors.length) entry.behaviors = behaviors;
    patchTargeting({ exclusions: Object.keys(entry).length ? entry : undefined });
  };

  const runSearch = (q: string) => {
    setQuery(q);
    if (debounce.current) clearTimeout(debounce.current);
    if (!q.trim()) {
      setResults([]);
      return;
    }
    debounce.current = setTimeout(async () => {
      setLoading(true);
      try {
        setResults(await searchTargetingAction(q, kind));
      } finally {
        setLoading(false);
      }
    }, 300);
  };

  const add = (s: TargetingSuggestion) => {
    if (selected.some((x) => x.id === s.id)) return;
    write([...selected, { id: s.id, name: s.name, flex_field: s.flex_field }]);
    setQuery('');
    setResults([]);
  };

  const remove = (id: string) => write(selected.filter((s) => s.id !== id));

  return (
    <div>
      <div className="text-secondary-text mb-1 text-[12px]">
        Exclude people (interests &amp; behaviors)
      </div>
      <SegmentedControl
        fullWidth
        size="xs"
        className="mb-2"
        value={kind}
        onChange={(v) => {
          setKind(v as 'interests' | 'behaviors');
          setResults([]);
        }}
        data={[
          { label: 'Interests', value: 'interests' },
          { label: 'Behaviors', value: 'behaviors' },
        ]}
        classNames={segmentedControlClassNames}
      />
      <Combobox
        store={combobox}
        withinPortal
        zIndex={1000001}
        onOptionSubmit={(val) => {
          const matched = results.find((r) => r.id === val);
          if (matched) add(matched);
          combobox.closeDropdown();
        }}
      >
        <div className="bg-transparent! border-primary-text/10! shadow-[0px_-1px_0px_0px_#00000026_inset,0px_1px_0px_0px_#FFFFFF0F_inset]! text-primary-text! rounded-4xl! w-full! border! flex flex-col! gap-2! px-3.5! py-2! min-h-10!">
          <Combobox.Target>
            <div className="flex items-center gap-2 w-full">
              <Search size={14} className="text-secondary-text/60 shrink-0" />
              <input
                value={query}
                onChange={(e) => {
                  runSearch(e.target.value);
                  combobox.openDropdown();
                }}
                placeholder={`Search ${kind} to exclude…`}
                className="text-primary-text min-w-0 flex-1 bg-transparent text-[13px] outline-none border-none py-0.5"
              />
              {loading && <Loader size={13} />}
            </div>
          </Combobox.Target>
          {selected.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {selected.map((s) => (
                <Box
                  key={s.id}
                  className="bg-primary-bg! border border-stroke-widget! rounded-full! py-0! pl-2 pr-1! h-6.5! flex items-center! gap-1! shadow-[0px_1.5px_3px_#00000040]!"
                >
                  <Text className="text-primary-text! text-[11px]! mb-0.5!">
                    {s.name}
                  </Text>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      remove(s.id);
                    }}
                    className="text-secondary-text! cursor-pointer hover:text-red-400! hover:bg-transparent! transition-colors! size-4! p-0! flex items-center justify-center!"
                  >
                    <X size={12} />
                  </button>
                </Box>
              ))}
            </div>
          )}
        </div>

        <Combobox.Dropdown classNames={{ dropdown: selectClassNames.dropdown }}>
          <Combobox.Options className="max-h-56 overflow-y-auto custom-textarea-scrollbar p-1">
            {results.map((r) => (
              <Combobox.Option
                key={r.id}
                value={r.id}
                className="text-primary-text/80 hover:bg-white/5 flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-[13px] cursor-pointer"
              >
                <span>{r.name}</span>
                {r.path && (
                  <span className="text-secondary-text/50 ml-2 truncate text-[11px]">
                    {r.path.join(' › ')}
                  </span>
                )}
              </Combobox.Option>
            ))}
          </Combobox.Options>
        </Combobox.Dropdown>
      </Combobox>
    </div>
  );
}
