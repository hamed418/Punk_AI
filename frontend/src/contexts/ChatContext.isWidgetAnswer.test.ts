import { describe, expect, it } from 'vitest';
import { isWidgetAnswer } from './ChatContext';

describe('isWidgetAnswer', () => {
  it('matches the Q:/A: wrapper most widgets send', () => {
    expect(isWidgetAnswer('Q: Pick one\nA: yes')).toBe(true);
  });

  it('matches bare JSON — CampaignEditor sends {"action","spec"} with no wrapper', () => {
    expect(isWidgetAnswer('{"action":"publish","spec":{}}')).toBe(true);
    expect(isWidgetAnswer('[{"name":"Park"}]')).toBe(true);
  });

  it('rejects a plain typed follow-up', () => {
    expect(isWidgetAnswer('actually, change the budget to $50/day')).toBe(false);
  });
});
