import { describe, expect, it } from 'vitest';
import { buildSubscriptionRows, formatEndsOn } from './subscriptionRows';

const sub = (over: Record<string, unknown> = {}) => ({
  id: `s-${Math.random()}`,
  status: 'active',
  ad_account_id: 'act_A',
  cancel_at_period_end: false,
  current_period_end: null as string | null,
  created_at: '2026-01-01T00:00:00Z',
  ...over,
});

const tokens = [{ accessible_accounts: [{ id: 'act_A', name: 'Shawarma Palace' }] }];

describe('buildSubscriptionRows', () => {
  it('shows only live subscriptions — one card per paid account', () => {
    const rows = buildSubscriptionRows(
      [
        sub({ id: 'live' }),
        sub({ id: 'trial', status: 'trialing', ad_account_id: 'act_B' }),
        sub({ id: 'late', status: 'past_due', ad_account_id: 'act_C' }),
        sub({ id: 'gone', status: 'canceled' }),
        sub({ id: 'never', status: 'incomplete' }),
      ],
      tokens
    );
    expect(rows.map((r) => r.sub.id)).toEqual(['live', 'trial', 'late']);
  });

  it('marks a scheduled cancel as ending and carries its date', () => {
    const [row] = buildSubscriptionRows(
      [sub({ cancel_at_period_end: true, current_period_end: '2030-06-15T12:00:00Z' })],
      tokens
    );
    expect(row.state).toBe('ending');
    expect(row.endsOn).toBe('2030-06-15T12:00:00Z');
  });

  it('reports a failed payment as past_due even when a cancel is scheduled', () => {
    const [row] = buildSubscriptionRows(
      [sub({ status: 'past_due', cancel_at_period_end: true })],
      tokens
    );
    expect(row.state).toBe('past_due');
  });

  it('names the account from the connection, then falls back to the id, then "Unassigned"', () => {
    const rows = buildSubscriptionRows(
      [
        sub({ id: '1', ad_account_id: 'act_A' }),
        sub({ id: '2', ad_account_id: 'act_UNKNOWN' }),
        sub({ id: '3', ad_account_id: null }),
      ],
      tokens
    );
    expect(rows.map((r) => r.accountName)).toEqual([
      'Shawarma Palace',
      'act_UNKNOWN',
      'Unassigned',
    ]);
    expect(rows[2].accountId).toBeNull();
  });

  it('orders active, then ending, then past_due, oldest first within a group', () => {
    const rows = buildSubscriptionRows(
      [
        sub({ id: 'late', status: 'past_due', created_at: '2026-01-01T00:00:00Z' }),
        sub({ id: 'ending', cancel_at_period_end: true, created_at: '2026-01-02T00:00:00Z' }),
        sub({ id: 'new', created_at: '2026-03-01T00:00:00Z' }),
        sub({ id: 'old', created_at: '2026-02-01T00:00:00Z' }),
      ],
      tokens
    );
    expect(rows.map((r) => r.sub.id)).toEqual(['old', 'new', 'ending', 'late']);
  });

  it('copes with nothing at all', () => {
    expect(buildSubscriptionRows(undefined, undefined)).toEqual([]);
    expect(buildSubscriptionRows([], [])).toEqual([]);
  });
});

describe('formatEndsOn', () => {
  it('formats a real date', () => {
    expect(formatEndsOn('2030-06-15T12:00:00Z')).toContain('2030');
  });

  it('words an unknown or bad date so the sentence is still true', () => {
    expect(formatEndsOn(null)).toBe('the end of the billing period');
    expect(formatEndsOn(undefined)).toBe('the end of the billing period');
    expect(formatEndsOn('not-a-date')).toBe('the end of the billing period');
  });
});
