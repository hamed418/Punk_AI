import type { Block, MapDataBlock, PendingActionBlock } from '@/types/chat';

type PendingContent = PendingActionBlock['content'];

const stepOf = (c: unknown): string | null | undefined =>
  (c as { step_key?: string | null } | undefined)?.step_key;

/**
 * Place an incoming pending_action into the block list, replacing the SAME step
 * in place rather than appending a new one.
 *
 * Why in place: the backend re-emits the identical step on every off-path reply
 * (reject / query / a refused edit). Appending a block with a fresh
 * `crypto.randomUUID()` changes the React `key`, which unmounts and remounts the
 * widget — wiping whatever the user had typed — while BlockRenderer returns null
 * for the superseded block, so it vanishes and their message is left floating
 * under a gap. That is what "it broke and forgot everything" looked like, and it
 * fired on every single off-path reply.
 *
 * Two homes to check. A pending_action can live standalone, or embedded inside a
 * map_data block — POI confirm and MAID confirm both ride map_data, so matching
 * only standalone blocks left the highest-traffic gates remounting. Worse, the
 * appended standalone copy of a `permission` / `stepper_input` action renders as
 * nothing at all (ActiveWidgetRenderer has no case for either), so the widget
 * could disappear outright.
 *
 * Matched from the END, but ONLY back to the last user message — not the whole
 * thread. `ChatPage.tsx`'s `activeAssistContent` / `activeWidgetBlock` memos
 * stop their own backward scan at that exact same boundary (a block above it is
 * history, not the live widget), so a step that legitimately repeats — a
 * rollback re-asking a step the user already answered once — must match its
 * OWN copy after the boundary and fall through to append otherwise. Matching
 * across the boundary rewrites the OLD copy in place: nothing changes at the
 * bottom of the chat, so the widget, its chips and its escape menu all appear
 * to vanish — the exact "it forgot everything" bug this function exists to
 * prevent, now triggered by the one path (edit → re-ask) it was written for.
 * Keep this boundary condition byte-identical to ChatPage.tsx's two memos.
 *
 * Returns a NEW array; never mutates the input.
 */
export function upsertPendingAction(
  blocks: Block[],
  content: PendingContent,
  newId: () => string
): Block[] {
  const next = [...blocks];
  const step = stepOf(content);

  // One backward scan over both shapes: whichever comes LAST *after the last
  // user message* is the widget actually on screen, standalone or map-embedded.
  for (let i = next.length - 1; step && i >= 0; i--) {
    const b = next[i];
    if (b.type === 'message' && b.role === 'user') break;
    if (b.type === 'pending_action' && stepOf(b.content) === step) {
      next[i] = { ...b, content } as Block;
      return next;
    }
    if (
      b.type === 'map_data' &&
      stepOf((b.content as { pending_action?: unknown })?.pending_action) === step
    ) {
      const mb = b as MapDataBlock;
      next[i] = {
        ...mb,
        content: { ...mb.content, pending_action: content },
      } as MapDataBlock;
      return next;
    }
  }

  next.push({ id: newId(), type: 'pending_action', content } as Block);
  return next;
}
