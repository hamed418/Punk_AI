// Turns the user's subscriptions into the cards the Billing tab shows.
//
// Punk sells one subscription per Meta ad account, so the tab needs one card per
// paid account — each with its own Cancel. Pure on purpose: vitest here runs in a
// node environment with no DOM, so keeping this out of the component is what makes
// the rules testable.

export interface SubscriptionLike {
  id: string;
  status: string;
  ad_account_id?: string | null;
  cancel_at_period_end?: boolean;
  current_period_end?: string | null;
  created_at?: string | null;
}

export interface OauthLike {
  accessible_accounts?: { id: string; name: string }[] | null;
}

// active  — running, can be cancelled
// ending  — cancel-at-period-end is set: still running, stops on `endsOn`
// past_due — the latest payment failed; fixing the card is a Stripe-side action
export type RowState = 'active' | 'ending' | 'past_due';

export interface SubscriptionRow<T extends SubscriptionLike> {
  sub: T;
  accountId: string | null;
  accountName: string;
  state: RowState;
  endsOn: string | null;
}

const RUNNING = new Set(['active', 'trialing']);
const LIVE = new Set(['active', 'trialing', 'past_due']);
const ORDER: Record<RowState, number> = { active: 0, ending: 1, past_due: 2 };

export function buildSubscriptionRows<T extends SubscriptionLike>(
  subscriptions: readonly T[] | null | undefined,
  oauthTokens: readonly OauthLike[] | null | undefined
): SubscriptionRow<T>[] {
  const names = new Map<string, string>();
  for (const token of oauthTokens ?? []) {
    for (const acc of token.accessible_accounts ?? []) names.set(acc.id, acc.name);
  }

  return (subscriptions ?? [])
    .filter((sub) => LIVE.has(sub.status))
    .map((sub, index) => {
      const accountId = sub.ad_account_id ?? null;
      // past_due wins over a scheduled cancel: a failed payment is the more urgent
      // thing to tell the user.
      const state: RowState =
        sub.status === 'past_due'
          ? 'past_due'
          : RUNNING.has(sub.status) && sub.cancel_at_period_end
            ? 'ending'
            : 'active';
      return {
        row: {
          sub,
          accountId,
          accountName: accountId ? (names.get(accountId) ?? accountId) : 'Unassigned',
          state,
          endsOn: sub.current_period_end ?? null,
        } satisfies SubscriptionRow<T>,
        index,
      };
    })
    .sort(
      (a, b) =>
        ORDER[a.row.state] - ORDER[b.row.state] ||
        (a.row.sub.created_at ?? '').localeCompare(b.row.sub.created_at ?? '') ||
        a.index - b.index
    )
    .map(({ row }) => row);
}

// The period end can be unknown (checkout does not write it; a later webhook does),
// so callers get wording that is true either way.
export function formatEndsOn(iso: string | null | undefined): string {
  if (!iso) return 'the end of the billing period';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'the end of the billing period';
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}
