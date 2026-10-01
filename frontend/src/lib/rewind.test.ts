import { describe, expect, it } from 'vitest';
import type { Block } from '@/types/chat';
import {
  awaitingReply,
  laterMessageCount,
  rewindImpact,
  rewindMarker,
  rewindableIds,
} from './rewind';

const ai = (id: string, ns: string | null, ckpt: string | null): Block => ({
  id,
  type: 'message',
  role: 'assistant',
  content: id,
  checkpoint_ns: ns,
  checkpoint_id: ckpt,
});
const user = (id: string): Block => ({
  id,
  type: 'message',
  role: 'user',
  content: id,
});

describe('rewindableIds', () => {
  it('offers an answer whose preceding assistant row carries a full address', () => {
    const blocks = [ai('q1', 'campaign_builder:x', 'c1'), user('a1')];
    expect([...rewindableIds(blocks)]).toEqual(['a1']);
  });

  it('treats an empty namespace as a real value, not a missing one', () => {
    expect(rewindableIds([ai('q1', '', 'c1'), user('a1')]).has('a1')).toBe(true);
  });

  it('refuses answers whose anchor predates the namespace stamp', () => {
    expect(rewindableIds([ai('q1', null, 'c1'), user('a1')]).size).toBe(0);
    expect(rewindableIds([ai('q1', 'ns', null), user('a1')]).size).toBe(0);
    expect(rewindableIds([user('a0')]).size).toBe(0); // opening message has no anchor
  });

  it('a builder step sharing one address is reachable only from its FIRST row', () => {
    const blocks = [
      ai('q1', 'campaign_builder:x', 'c1'),
      user('a1'),
      ai('q2', 'campaign_builder:x', 'c1'),
      user('a2'),
    ];
    expect([...rewindableIds(blocks)]).toEqual(['a1']);
  });

  it('a parent-graph pause sharing one address is reachable only from its SECOND row', () => {
    const blocks = [ai('q1', '', 'c1'), user('a1'), ai('q2', '', 'c1'), user('a2')];
    expect([...rewindableIds(blocks)]).toEqual(['a2']);
  });
});

describe('laterMessageCount', () => {
  const blocks: Block[] = [
    ai('q1', 'ns', 'c1'),
    user('a1'),
    ai('q2', 'ns', 'c2'),
    { id: 's', type: 'message', role: 'system', content: 'note' },
    user('a2'),
  ];
  it('counts chat messages after the answer, not system notes', () => {
    expect(laterMessageCount(blocks, 'a1')).toBe(2);
    expect(laterMessageCount(blocks, 'a2')).toBe(0);
    expect(laterMessageCount(blocks, 'missing')).toBe(0);
  });
});

describe('copy', () => {
  it('states the impact with the count and the token cost', () => {
    expect(rewindImpact(0)).toBe('This re-runs from this step. Re-running uses tokens.');
    expect(rewindImpact(1)).toContain('the 1 message after');
    expect(rewindImpact(4)).toContain('the 4 messages after');
    expect(rewindImpact(4)).toContain('uses tokens');
  });

  it('marks the cut in the transcript', () => {
    expect(rewindMarker(true, 3)).toBe('Continuing from your edited answer — 3 later messages were removed.');
    expect(rewindMarker(true, 1)).toBe('Continuing from your edited answer — 1 later message was removed.');
    expect(rewindMarker(false, 0)).toBe('Went back to this step.');
  });
});

describe('awaitingReply', () => {
  const marker: Block = {
    id: 'm',
    type: 'message',
    role: 'system',
    kind: 'rewind_marker',
    content: 'Continuing from your edited answer.',
  };
  const note: Block = { id: 'n', type: 'message', role: 'system', content: 'note' };

  it('is true right after a user answer, as before', () => {
    expect(awaitingReply([ai('q', 'ns', 'c'), user('a')])).toBe(true);
  });

  it('stays true when a status line follows the answer — the rewind regression', () => {
    expect(awaitingReply([ai('q', 'ns', 'c'), user('a'), marker])).toBe(true);
    expect(awaitingReply([ai('q', 'ns', 'c'), user('a'), note])).toBe(true);
  });

  it('is true for an undo, where the marker trails an older answer or an assistant row', () => {
    expect(awaitingReply([user('a0'), marker])).toBe(true);
    expect(awaitingReply([ai('q0', 'ns', 'c'), marker])).toBe(true);
  });

  it('turns off once something real has arrived', () => {
    expect(awaitingReply([user('a'), marker, ai('q2', 'ns', 'c2')])).toBe(false);
    expect(awaitingReply([user('a'), { id: 'w', type: 'map_data', content: {} } as unknown as Block])).toBe(false);
    expect(awaitingReply([])).toBe(false);
  });
});
