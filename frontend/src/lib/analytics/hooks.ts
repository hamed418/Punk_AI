'use client';

import { trackEvent, identifyUser, resetUser, setPersonProperties, optInTracking, optOutTracking, hasConsented } from './posthog';
import { EventRegistry, AnalyticsEventName } from './events';

export function useAnalytics() {
  return {
    track: <E extends AnalyticsEventName>(event: E, props: EventRegistry[E]) => trackEvent(event, props),
    identify: (id: string, traits?: Record<string, unknown>) => identifyUser(id, traits),
    reset: () => resetUser(),
    setPersonProperties: (props: Record<string, unknown>) => setPersonProperties(props),
    optIn: () => optInTracking(),
    optOut: () => optOutTracking(),
    hasConsented: () => hasConsented(),
  };
}
