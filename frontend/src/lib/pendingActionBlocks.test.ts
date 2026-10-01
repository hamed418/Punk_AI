import { describe, expect, it } from 'vitest';
import type { Block } from '@/types/chat';
import { upsertPendingAction } from './pendingActionBlocks';

const pa = (step: string, prompt = 'Pick one') =>
  ({ action_type: 'option_selection', prompt, step_key: step }) as never;

let n = 0;
const ids = () => `id-${++n}`;

describe('upsertPendingAction', () => {
  it('appends when the step is new', () => {
    const out = upsertPendingAction([], pa('geo_collect_locations'), ids);
    expect(out).toHaveLength(1);
    expect(out[0].type).toBe('pending_action');
  });

  it('replaces the same step IN PLACE, keeping the block id', () => {
    // The off-path re-ask. A new id changes the React key, which remounts the
    // widget and wipes whatever the user had typed.
    const first = upsertPendingAction([], pa('maid_collect_settings'), ids);
    const id = first[0].id;

    const second = upsertPendingAction(first, pa('maid_collect_settings', 'Try again'), ids);

    expect(second).toHaveLength(1);
    expect(second[0].id).toBe(id);
    expect((second[0].content as { prompt: string }).prompt).toBe('Try again');
  });

  it('replaces a step embedded in a map block, not appending beside it', () => {
    // POI confirm and MAID confirm ride map_data. Matching only standalone
    // blocks left them remounting — and the appended standalone copy of a
    // permission/stepper action renders as NOTHING.
    const blocks: Block[] = [
      {
        id: 'map-1',
        type: 'map_data',
        // Only the fields upsertPendingAction reads; the full MaidSplitViewData
        // payload is irrelevant to block placement.
        content: { action_type: 'maid_split_view', pending_action: pa('maid_confirm_results') },
      } as unknown as Block,
    ];

    const out = upsertPendingAction(blocks, pa('maid_confirm_results', 'Confirm?'), ids);

    expect(out).toHaveLength(1);
    expect(out[0].type).toBe('map_data');
    expect(out[0].id).toBe('map-1');
    const embedded = (out[0].content as { pending_action: { prompt: string } }).pending_action;
    expect(embedded.prompt).toBe('Confirm?');
  });

  it('appends a genuinely different step rather than clobbering', () => {
    const first = upsertPendingAction([], pa('geo_collect_locations'), ids);
    const out = upsertPendingAction(first, pa('geo_collect_det_type'), ids);
    expect(out).toHaveLength(2);
  });

  it('falls back to append when the payload carries no step_key', () => {
    const noStep = { action_type: 'option_selection', prompt: 'x' } as never;
    const out = upsertPendingAction([], noStep, ids);
    expect(out).toHaveLength(1);
  });

  it('never mutates the input array', () => {
    const blocks: Block[] = [];
    upsertPendingAction(blocks, pa('a'), ids);
    expect(blocks).toHaveLength(0);
  });

  it('updates the LAST copy of a repeated step, not the first', () => {
    // An edit rolls a stage back and the planner re-asks a step the user has
    // already answered, so the same step_key legitimately appears twice in one
    // thread. Matching the first copy wrote the refreshed widget far up the
    // scrollback and left the stale one on screen — on the recovery path, which
    // is exactly when the user is already confused.
    // Two copies already in the transcript — this is what a reloaded thread
    // looks like after an earlier rollback re-asked the step.
    const onscreen: Block[] = [
      { id: 'first', type: 'pending_action', content: pa('geo_confirm_locations', 'FIRST') } as never,
      { id: 'msg', type: 'message', role: 'assistant', content: '...' } as never,
      { id: 'second', type: 'pending_action', content: pa('geo_confirm_locations', 'SECOND') } as never,
    ];

    const out = upsertPendingAction(
      onscreen,
      { action_type: 'option_selection', prompt: 'AFTER ROLLBACK', step_key: 'geo_confirm_locations' } as never,
      ids
    );
    expect(out).toHaveLength(3);
    expect(out[2].id).toBe('second');   // replaced in place, key preserved
    expect((out[2].content as { prompt: string }).prompt).toBe('AFTER ROLLBACK');
    expect((out[0].content as { prompt: string }).prompt).toBe('FIRST');
  });

  it('prefers a later map_data-embedded widget over an older standalone one', () => {
    const standalone = upsertPendingAction([], pa('geo_pois_confirmation', 'OLD'), ids);
    const withMap: Block[] = [
      ...standalone,
      {
        id: 'map',
        type: 'map_data',
        content: { pending_action: { step_key: 'geo_pois_confirmation', prompt: 'ON SCREEN' } },
      } as never,
    ];
    const out = upsertPendingAction(
      withMap,
      { action_type: 'option_selection', prompt: 'FRESH', step_key: 'geo_pois_confirmation' } as never,
      ids
    );
    expect(out).toHaveLength(2);
    expect(
      (out[1].content as { pending_action: { prompt: string } }).pending_action.prompt
    ).toBe('FRESH');
    expect((out[0].content as { prompt: string }).prompt).toBe('OLD');
  });

  it('appends rather than rewriting a step_key match from before the last user message', () => {
    // A rollback re-asks a step the user already answered — same step_key,
    // legitimately a new turn. ChatPage's activeAssistContent/activeWidgetBlock
    // memos stop their own backward scan at the last user message, so a match
    // ABOVE that boundary is history to them; rewriting it in place leaves the
    // bottom of the chat with no widget, no chips, no escape menu at all — the
    // "it forgot everything" bug, now firing on the exact edit/rollback path
    // this whole module exists to support.
    const onscreen: Block[] = [
      { id: 'old-widget', type: 'pending_action', content: pa('geo_confirm_locations', 'OLD') } as never,
      { id: 'user-reply', type: 'message', role: 'user', content: 'add Toronto' } as never,
    ];

    const out = upsertPendingAction(
      onscreen,
      { action_type: 'option_selection', prompt: 'RE-ASKED', step_key: 'geo_confirm_locations' } as never,
      ids
    );

    expect(out).toHaveLength(3);                                  // appended, not rewritten
    expect((out[0].content as { prompt: string }).prompt).toBe('OLD');   // history untouched
    expect(out[2].type).toBe('pending_action');
    expect((out[2].content as { prompt: string }).prompt).toBe('RE-ASKED');
  });

  it('still replaces in place when the repeated step_key comes after the last user message', () => {
    // Guards the boundary itself: two off-path re-asks of the SAME step in the
    // SAME turn (no user message between them) must still collapse to one
    // widget, exactly as before this fix.
    const onscreen: Block[] = [
      { id: 'user-reply', type: 'message', role: 'user', content: 'huh?' } as never,
      { id: 'this-turn', type: 'pending_action', content: pa('geo_confirm_locations', 'FIRST ASK') } as never,
    ];

    const out = upsertPendingAction(
      onscreen,
      { action_type: 'option_selection', prompt: 'SECOND ASK', step_key: 'geo_confirm_locations' } as never,
      ids
    );

    expect(out).toHaveLength(2);
    expect(out[1].id).toBe('this-turn');
    expect((out[1].content as { prompt: string }).prompt).toBe('SECOND ASK');
  });
});
