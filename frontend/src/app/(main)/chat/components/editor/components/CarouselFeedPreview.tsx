import type { EditorCarouselCard } from '@/types/chat';
import MediaThumb from './MediaThumb';

interface Props {
  cards: EditorCarouselCard[];
  activeIndex: number;
  onSelect: (i: number) => void;
  pageName?: string;
  // The shared primary text (creative.body) — a carousel's headline and
  // description live per card, but the primary text above the cards is the
  // ad-level field, same as Meta actually renders it.
  body: string;
  callToAction: string;
}

/**
 * The carousel's own feed-style preview, beside CarouselFeedPreview's sibling
 * AdFeedPreview — same chrome (page header, primary text, bottom headline/CTA
 * bar), a swipeable card strip in place of the single media slot. Card
 * management (replace/delete/add, drag to reorder) stays in CarouselCards
 * below; this is what the ad actually looks like, and clicking a card here
 * only changes which one that panel is editing.
 */
export default function CarouselFeedPreview({
  cards,
  activeIndex,
  onSelect,
  pageName,
  body,
  callToAction,
}: Props) {
  const active = cards[Math.min(activeIndex, Math.max(cards.length - 1, 0))];
  const ctaLabel = callToAction?.replace(/_/g, ' ') || 'Learn More';

  return (
    <div className="border-primary-text/8 bg-primary-text/3 flex flex-col gap-3 rounded-2xl border px-2.5 pt-2.5 pb-1.75">
      {/* Page header — identical to AdFeedPreview */}
      <div className="flex items-center gap-1.75">
        <div className="border-primary-text/10 bg-primary-text/8 text-primary-text flex h-8 w-8 items-center justify-center overflow-hidden rounded-full border text-xs font-semibold">
          {(pageName || 'P').charAt(0).toUpperCase()}
        </div>
        <div className="flex flex-col">
          <span className="text-primary-text text-[11px] leading-tight font-bold">
            {pageName || 'Your Page'}
          </span>
          <span className="text-primary-text/35 mt-1 text-[9px] leading-tight">
            Sponsored · ⊙
          </span>
        </div>
      </div>

      {/* Body text */}
      <p className="text-primary-text/65 mb-2 text-[11px] leading-relaxed whitespace-pre-wrap">
        {body || 'Your ad copy will appear here.'}
      </p>

      {/* The cards, swipeable — click one to edit it below */}
      <div className="-mx-0.5 flex snap-x snap-mandatory gap-1.5 overflow-x-auto px-0.5 pb-1">
        {cards.map((card, i) => {
          const isActive = i === activeIndex;
          return (
            <button
              key={i}
              type="button"
              onClick={() => onSelect(i)}
              className={`relative aspect-square w-24 shrink-0 snap-start overflow-hidden rounded-lg border transition-colors ${
                isActive
                  ? 'border-white/70'
                  : 'border-primary-text/8 hover:border-primary-text/30'
              }`}
            >
              <MediaThumb m={card} iconSize={18} />
            </button>
          );
        })}
      </div>

      {/* Bottom bar — the active card's own headline, since that's the one
          Meta shows while it's the card in view. */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="text-primary-text truncate text-[11px] font-bold">
            {active?.title || 'Card headline'}
          </span>
        </div>
        <span className="border-primary-text/12 bg-primary-text/8 text-primary-text shrink-0 rounded-[6px] border px-2.5 py-1 text-[10px] font-bold shadow-[0px_1px_0px_0px_#FFFFFF1F_inset]">
          {ctaLabel}
        </span>
      </div>
      <div className="text-primary-text/25 -mt-1 text-center text-[9px]">
        Swipe · {cards.length} card{cards.length === 1 ? '' : 's'}
      </div>
    </div>
  );
}
