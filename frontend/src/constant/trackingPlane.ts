import type { TrackingMethod } from '@/types/chat';

// What Punk does, and where the conversion data actually goes.
//
// The first clause is deliberately identical in all five: Punk's job is the
// control plane — the promoted_object on the ad set, the optimization goal, the
// Page subscription, the diagnostics read back — and that half never varies.
// Only the second clause moves, and that is the whole distinction nothing in the
// product stated out loud. An advertiser (and, it turned out, the person who
// built this) could not tell whether Punk was the server their conversions pass
// through. For three of these five it is not, and for pixel_only — the express
// default — nothing about their customers reaches Punk at all.
//
// '' is keyed too: a row predating the column never answered the question, and
// TrackingService treats an empty method as "both halves are still on offer".
export const TRACKING_PLANE: Record<TrackingMethod | '', string> = {
  pixel_only:
    'Punk configures your Meta ad account and reads your results back; your website tag reports conversions straight to Meta, so none of that data passes through Punk.',
  pixel_and_server:
    'Punk configures your Meta ad account and reads your results back; your website tag reports straight to Meta, and your server posts each conversion through Punk, which hashes it and forwards it to your own dataset.',
  // ponytail: "no names or emails" is true of the code today (_forward_lead
  // sends lead_id alone) but the MATCHING it implies is unverified — nobody has
  // read Event Match Quality for a lead_id-only Lead against a live event. If it
  // scores near zero, fetch_lead comes back and this sentence has to change.
  lead_forms:
    "Punk configures your Meta ad account and reads your results back; Meta pushes each instant-form lead to Punk, which reports it to your own dataset using Meta's lead id — no names or emails.",
  offline_crm:
    'Punk configures your Meta ad account and reads your results back; your CRM posts each closed sale through Punk, which hashes it and forwards it to your own dataset.',
  '': 'Punk configures your Meta ad account and reads your results back; you have not said how conversions reach Meta yet, so both halves — the website tag and the server endpoint — are still on offer.',
};
