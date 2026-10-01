'use client';

import { z } from 'zod';

import {
  Accordion,
  Alert,
  NumberInput,
  MultiSelect,
  ScrollArea,
  SegmentedControl,
  Text,
  Textarea,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { DateInput, DateTimePicker } from '@mantine/dates';
import { Lock } from 'lucide-react';
import {
  Fragment,
  forwardRef,
  useImperativeHandle,
  useMemo,
  useState,
  type Ref,
} from 'react';
import dayjs from 'dayjs';
import PrimarySelect from '@/components/PrimarySelect';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';
import {
  AttributionField,
  DaypartingField,
  type AttributionWindow,
  type DayPart,
} from './scheduleFields';
import { InfoLabel, makeOptionRenderer } from './InfoLabel';
import type {
  FormCondition,
  FormField,
  FormOption,
  FormSchema,
} from '@/types/chat';

// ── visible_when / required_when evaluation ─────────────────────────────────

function valueMatches(live: unknown, allowed: string[]): boolean {
  if (Array.isArray(live)) {
    return live.some((v) => allowed.includes(String(v)));
  }
  return allowed.includes(String(live ?? ''));
}

function clauseMatches(
  clause: Record<string, string[]>,
  values: Record<string, unknown>
): boolean {
  return Object.entries(clause).every(([key, allowed]) =>
    valueMatches(values[key], allowed)
  );
}

export function conditionMatches(
  cond: FormCondition | undefined,
  values: Record<string, unknown>
): boolean {
  if (!cond) return true;
  if (Array.isArray(cond)) return cond.some((c) => clauseMatches(c, values));
  return clauseMatches(cond, values);
}

// ── option resolution (objective-driven local swap) ─────────────────────────

function optionsFor(
  field: FormField,
  values: Record<string, unknown>
): FormOption[] {
  if (field.options_by_objective) {
    const objective = String(values['objective'] ?? '');
    const byObj = field.options_by_objective[objective];
    if (byObj) return byObj;
  }
  return field.options ?? [];
}

const toWhole = (minor: unknown, scale: number): number | undefined =>
  minor == null || minor === '' ? undefined : Number(minor) / scale;
const toMinor = (
  whole: number | string | undefined,
  scale: number
): number | undefined =>
  whole == null || whole === '' ? undefined : Math.round(Number(whole) * scale);

export type SubmitAction = {
  label: string;
  action: string;
  variant?: 'primary' | 'ghost';
};

interface DynamicFormProps {
  schema: FormSchema;
  initialValues?: Record<string, unknown>;
  errors?: Record<string, string>;
  // Empty (or omitted) when the caller draws its own submit button and drives
  // the form through the ref instead — see DynamicFormHandle. The action row
  // at the bottom of the form only renders when this is non-empty.
  submitActions?: SubmitAction[];
  submitMode?: 'changed' | 'full';
  onSubmit: (action: string, changedValues: Record<string, unknown>) => void;
  fullHeight?: boolean;
  className?: string;
}

export interface DynamicFormHandle {
  /** Runs the same validate → assemble → onSubmit path a submitActions button
   * would, for a caller (CampaignEditor's intake footer) that draws its own
   * Back/Next bar instead of using submitActions. */
  submit: (action: string) => void;
}

function getCategory(field: FormField): string {
  const k = field.key.toLowerCase();
  const l = field.label.toLowerCase();

  if (k === 'business_name' || l.includes('business name'))
    return 'business_name';
  if (k === 'objective' || l.includes('objective')) return 'objective';
  if (
    field.type === 'textarea' ||
    k === 'business_context' ||
    k === 'business_description' ||
    l.includes('description') ||
    l.includes('what you sell')
  )
    return 'description';
  if (k === 'website' || k === 'website_url' || l === 'website')
    return 'website';
  if (
    k === 'lead_form_id' ||
    k === 'instant_form' ||
    l.includes('instant form') ||
    l.includes('lead form')
  )
    return 'instant_form';
  if (k === 'app_store_url' || l.includes('app store')) return 'app_store';
  if (
    k === 'play_store_url' ||
    k === 'google_play_url' ||
    l.includes('google play')
  )
    return 'google_play';
  if (k === 'pixel_id' || k === 'meta_pixel_id' || l.includes('pixel'))
    return 'pixel';
  if (
    k === 'budget_type' ||
    k === 'campaign_budget_type' ||
    l.includes('budget type')
  )
    return 'budget_type';
  if (
    k === 'budget_amount' ||
    k === 'campaign_daily_budget' ||
    k === 'daily_budget' ||
    l.includes('budget')
  )
    return 'budget_amount';
  if (
    k === 'start_date' ||
    k === 'campaign_start_date' ||
    l.includes('start date')
  )
    return 'start_date';
  if (k === 'end_date' || k === 'campaign_end_date' || l.includes('end date'))
    return 'end_date';
  return 'other';
}

function getDemoPlaceholder(field: FormField): string {
  const cat = getCategory(field);
  switch (cat) {
    case 'business_name':
      return 'eg: Autopaws';
    case 'description':
      return 'Tell us what you are promoting so we can build the right campaign foundation...';
    case 'website':
      return 'website.com';
    case 'instant_form':
      return 'e.g. 123456789012345';
    case 'app_store':
      return 'https://apps.apple.com/app/your-app/id123456789';
    case 'google_play':
      return 'https://play.google.com/store/apps/details?id=com.yourapp';
    case 'pixel':
      return 'Select a dataset';
    case 'budget_amount':
      return '21';
    default:
      return `e.g. ${field.label}`;
  }
}



function DynamicForm(
  {
    schema,
    initialValues,
    errors,
    submitActions = [],
    submitMode = 'changed',
    onSubmit,
    fullHeight = false,
    className = '',
  }: DynamicFormProps,
  ref: Ref<DynamicFormHandle>
) {
  const seed = useMemo(() => {
    const out: Record<string, unknown> = {};
    for (const group of schema.groups) {
      const fields = group.repeat
        ? (group.items ?? []).flatMap((it) => it.fields)
        : (group.fields ?? []);
      for (const f of fields) {
        if (f.suggestion !== undefined && f.suggestion !== null) {
          out[f.key] = f.suggestion;
        } else if (f.type === 'select') {
          // No opts[0] fallback: a suggestion-less select (pixel_id, lead_form_id,
          // page_id with nothing stored yet) stays genuinely unset rather than
          // silently picking whatever Meta's API happened to list first — see
          // the "no auto-select" note beside the analogous render-time guard below.
          const opts = optionsFor(f, out);
          const defaultOpt = opts.find(
            (o) =>
              o.label.toLowerCase() === 'awareness' ||
              o.value.toLowerCase() === 'awareness' ||
              o.value === 'OUTREACH'
          );
          if (defaultOpt) out[f.key] = defaultOpt.value;
        } else {
          const cat = getCategory(f);
          if (cat === 'start_date') {
            out[f.key] = dayjs().format('YYYY-MM-DD');
          } else if (cat === 'end_date') {
            out[f.key] = null;
          }
        }
      }
    }
    return { ...out, ...(initialValues ?? {}) };
  }, [schema, initialValues]);

  const [values, setValues] = useState<Record<string, unknown>>(seed);
  const [changed, setChanged] = useState<Set<string>>(
    // Pre-seed with all keys that already have a value so stale server-side
    // errors are suppressed for fields pre-filled from suggestions / initialValues.
    () => new Set(Object.keys(seed).filter((k) => seed[k] != null && seed[k] !== ''))
  );
  const [localErrors, setLocalErrors] = useState<Record<string, string>>({});

  const setValue = (key: string, value: unknown) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setChanged((prev) => new Set(prev).add(key));
    if (localErrors[key]) {
      setLocalErrors((prev) => {
        const copy = { ...prev };
        delete copy[key];
        return copy;
      });
    }
  };

  const isFieldRequired = (field: FormField): boolean => {
    if (!field.editable) return false;
    if (field.required_when != null) {
      return conditionMatches(field.required_when, values);
    }
    // The server declares what it actually rejects a submission over. Marking a
    // field required that the backend defaults anyway is a question asked for
    // nothing — it blocked "do it for me" users on a Pixel they had never heard
    // of. Schemas that predate the flag keep the old everything-is-required rule.
    if (typeof field.required === 'boolean') return field.required;
    const cat = getCategory(field);
    if (cat === 'end_date' || cat === 'start_date') return false;
    return true;
  };

  const rootError = errors?.['__root__'];

  const handleSubmit = (action: string) => {
    if (action === 'back') {
      onSubmit(action, {});
      return;
    }

    const visibleFields: FormField[] = [];
    for (const group of schema.groups) {
      const fields = group.repeat
        ? (group.items ?? []).flatMap((it) => it.fields)
        : (group.fields ?? []);
      for (const f of fields) {
        if (conditionMatches(f.visible_when, values)) {
          visibleFields.push(f);
        }
      }
    }

    // Build a Zod schema dynamically from the visible, required fields
    const schemaShape: Record<string, z.ZodTypeAny> = {};
    for (const f of visibleFields) {
      if (!isFieldRequired(f)) continue;
      if (f.type === 'multiselect') {
        schemaShape[f.key] = z
          .array(z.string(), { error: 'This field is required' })
          .min(1, 'This field is required');
      } else if (f.type === 'number' || f.type === 'currency') {
        schemaShape[f.key] = z
          .number({ error: 'This field is required' })
          .or(z.string().min(1, 'This field is required'));
      } else {
        schemaShape[f.key] = z
          .string({ error: 'This field is required' })
          .min(1, 'This field is required')
          .nullable();
      }
    }

    const zodSchema = z.object(schemaShape).passthrough();
    const result = zodSchema.safeParse(values);

    if (!result.success) {
      const newErrors: Record<string, string> = {};
      let firstInvalidKey: string | null = null;
      for (const issue of result.error.issues) {
        const key = String(issue.path[0]);
        if (!newErrors[key]) {
          newErrors[key] = issue.message;
          if (!firstInvalidKey) firstInvalidKey = key;
        }
      }
      setLocalErrors(newErrors);
      if (firstInvalidKey) {
        setTimeout(() => {
          const el = document.getElementById(`field-${firstInvalidKey}`);
          if (el) {
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        }, 50);
      }
      return;
    }

    setLocalErrors({});
    const visibleKeys = new Set(visibleFields.map((f) => f.key));
    const out: Record<string, unknown> = {};
    if (submitMode === 'full') {
      for (const key of visibleKeys) out[key] = values[key];
    } else {
      for (const key of changed) {
        if (visibleKeys.has(key)) out[key] = values[key];
      }
    }
    onSubmit(action, out);
  };

  // No deps array: handleSubmit closes over values/changed/localErrors and is
  // redefined every render anyway, so memoizing against it would either go
  // stale or need listing everything it closes over. Recomputing this trivial
  // wrapper every render is cheaper than chasing that list.
  useImperativeHandle(ref, () => ({ submit: handleSubmit }));

  const renderField = (field: FormField) => {
    if (!conditionMatches(field.visible_when, values)) return null;

    // Suppress stale server-side errors once the user has touched a field
    const error = (!changed.has(field.key) && errors?.[field.key]) || localErrors[field.key];
    let label = field.label;
    const required = isFieldRequired(field);

    const cat = getCategory(field);

    if (cat === 'budget_amount') {
      const budgetTypeVal = String(
        values['budget_type'] ??
          values['campaign_budget_type'] ??
          Object.entries(values).find(
            ([k]) =>
              getCategory({ key: k, label: k } as FormField) === 'budget_type'
          )?.[1] ??
          'daily'
      ).toLowerCase();
      const isLifetime = budgetTypeVal === 'lifetime';

      if (isLifetime) {
        if (label && /daily/i.test(label)) {
          label = label.replace(/daily/gi, 'total');
        } else if (label && /campaign budget/i.test(label)) {
          label = label.replace(/campaign budget/gi, 'Campaign total budget');
        } else if (label) {
          label = label.includes('Campaign')
            ? 'Campaign total budget'
            : 'Total budget';
        } else {
          label = 'Campaign total budget';
        }
      } else {
        if (label && /lifetime/i.test(label)) {
          label = label.replace(/lifetime/gi, 'daily');
        } else if (label && /total/i.test(label)) {
          label = label.replace(/total/gi, 'daily');
        } else if (
          label &&
          /campaign budget/i.test(label) &&
          !/daily/i.test(label)
        ) {
          label = label.replace(/campaign budget/gi, 'Campaign daily budget');
        } else if (!label) {
          label = 'Campaign daily budget';
        }
      }
    }

    const isInputOrSelect =
      field.type !== 'textarea' &&
      field.type !== 'dayparting' &&
      field.type !== 'attribution';

    const inputStyles = {
      label: {
        marginBottom: '7.75px',
      },
      input: {
        height: isInputOrSelect ? '42px' : undefined,
        minHeight: isInputOrSelect ? '42px' : undefined,
        background: '#FFFFFF00',
        boxShadow:
          '0px -1px 0px 0px #00000026 inset, 0px 1px 0px 0px #FFFFFF0F inset',
        borderRadius: isInputOrSelect ? '32px' : '20px',
      },
    };

    const common = {
      label: <InfoLabel label={label} help={field.help} required={required} />,
      placeholder: getDemoPlaceholder(field),
      error,
      styles: inputStyles,
    };

    if (!field.editable) {
      return (
        <div key={field.key} className="flex flex-col gap-1">
          <Text className="text-primary-text text-[13px] font-medium">
            {label}
          </Text>
          <div className="border-stroke-widget bg-primary-widget/40 flex items-center gap-2 rounded-lg border px-3 py-2">
            <Tooltip label={field.locked_reason ?? 'Locked'} withArrow>
              <Lock size={13} className="text-secondary-text/60 shrink-0" />
            </Tooltip>
            <Text className="text-secondary-text text-[12px]">
              {String(values[field.key] ?? field.suggestion ?? '—')}
            </Text>
          </div>
        </div>
      );
    }

    // Special custom controls based on category
    if (cat === 'budget_type') {
      const currentVal = String(values[field.key] ?? 'daily').toLowerCase();
      return (
        <div key={field.key} className="flex flex-col">
          <div style={{ marginBottom: '7.75px' }}>
            <InfoLabel
              label={field.label || 'Campaign budget type'}
              help={field.help}
              required={required}
            />
          </div>
          <SegmentedControl
            fullWidth
            value={currentVal === 'lifetime' ? 'lifetime' : 'daily'}
            onChange={(v) => setValue(field.key, v)}
            data={[
              { label: 'Daily Budget', value: 'daily' },
              { label: 'Total Budget', value: 'lifetime' },
            ]}
            styles={{
              root: {
                height: '40px',
                background: 'rgba(255,255,255,0.04)',
                borderRadius: '32px',
                padding: '3px',
              },
              indicator: {
                background: 'rgba(255,255,255,0.08)',
                border: '1px solid rgba(255,255,255,0.12)',
                borderRadius: '24px',
                boxShadow:
                  '0px 2px 12px 0px #00000040, 0px 1px 0px 0px #FFFFFF40 inset',
              },
              label: {
                fontSize: '13px',
                fontWeight: 500,
                color: 'rgba(255,255,255,0.40)',
                height: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '0 12px',
              },
              control: {
                border: 'none !important',
              },
            }}
            classNames={{
              label: '[&[data-active]]:!text-[var(--color-primary-text)]',
            }}
          />
        </div>
      );
    }

    if (cat === 'start_date') {
      const raw = values[field.key];
      const isToday =
        !raw ||
        raw === 'today' ||
        (typeof raw === 'string' && dayjs(raw).isSame(dayjs(), 'day'));

      return (
        <div key={field.key} className="flex flex-col gap-1.5 md:py-4">
          <InfoLabel
            label={field.label || 'Campaign Start Date'}
            help={field.help}
            required={required}
          />
          <SegmentedControl
            value={isToday ? 'today' : 'pick'}
            onChange={(v) => {
              if (v === 'today')
                setValue(field.key, dayjs().format('YYYY-MM-DD'));
              else
                setValue(field.key, dayjs().add(1, 'day').format('YYYY-MM-DD'));
            }}
            data={[
              { label: 'Today', value: 'today' },
              { label: 'Pick a date', value: 'pick' },
            ]}
            styles={{
              root: {
                width: 'calc(50% + 15px)',
                height: '40px',
                background: 'rgba(255,255,255,0.04)',
                borderRadius: '24px',
                padding: '3px',
              },
              indicator: {
                background: 'rgba(255,255,255,0.08)',
                border: '1px solid rgba(255,255,255,0.12)',
                borderRadius: '20px',
                boxShadow:
                  '0px 2px 12px 0px #00000040, 0px 1px 0px 0px #FFFFFF40 inset',
              },
              label: {
                fontSize: '13px',
                fontWeight: 500,
                color: 'rgba(255,255,255,0.40)',
                height: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '0 12px',
              },
              control: {
                border: 'none !important',
              },
            }}
            classNames={{
              label: '[&[data-active]]:!text-[var(--color-primary-text)]',
            }}
          />
          <DateInput
            {...common}
            label={null}
            valueFormat="MMM D, YYYY"
            value={
              values[field.key]
                ? new Date(String(values[field.key]))
                : new Date()
            }
            onChange={(d) =>
              setValue(field.key, d ? dayjs(d).format('YYYY-MM-DD') : null)
            }
            styles={{
              input: {
                ...inputStyles.input,
                border: '1px solid rgba(255,255,255,0.08)',
              },
            }}
            popoverProps={{
            zIndex: 10001,
            classNames: {
              dropdown: 'bg-[#FFFFFF03]! backdrop-blur-[75.9000015258789px]! rounded-[18px]! shadow-[0px_8px_24px_0px_#00000080,0px_-1px_0px_0px_#00000066_inset,0px_1px_0px_0px_#FFFFFF1F_inset]!',
            },
            styles: {
              dropdown: {
                backgroundColor: '#FFFFFF03',
                background: '#FFFFFF03',
              },
            },
          }}
          />
        </div>
      );
    }

    if (cat === 'end_date') {
      const raw = values[field.key];
      const isOngoing = !raw || raw === 'ongoing' || raw === null || raw === '';

      return (
        <div
          key={field.key}
          className="flex flex-col gap-1.5 md:ml-0 md:border-l md:border-white/10 md:pl-8 md:p-4"
        >
          <InfoLabel
            label={field.label || 'Campaign End Date'}
            help={field.help}
            required={required}
          />
          <SegmentedControl
            value={isOngoing ? 'ongoing' : 'pick'}
            onChange={(v) => {
              if (v === 'ongoing') setValue(field.key, null);
              else
                setValue(
                  field.key,
                  dayjs().add(14, 'days').format('YYYY-MM-DD')
                );
            }}
            data={[
              { label: 'Ongoing', value: 'ongoing' },
              { label: 'Pick a date', value: 'pick' },
            ]}
            styles={{
              root: {
                width: 'calc(50% + 25px)',
                height: '40px',
                background: 'rgba(255,255,255,0.04)',
                borderRadius: '24px',
                padding: '3px',
              },
              indicator: {
                background: 'rgba(255,255,255,0.08)',
                border: '1px solid rgba(255,255,255,0.12)',
                borderRadius: '20px',
                boxShadow:
                  '0px 2px 12px 0px #00000040, 0px 1px 0px 0px #FFFFFF40 inset',
              },
              label: {
                fontSize: '13px',
                fontWeight: 500,
                color: 'rgba(255,255,255,0.40)',
                height: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '0 12px',
              },
              control: {
                border: 'none !important',
              },
            }}
            classNames={{
              label: '[&[data-active]]:!text-[var(--color-primary-text)]',
            }}
          />
          <DateInput
            {...common}
            label={null}
            disabled={isOngoing}
            placeholder={isOngoing ? 'Ongoing campaign' : 'Select date'}
            valueFormat="MMM D, YYYY"
            value={
              values[field.key] && !isOngoing
                ? new Date(String(values[field.key]))
                : null
            }
            onChange={(d) =>
              setValue(field.key, d ? dayjs(d).format('YYYY-MM-DD') : null)
            }
            styles={{
              input: {
                ...inputStyles.input,
                border: '1px solid rgba(255,255,255,0.08)',
              },
            }}
            popoverProps={{
            zIndex: 10001,
            classNames: {
              dropdown: 'bg-[#FFFFFF03]! backdrop-blur-[75.9000015258789px]! rounded-[18px]! shadow-[0px_8px_24px_0px_#00000080,0px_-1px_0px_0px_#00000066_inset,0px_1px_0px_0px_#FFFFFF1F_inset]!',
            },
            styles: {
              dropdown: {
                backgroundColor: '#FFFFFF03',
                background: '#FFFFFF03',
              },
            },
          }}
          />
        </div>
      );
    }

    switch (field.type) {
      case 'select': {
        const resolved = optionsFor(field, values);
        const opts = resolved.map((o) => ({ value: o.value, label: o.label }));
        const descs = Object.fromEntries(
          resolved.map((o) => [o.value, o.description])
        );
        // No opts[0] fallback here either — a preselected pixel or lead form
        // reads as "Punk verified this" and gets submitted without a look.
        // Blank is a real, submittable answer (see the matching seed-time note).
        const defaultAwarenessOpt = opts.find(
          (o) =>
            o.label.toLowerCase() === 'awareness' ||
            o.value.toLowerCase() === 'awareness' ||
            o.value === 'OUTREACH'
        );
        // `''` is a real option value ("Create a default one for me"), not a
        // missing one — treating it as missing wrote the default back every
        // render and looped forever on the Leads instant-form select.
        const missing = values[field.key] == null;
        const currentValue = missing
          ? (defaultAwarenessOpt?.value ?? null)
          : String(values[field.key]);
        if (missing && currentValue != null) {
          setValue(field.key, currentValue);
        }
        return (
          <PrimarySelect
            key={field.key}
            {...common}
            data={opts}
            renderOption={makeOptionRenderer(descs)}
            value={currentValue}
            onChange={(v) => setValue(field.key, v)}
            comboboxProps={{ zIndex: 10001 }}
          />
        );
      }
      case 'multiselect': {
        const resolved = optionsFor(field, values);
        const opts = resolved.map((o) => ({ value: o.value, label: o.label }));
        const descs = Object.fromEntries(
          resolved.map((o) => [o.value, o.description])
        );
        const current = Array.isArray(values[field.key])
          ? (values[field.key] as unknown[]).map(String)
          : [];
        return (
          <MultiSelect
            key={field.key}
            {...common}
            data={opts}
            renderOption={makeOptionRenderer(descs)}
            value={current}
            onChange={(v) => setValue(field.key, v)}
            comboboxProps={{
              zIndex: 10001,
              shadow: 'md',
              transitionProps: { transition: 'fade', duration: 150 },
            }}
            styles={{
              ...common.styles,
              dropdown: {
                maxHeight: '180px',
                backdropFilter: 'blur(15px)',
                WebkitBackdropFilter: 'blur(15px)',
                backgroundColor: 'rgba(24, 24, 27, 0.75)',
                border: '1px solid rgba(255, 255, 255, 0.15)',
                borderRadius: '16px',
                padding: '6px',
                boxShadow: '0 8px 32px 0 rgba(0, 0, 0, 0.36)',
              },
            }}
            classNames={{
              dropdown:
                'bg-primary-bg/40! backdrop-blur-[15px] border-primary-text/20 rounded-xl overflow-hidden shadow-xl',
              option:
                'text-secondary-text text-xs! py-2 px-3 rounded-lg transition-colors hover:bg-white/5! hover:text-primary-text! data-[selected]:bg-white/10! data-[selected]:text-primary-text! dark:hover:bg-white/5! light:hover:bg-black/5!',
              pill: 'bg-white/10 text-primary-text border border-white/15 rounded-md text-xs',
            }}
          />
        );
      }
      case 'textarea':
        return (
          <Textarea
            key={field.key}
            {...common}
            autosize
            maxLength={field.max_length}
            value={String(values[field.key] ?? '')}
            onChange={(e) => setValue(field.key, e.currentTarget.value)}
          />
        );
      case 'number':
        return (
          <NumberInput
            key={field.key}
            {...common}
            min={field.min}
            max={field.max}
            value={values[field.key] == null ? '' : Number(values[field.key])}
            onChange={(v) => setValue(field.key, v)}
          />
        );
      case 'currency': {
        const scale = field.minor_units ?? 100;
        return (
          <NumberInput
            key={field.key}
            {...common}
            min={field.min != null ? field.min / scale : 0}
            prefix={field.prefix ?? '$'}
            decimalScale={scale === 1 ? 0 : 2}
            fixedDecimalScale
            value={toWhole(values[field.key], scale) ?? ''}
            onChange={(v) => setValue(field.key, toMinor(v as number, scale))}
            classNames={{
              controls:
                '!absolute !right-[6px] !top-1/2 !-translate-y-1/2 !h-7 !border-0 flex flex-col gap-px [.mantine-InputWrapper-root_&]:!top-auto [.mantine-InputWrapper-root_&]:!translate-y-0',
            }}
          />
        );
      }
      case 'date':
        return (
          <DateInput
            key={field.key}
            {...common}
            valueFormat="MMM D, YYYY"
            value={
              values[field.key] ? new Date(String(values[field.key])) : null
            }
            onChange={(d) =>
              setValue(field.key, d ? dayjs(d).format('YYYY-MM-DD') : null)
            }
            popoverProps={{
            zIndex: 10001,
            classNames: {
              dropdown: 'bg-[#FFFFFF03]! backdrop-blur-[75.9000015258789px]! rounded-[18px]! shadow-[0px_8px_24px_0px_#00000080,0px_-1px_0px_0px_#00000066_inset,0px_1px_0px_0px_#FFFFFF1F_inset]!',
            },
            styles: {
              dropdown: {
                backgroundColor: '#FFFFFF03',
                background: '#FFFFFF03',
              },
            },
          }}
          />
        );
      case 'datetime': {
        const stored = values[field.key];
        const localString = stored
          ? dayjs(String(stored)).format('YYYY-MM-DD HH:mm:ss')
          : null;
        return (
          <DateTimePicker
            key={field.key}
            {...common}
            valueFormat="MMM D, YYYY h:mm A"
            value={localString}
            onChange={(v) => setValue(field.key, v ? dayjs(v).format() : null)}
            popoverProps={{
            zIndex: 10001,
            classNames: {
              dropdown: 'bg-[#FFFFFF03]! backdrop-blur-[75.9000015258789px]! rounded-[18px]! shadow-[0px_8px_24px_0px_#00000080,0px_-1px_0px_0px_#00000066_inset,0px_1px_0px_0px_#FFFFFF1F_inset]!',
            },
            styles: {
              dropdown: {
                backgroundColor: '#FFFFFF03',
                background: '#FFFFFF03',
              },
            },
          }}
          />
        );
      }
      case 'dayparting':
        return (
          <DaypartingField
            key={field.key}
            label={field.label}
            help={field.help}
            value={(values[field.key] as DayPart[]) ?? []}
            onChange={(v) => setValue(field.key, v)}
            error={error}
          />
        );
      case 'attribution':
        return (
          <AttributionField
            key={field.key}
            label={field.label}
            help={field.help}
            value={(values[field.key] as AttributionWindow[]) ?? []}
            onChange={(v) => setValue(field.key, v)}
            clickWindows={field.windows?.click}
            viewWindows={field.windows?.view}
            error={error}
          />
        );
      case 'text':
      default:
        return (
          <TextInput
            key={field.key}
            {...common}
            maxLength={field.max_length}
            value={String(values[field.key] ?? '')}
            onChange={(e) => setValue(field.key, e.currentTarget.value)}
          />
        );
    }
  };

  const renderFieldList = (fields: FormField[]) => {
    const visibleFields = fields.filter((f) =>
      conditionMatches(f.visible_when, values)
    );

    const objectiveVal = String(values['objective'] ?? '').toLowerCase();
    const isLeads = objectiveVal.includes('lead');
    const isApp = objectiveVal.includes('app');
    const isSales =
      objectiveVal.includes('sale') || objectiveVal.includes('conversion');
    const objType = isLeads
      ? 'leads'
      : isApp
        ? 'app_promotion'
        : isSales
          ? 'sales'
          : 'awareness';

    const orderMap: Record<string, string[]> = {
      awareness: [
        'business_name',
        'objective',
        'description',
        'website',
        'budget_amount',
        'budget_type',
        'start_date',
        'end_date',
      ],
      leads: [
        'business_name',
        'objective',
        'description',
        'website',
        'instant_form',
        'budget_amount',
        'budget_type',
        'start_date',
        'end_date',
      ],
      app_promotion: [
        'business_name',
        'objective',
        'description',
        'app_store',
        'google_play',
        'website',
        'budget_amount',
        'budget_type',
        'start_date',
        'end_date',
      ],
      sales: [
        'business_name',
        'objective',
        'description',
        'website',
        'pixel',
        'budget_amount',
        'budget_type',
        'start_date',
        'end_date',
      ],
    };

    const desiredSeq = orderMap[objType] || orderMap.awareness;

    const sortedFields = [...visibleFields].sort((a, b) => {
      const catA = getCategory(a);
      const catB = getCategory(b);
      let idxA = desiredSeq.indexOf(catA);
      let idxB = desiredSeq.indexOf(catB);
      if (idxA === -1) idxA = 999;
      if (idxB === -1) idxB = 999;
      return idxA - idxB;
    });

    const dividerSet = new Set<string>();
    let col = 0;

    sortedFields.forEach((field, i) => {
      const cat = getCategory(field);
      const isFull =
        cat === 'description' ||
        (cat === 'website' &&
          (objType === 'awareness' || objType === 'app_promotion')) ||
        ['textarea', 'dayparting', 'attribution'].includes(field.type);

      const isLast = i === sortedFields.length - 1;

      if (isFull) {
        col = 0;
        if (!isLast) {
          dividerSet.add(field.key);
        }
      } else {
        col += 1;
        const nextIsFull =
          i + 1 < sortedFields.length &&
          (() => {
            const nextF = sortedFields[i + 1];
            const nextC = getCategory(nextF);
            return (
              nextC === 'description' ||
              (nextC === 'website' &&
                (objType === 'awareness' || objType === 'app_promotion')) ||
              ['textarea', 'dayparting', 'attribution'].includes(nextF.type)
            );
          })();

        if (col === 2 || nextIsFull) {
          if (!isLast) {
            if (
              cat !== 'objective' &&
              !(objType === 'app_promotion' && cat === 'google_play')
            ) {
              dividerSet.add(field.key);
            }
          }
          col = 0;
        }
      }
    });

    return (
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {sortedFields.map((field) => {
          const cat = getCategory(field);
          const isFullWidth =
            cat === 'description' ||
            (cat === 'website' &&
              (objType === 'awareness' || objType === 'app_promotion')) ||
            ['textarea', 'dayparting', 'attribution'].includes(field.type);

          const rendered = renderField(field);
          if (!rendered) return null;

          const showDividerAfter = dividerSet.has(field.key);

          return (
            <Fragment key={field.key}>
              <div
                id={`field-${field.key}`}
                className={
                  isFullWidth ? 'col-span-1 md:col-span-2' : 'col-span-1'
                }
              >
                {rendered}
              </div>
              {showDividerAfter && (
                <hr
                  className="col-span-1 m-0 -mx-4 mt-1 border-t-2 border-white/6 p-0 md:col-span-2"
                />
              )}
            </Fragment>
          );
        })}
      </div>
    );
  };

  const hasBudgetAndDates = useMemo(() => {
    const allFields = schema.groups.flatMap((g) =>
      g.repeat ? (g.items ?? []).flatMap((it) => it.fields) : (g.fields ?? [])
    );
    const categories = new Set(allFields.map(getCategory));
    return (
      (categories.has('budget_amount') || categories.has('budget_type')) &&
      (categories.has('start_date') || categories.has('end_date'))
    );
  }, [schema]);

  const isFullHeight = fullHeight || hasBudgetAndDates;

  return (
    <div className={`flex flex-col ${isFullHeight ? 'flex-1 h-full min-h-0' : ''} ${className}`}>
      {rootError && (
        <Alert color="red" variant="light" className="m-4 mb-0 text-[13px]">
          {rootError}
        </Alert>
      )}

      <ScrollArea.Autosize
        mah={isFullHeight ? '100%' : '55vh'}
        type="hover"
        scrollbars="y"
        scrollbarSize={6}
        offsetScrollbars
        className={`custom-textarea-scrollbar px-1 ${isFullHeight ? 'flex-1 min-h-0 h-full' : ''}`}
        styles={{
          scrollbar: {
            background: 'transparent',
          },
          thumb: {
            background: 'color-mix(in srgb, var(--color-primary-text) 18%, transparent)',
            borderRadius: '999px',
          },
        }}
      >
        <div className={`flex flex-col gap-4 pb-2 ${isFullHeight ? 'flex-1 min-h-0 h-full' : ''}`}>
          {schema.groups.map((group) => {
            if (!group.repeat) {
              return (
                <div key={group.key} className={`flex flex-col gap-3 px-4 pt-4 ${isFullHeight ? 'flex-1 min-h-0 h-full' : ''}`}>
                  {renderFieldList(group.fields ?? [])}
                </div>
              );
            }
            return (
              <div key={group.key} className="flex flex-col gap-2 px-4 pt-4">
                <Accordion
                  multiple
                  defaultValue={(group.items ?? []).map((it) => String(it.index))}
                  variant="separated"
                >
                  {(group.items ?? []).map((item) => {
                    const itemError = errors?.[`${group.key}[${item.index}]`];
                    return (
                      <Accordion.Item key={item.index} value={String(item.index)}>
                        <Accordion.Control>
                          <span className="text-primary-text text-[13px] font-medium">
                            {item.label}
                          </span>
                        </Accordion.Control>
                        <Accordion.Panel>
                          <div className="flex flex-col gap-3">
                            {itemError && (
                              <Alert
                                color="red"
                                variant="light"
                                className="text-[12px]"
                              >
                                {itemError}
                              </Alert>
                            )}
                            {renderFieldList(item.fields)}
                          </div>
                        </Accordion.Panel>
                      </Accordion.Item>
                    );
                  })}
                </Accordion>
              </div>
            );
          })}
        </div>
      </ScrollArea.Autosize>

      {submitActions.length > 0 && (
        <div className="border-primary-text/10 flex flex-wrap items-center justify-end gap-3 border-t p-4">
          {submitActions.map((a) => (
            <PrimaryGlassBtn
              key={a.action}
              type="button"
              onClick={() => handleSubmit(a.action)}
              withArrow={a.variant !== 'ghost'}
              variant={a.variant}
            >
              {a.label}
            </PrimaryGlassBtn>
          ))}
        </div>
      )}
    </div>
  );
}

export default forwardRef(DynamicForm);
