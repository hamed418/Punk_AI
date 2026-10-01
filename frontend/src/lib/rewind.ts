import type { Block, MessageBlock } from '@/types/chat';

const isMessage = (b: Block): b is MessageBlock => b.type === 'message';

/** Fork address of an assistant row, or null when it predates the namespace stamp. */
const stampOf = (b: MessageBlock): string | null =>
  b.checkpoint_id != null && b.checkpoint_ns != null
    ? `${b.checkpoint_ns}|${b.checkpoint_id}`
    : null;

/**
 * Ids of the user answers that can be rewound. Mirrors the server's `plan_rewind`
 * (backend chat/rewind_restore.py) — offering a button the server would refuse only
 * ends in an error.
 *
 * A user answer is rewindable when the assistant row before it carries BOTH halves of
 * the fork address (`checkpoint_ns === ''` is a real value and falsy in JS, so this
 * tests for null/undefined). Assistant rows sharing one address (several interrupts in
 * one node run) cannot be told apart by it: a builder step (non-empty namespace) is
 * restarted and re-asks the FIRST of them, a parent-graph pause ('') is forked and
 * re-arms the SECOND. Only that row's answer can be changed.
 */
export function rewindableIds(blocks: Block[]): Set<string> {
  const groups = new Map<string, string[]>();
  for (const b of blocks) {
    if (!isMessage(b) || b.role === 'user') continue;
    const key = stampOf(b);
    if (key) groups.set(key, [...(groups.get(key) ?? []), b.id]);
  }

  const ids = new Set<string>();
  let anchor: MessageBlock | null = null;
  for (const b of blocks) {
    if (!isMessage(b)) continue;
    if (b.role !== 'user') {
      anchor = b;
      continue;
    }
    const key = anchor ? stampOf(anchor) : null;
    if (!anchor || !key) continue;
    const group = groups.get(key) ?? [];
    const reachable = anchor.checkpoint_ns ? group[0] : group[1];
    if (group.length <= 1 || reachable === anchor.id) ids.add(b.id);
  }
  return ids;
}

/** Chat messages after `id` — what changing that answer will discard. */
export function laterMessageCount(blocks: Block[], id: string): number {
  const at = blocks.findIndex((b) => b.id === id);
  if (at === -1) return 0;
  return blocks
    .slice(at + 1)
    .filter((b) => isMessage(b) && b.role !== 'system').length;
}

/** The one sentence every change/redo affordance shows before it acts. */
export function rewindImpact(later: number): string {
  const discarded =
    later > 0
      ? `This removes the ${later} message${later === 1 ? '' : 's'} after this step and re-runs from here.`
      : 'This re-runs from this step.';
  return `${discarded} Re-running uses tokens.`;
}

/**
 * True while the turn is running but has shown the user nothing new yet — the
 * trailing blocks are only system notes after a user answer, or a rewind marker.
 * Drives the "Punk is working" shimmer + step label. It used to test only "last block
 * is a user message", so a status line appended after the answer hid the indicator and
 * the screen looked finished while the server was still re-running the step.
 */
export function awaitingReply(blocks: Block[]): boolean {
  for (let i = blocks.length - 1; i >= 0; i--) {
    const b = blocks[i];
    if (!isMessage(b)) return false;
    if (b.kind === 'rewind_marker') return true;
    if (b.role === 'system') continue;
    return b.role === 'user';
  }
  return false;
}

/** Transcript marker shown right after a rewind, so the cut never looks like a glitch. */
export function rewindMarker(resubmitting: boolean, discarded: number): string {
  const tail =
    discarded > 0
      ? ` — ${discarded} later message${discarded === 1 ? ' was' : 's were'} removed`
      : '';
  return resubmitting
    ? `Continuing from your edited answer${tail}.`
    : `Went back to this step${tail}.`;
}
