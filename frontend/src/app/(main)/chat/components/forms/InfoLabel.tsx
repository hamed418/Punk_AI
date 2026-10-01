'use client';

import { Tooltip } from '@mantine/core';
import { Info } from 'lucide-react';
import type { ReactNode } from 'react';

// A field label with an optional "!" info icon. When `help` is present the icon
// shows the explanation on hover/focus/tap. Used by both the intake DynamicForm
// and the bespoke CampaignEditor so every field explains itself the same way.
export function InfoLabel({
  label,
  help,
  required,
  className,
}: {
  label: ReactNode;
  help?: string;
  required?: boolean;
  className?: string;
}) {
  return (
    <span
      className={`text-primary-text inline-flex items-center gap-1.5 text-[12px] font-medium leading-none ${className || ''}`}
      onClick={(e) => {
        e.stopPropagation();
        e.preventDefault();
      }}
    >
      <span className="inline-flex items-center leading-none">{label}</span>
      {required ? <span className="text-red-400 leading-none"> *</span> : null}
      {help ? (
        <Tooltip
          label={help}
          withArrow
          multiline
          w={240}
          position="top"
          events={{ hover: true, focus: true, touch: true }}
          zIndex={1000002}
          styles={{
            tooltip: {
              backgroundColor: 'var(--mantine-color-widget-inner-glass-bg)',
              backdropFilter: 'blur(16px)',
              WebkitBackdropFilter: 'blur(16px)',
              border: '1px solid var(--mantine-color-plus-minus-button-border)',
              borderRadius: '8px',
              padding: '6px 8px',
              lineHeight: 1.2,
              color: 'var(--color-secondary-text)',
            },
            arrow: {
              backgroundColor: 'var(--mantine-color-widget-inner-glass-bg)',
              border: '1px solid var(--mantine-color-plus-minus-button-border)',
            },
          }}
        >
          <Info
            size={12}
            className="text-secondary-text/60 shrink-0 cursor-help self-center"
            aria-label="More info"
            onClick={(e) => {
              e.stopPropagation();
              e.preventDefault();
            }}
          />
        </Tooltip>
      ) : null}
    </span>
  );
}

// Builds a Mantine Select/MultiSelect `renderOption` that shows each option's
// description under its label, so users see what each choice means in the
// dropdown itself. `descs` maps option value → description.
export function makeOptionRenderer(descs: Record<string, string | undefined>) {
  return function renderOption({
    option,
  }: {
    option: { value: string; label: string };
  }) {
    const d = descs[option.value];
    return (
      <div className="flex flex-col">
        <span className="text-[13px]">{option.label}</span>
        {d ? (
          <span className="text-secondary-text/60 text-[11px] leading-snug">
            {d}
          </span>
        ) : null}
      </div>
    );
  };
}
