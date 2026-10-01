import { Combobox, useCombobox, Text, TextInput, Textarea } from '@mantine/core';
import { Plus, Sparkles, Trash2 } from 'lucide-react';
import { selectClassNames } from './editorUtils';

interface FieldProps {
  label: string;
  withAsterisk?: boolean;
  value: string;
  options: string[];
  maxLength: number;
  error?: string;
  multiline?: boolean;
  placeholder: string;
  onChange: (v: string) => void;
  onRemove?: () => void;
  headerAction?: React.ReactNode;
}

// Plain char count against the real cap (title/body/description's own
// `maxLength`) — no color, no "over Meta's recommended length" warning.
// Meta's real limits (255/2200/255, meta_spec/enums.py CREATIVE_*_MAX) are
// already the field's `maxLength`, so `len` can never exceed what's passed
// here; there is nothing left to warn about.
export function softLabel(label: React.ReactNode, len: number, max: number) {
  return (
    <span>
      {label} <span className="text-primary-text/40">({len}/{max})</span>
    </span>
  );
}

export function SoftCounter({ len, max }: { len: number; max: number }) {
  return (
    <Text fz={11} className="text-primary-text/30!">
      {len}/{max}
    </Text>
  );
}

function PickField({
  label,
  withAsterisk,
  value,
  options,
  maxLength,
  error,
  multiline,
  placeholder,
  onChange,
  onRemove,
  headerAction,
}: FieldProps) {
  const combobox = useCombobox();
  const rightSection = onRemove ? (
    <div
      role="button"
      tabIndex={0}
      onClick={(e) => {
        e.stopPropagation();
        onRemove();
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.stopPropagation();
          onRemove();
        }
      }}
      className="text-secondary-text/60 mr-2 flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center rounded-full hover:bg-red-500/10 hover:text-red-400"
    >
      <Trash2 size={13} />
    </div>
  ) : (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        if (options.length > 0) {
          combobox.toggleDropdown();
        }
      }}
      title={options.length > 0 ? 'AI suggestions' : 'Sparkle idea'}
      className="bg-primary-text/6 hover:bg-primary-text/12 border-primary-text/10 text-primary-text/70 hover:text-primary-text mr-1.5 flex h-6 w-6 cursor-pointer items-center justify-center rounded-full border transition-colors"
    >
      <Sparkles size={12} />
    </button>
  );

  const inputClass = multiline
    ? selectClassNames.input.replace('rounded-[32px]!', 'rounded-xl!')
    : selectClassNames.input;

  const common = {
    value,
    maxLength,
    error,
    placeholder,
    classNames: {
      ...selectClassNames,
      input: `${inputClass} pr-9!`,
      section: multiline
        ? `${selectClassNames.section} items-start! pt-2.5!`
        : selectClassNames.section,
    },
    rightSection,
    rightSectionPointerEvents: 'all' as const,
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      onChange(e.currentTarget.value),
  };

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-[12px] font-semibold text-primary-text/80">
          {softLabel(label, value.length, maxLength)}
          {withAsterisk && <span className="text-red-400 ml-0.5">*</span>}
        </span>
        {headerAction}
      </div>
      <Combobox
        store={combobox}
        withinPortal
        zIndex={1000000}
        onOptionSubmit={(v) => {
          onChange(v);
          combobox.closeDropdown();
        }}
      >
        <Combobox.Target>
          {multiline ? (
            <Textarea {...common} autosize minRows={2} maxRows={4} />
          ) : (
            <TextInput {...common} />
          )}
        </Combobox.Target>
        {options.length > 0 && (
          <Combobox.Dropdown
            className="border-stroke-widget! text-primary-text! shadow-widget! overflow-hidden rounded-2xl border p-1"
            style={{
              backgroundColor: 'var(--mantine-color-primary-widget, rgba(28, 28, 28, 0.95))',
              backdropFilter: 'blur(75.9px)',
              WebkitBackdropFilter: 'blur(75.9px)',
            }}
          >
            <Combobox.Options className="flex flex-col gap-0.5">
              {options.map((s) => (
                <Combobox.Option
                  value={s}
                  key={s}
                  className="hover:bg-primary-text/8! data-[selected]:bg-primary-text/12! text-primary-text! cursor-pointer! rounded-xl! px-3! py-2! text-[12.5px]! font-medium! transition-colors!"
                >
                  {s}
                </Combobox.Option>
              ))}
            </Combobox.Options>
          </Combobox.Dropdown>
        )}
      </Combobox>
    </div>
  );
}

interface Props {
  label: string;
  // Marks the first field only — the variants beneath it are optional extras.
  withAsterisk?: boolean;
  value: string;
  // The AI's other ideas, offered as a dropdown on every field. Picking one
  // fills that field — these never ship to Meta on their own.
  suggestions: string[];
  maxLength: number;
  error?: string;
  multiline?: boolean;
  onChange: (v: string) => void;
  placeholder?: string;
  // Extra options the user added by hand. Every entry ships to Meta as a text
  // variation, so these are editable rather than a picklist. Set
  // `onVariantsChange` only where the ad format can publish them.
  variants?: string[];
  onVariantsChange?: (v: string[]) => void;
  maxVariants?: number;
}

export default function CopyField({
  label,
  withAsterisk,
  value,
  suggestions,
  maxLength,
  error,
  multiline,
  onChange,
  placeholder,
  variants = [],
  onVariantsChange,
  maxVariants = 5,
}: Props) {
  const defaultPlaceholder =
    placeholder ??
    (label.toLowerCase().includes('headline') || label.toLowerCase().includes('title')
      ? 'e.g. Exclusive 20% Off Limited Time Offer'
      : label.toLowerCase().includes('body') ||
        label.toLowerCase().includes('text') ||
        label.toLowerCase().includes('description')
        ? 'e.g. Upgrade your routine with premium quality. Order today and get free shipping!'
        : `Enter ${label.toLowerCase()}…`);

  // A suggestion already sitting in another field is not worth offering: publish
  // de-duplicates the variations, so picking it twice would silently drop one.
  const taken = new Set([value, ...variants]);
  const options = suggestions.filter((s) => s && !taken.has(s));

  const addVariantButton = onVariantsChange && variants.length + 1 < maxVariants ? (
    <button
      type="button"
      onClick={() => onVariantsChange([...variants, ''])}
      className="text-primary-text/45 hover:text-primary-text flex w-fit cursor-pointer items-center gap-1 text-[11px] font-medium transition-colors"
    >
      <Plus size={11} /> Add another {label.toLowerCase()}
    </button>
  ) : null;

  return (
    <div className="flex flex-col gap-2">
      <PickField
        label={variants.length ? `${label} 1` : label}
        withAsterisk={withAsterisk}
        value={value}
        options={options}
        maxLength={maxLength}
        error={error}
        multiline={multiline}
        placeholder={defaultPlaceholder}
        onChange={onChange}
        headerAction={addVariantButton}
      />

      {onVariantsChange && (
        <>
          {variants.map((v, i) => (
            <PickField
              key={i}
              label={`${label} ${i + 2}`}
              value={v}
              options={options}
              maxLength={maxLength}
              multiline={multiline}
              placeholder={defaultPlaceholder}
              onChange={(next) =>
                onVariantsChange(
                  variants.map((x, idx) => (idx === i ? next : x))
                )
              }
              onRemove={() =>
                onVariantsChange(variants.filter((_x, idx) => idx !== i))
              }
            />
          ))}
          {variants.length > 0 && (
            <span className="text-secondary-text/50 text-[11px]">
              Meta runs every option and learns which combination performs.
            </span>
          )}
        </>
      )}
    </div>
  );
}
