import { useEffect, useRef, useState } from 'react';
import { useParams } from 'next/navigation';
import { Combobox, useCombobox, Loader, Box, Text, SegmentedControl } from '@mantine/core';
import { Search, Plus, X } from 'lucide-react';
import { searchTargetingAction, suggestTargetingAction } from '@/actions/ads.actions';
import type { TargetingSuggestion } from '@/types/chat';
import { selectClassNames, segmentedControlClassNames } from './editorUtils';

export type FlexEntry = {
  interests?: { id: string; name: string }[];
  behaviors?: { id: string; name: string }[];
};

export function readSelected(
  targeting: Record<string, unknown>
): { id: string; name: string; flex_field: 'interests' | 'behaviors' }[] {
  const flex = (targeting.flexible_spec as FlexEntry[]) || [];
  const out: { id: string; name: string; flex_field: 'interests' | 'behaviors' }[] = [];
  flex.forEach((entry) => {
    (entry.interests || []).forEach((i) =>
      out.push({ id: i.id, name: i.name, flex_field: 'interests' })
    );
    (entry.behaviors || []).forEach((b) =>
      out.push({ id: b.id, name: b.name, flex_field: 'behaviors' })
    );
  });
  return out;
}

export function writeSelected(
  selected: { id: string; name: string; flex_field: 'interests' | 'behaviors' }[]
): FlexEntry[] | undefined {
  const interests = selected
    .filter((s) => s.flex_field === 'interests')
    .map((s) => ({ id: s.id, name: s.name }));
  const behaviors = selected
    .filter((s) => s.flex_field === 'behaviors')
    .map((s) => ({ id: s.id, name: s.name }));
  const entry: FlexEntry = {};
  if (interests.length) entry.interests = interests;
  if (behaviors.length) entry.behaviors = behaviors;
  return Object.keys(entry).length ? [entry] : undefined;
}

interface Props {
  targeting: Record<string, unknown>;
  patchTargeting: (p: Record<string, unknown>) => void;
  // Employment / housing / financial campaigns: Meta forbids detailed targeting
  // outright, and the server rejects a flexible_spec on one. Without this the
  // autofill below wrote interests nobody picked and made the plan unsubmittable.
  blocked?: boolean;
}

export default function InterestField({
  targeting,
  patchTargeting,
  blocked = false,
}: Props) {
  const selected = readSelected(targeting);
  // Behaviors were unreachable — the search was hardcoded to 'interests', so the
  // behaviors half of writeSelected was dead code and the label lied.
  const [kind, setKind] = useState<'interests' | 'behaviors'>('interests');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<TargetingSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [suggested, setSuggested] = useState<TargetingSuggestion[]>([]);
  const [prefilled, setPrefilled] = useState(false);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const didPrefill = useRef(false);

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

  const params = useParams();
  const threadId = (params.threadId as string) || '';
  const seeds = selected
    .filter((s) => s.flex_field === 'interests')
    .map((s) => s.name)
    .join(',');

  useEffect(() => {
    if (blocked) return;
    let stale = false;
    suggestTargetingAction(threadId, seeds).then((res) => {
      if (stale) return;
      setSuggested(res);
      if (!didPrefill.current && selected.length === 0 && res.length) {
        didPrefill.current = true;
        const top = res.slice(0, 3);
        patchTargeting({
          flexible_spec: writeSelected(
            top.map((s) => ({ id: s.id, name: s.name, flex_field: s.flex_field }))
          ),
        });
        setPrefilled(true);
      }
    });
    return () => {
      stale = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId, seeds, blocked]);

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
        const res = await searchTargetingAction(q, kind);
        setResults(res);
      } finally {
        setLoading(false);
      }
    }, 300);
  };

  const add = (s: TargetingSuggestion) => {
    if (selected.some((x) => x.id === s.id)) return;
    patchTargeting({
      flexible_spec: writeSelected([
        ...selected,
        { id: s.id, name: s.name, flex_field: s.flex_field },
      ]),
    });
    setQuery('');
    setResults([]);
  };

  const remove = (id: string) =>
    patchTargeting({
      flexible_spec: writeSelected(selected.filter((s) => s.id !== id)),
    });

  const suggestedUnpicked = suggested
    .filter((s) => !selected.some((x) => x.id === s.id))
    .slice(0, 12);

  if (blocked) return null;

  return (
    <div>
      <div className="text-secondary-text mb-1 text-[12px]">
        Detailed targeting (interests &amp; behaviors)
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
                placeholder={`Search ${kind}…`}
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
                  <Text className="text-primary-text! text-[11px]! mb-px!">
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
      {prefilled && selected.length > 0 && (
        <div className="text-secondary-text/60 mt-1.5 text-[11px]">
          Added from your business details — remove any that don&apos;t fit.
        </div>
      )}
      {suggestedUnpicked.length > 0 && (
        <div className="mt-2">
          <div className="text-secondary-text/60 mb-1 text-[11px]">Suggested</div>
          <div className="flex flex-wrap gap-1.5">
            {suggestedUnpicked.map((s) => (
              <button
                key={s.id}
                onClick={() => add(s)}
                className="border-stroke-widget/60 text-secondary-text hover:text-primary-text flex items-center gap-1 rounded-full border border-dashed px-2.5 py-1 text-[11px] hover:bg-white/5"
              >
                <Plus size={10} />
                {s.name}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
