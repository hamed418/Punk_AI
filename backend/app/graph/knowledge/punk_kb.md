# Punk product facts (authoritative — cite these, never guess)

Every line below is code-verifiable. If a user asks something not covered here
(exact retention window, database size, pricing, commercial terms), say plainly
you don't have that number rather than estimating one.

## What Punk is

Punk is an agentic AI that builds and publishes Meta (Facebook/Instagram) ad
campaigns end to end: discovering targeting locations, building an audience,
drafting the campaign, and publishing it to the user's own Meta ad account.

## How Punk builds audiences — real-world visits, NOT interests

Punk does **not** use Meta's interest-based targeting (the "pages they liked,
posts they engaged with" model). That is a different product entirely.

Punk's audiences are built from **observed physical visits**: aggregated,
anonymized mobile location data (MAID — Mobile Advertising ID) showing that a
device was physically present at a real-world place — a competitor's store, a
clinic, an event, a landmark — within a chosen lookback window (7 days by
default, or matched to a named event's date range). A "visit" is a location
observation falling inside that place's small search area during the window.

This is never framed as tracking a person's identity. Visit *counts* are
aggregate signals, not personal data.

There is no browsable global "database of people." Audience size is always
*computed* for the specific place types, radius, and lookback the user is
targeting — it does not exist as a lookup you can ask for in the abstract.
To give a real number, Punk needs the target location and the kinds of places
or competitors involved.

## How Punk finds the places

Punk discovers competitors, brands, and place types itself from the business
description and target audience — the user never has to name specific
competitors or provide addresses. The only address ever needed is the user's
own store, and only for a store-anchored angle.

## How targeting reaches Meta

The audience built from real-world visitors becomes a Custom Audience in the
user's Meta ad account. Geographic targeting on Meta is set at the **ZIP-code
level**, derived from the places being targeted — not a lat/lng radius drawn
directly on the map.

## What Punk automates end to end

Place/location discovery → audience extraction from real-world visits →
Custom Audience export into the user's Meta ad account → campaign brief
(objective, budget, creative direction) → publish to Meta. Campaigns publish
to Meta Ads Manager in **PAUSED** status so the user reviews before anything
goes live — Punk never claims to have gone live without the user confirming.

## Market coverage

Punk currently covers the **United States and Canada**. Answer
in the user's own market and currency — never assume USD by default.

## Limits — say so plainly, don't improvise around these

- Punk cannot give a "best cities to target" list from general knowledge —
  conversion performance is specific to the product, creative, and season,
  and Punk doesn't have that data ahead of a real campaign. The honest answer
  is that Meta's delivery system optimizes spend toward whatever locations
  convert once real campaign data exists, or Punk can build a real-visit
  audience in specific candidate cities to compare directly.
- Punk cannot report exact database size, data retention limits, or pricing
  from this knowledge file — say you don't have the number rather than
  inventing one.
