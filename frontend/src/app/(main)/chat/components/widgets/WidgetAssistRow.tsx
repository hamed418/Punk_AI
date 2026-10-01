'use client';
import type { PendingActionBlock } from '@/types/chat';
import { Box, Text } from '@mantine/core';

/**
 * One-tap answers and the way out of an off-path loop.
 *
 * Rendered ONCE next to the active widget rather than inside each widget, so it
 * covers every action_type — including `text_input`, which renders no widget at
 * all, and `permission` / `stepper_input`, which ActiveWidgetRenderer has no case
 * for. Previously both rows lived only in WidgetOptionSelection, so a user stuck
 * at the intake form, a stepper, or a typed step had no visible way out even
 * though the backend was already sending `escape_menu`.
 *
 * Escape actions are submitted VERBATIM — wizard_helpers._match_escape compares
 * them exactly, ahead of the fuzzy option matcher.
 */
const ESCAPE_HELP: Record<string, string> = {
  'use default': "Take Punk's suggestion for this step",
  explain: 'Ask what this step is for',
  'exit wizard': 'Step out — your progress is saved',
};

interface WidgetAssistRowProps {
  content: PendingActionBlock['content'];
  onConfirm: (value: string) => void;
  disabled?: boolean;
}

export const WidgetAssistRow = ({
  content,
  onConfirm,
  disabled = false,
}: WidgetAssistRowProps) => {
  const escape = content.escape_menu ?? [];
  if (!escape.length) return null;

  const send = (value: string) => {
    if (disabled) return;
    onConfirm(`Q: ${content.prompt}\nA: ${value}`);
  };

  const chip =
    'border-underline/25 text-secondary-text hover:bg-primary-widget rounded-full ' +
    'border px-3 py-1 text-xs transition-colors disabled:opacity-40';

  return (
    <Box className="mx-auto flex w-full max-w-207.5 flex-col gap-2 pb-2">
      <Box className="flex flex-wrap items-center gap-2">
        <Text className="text-secondary-text text-xs opacity-70">Stuck?</Text>
        {escape.map((action) => (
          <button
            key={action}
            type="button"
            disabled={disabled}
            title={ESCAPE_HELP[action]}
            onClick={() => send(action)}
            className={`${chip} capitalize`}
          >
            {action}
          </button>
        ))}
      </Box>
    </Box>
  );
};

export default WidgetAssistRow;
