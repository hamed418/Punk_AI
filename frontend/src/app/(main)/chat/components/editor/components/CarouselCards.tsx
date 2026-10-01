import { useRef, useState } from 'react';
import { TextInput, Loader } from '@mantine/core';
import { Plus, Trash2, ImagePlus, ChevronsUpDown } from 'lucide-react';
import type { EditorCarouselCard, EditorMediaRef } from '@/types/chat';
import { selectClassNames } from './editorUtils';
import { softLabel } from './CopyField';
import { uploadMediaAction } from '@/actions/chat.actions';
import MediaThumb from './MediaThumb';

interface Props {
  cards: EditorCarouselCard[];
  pathPrefix: string;
  errors: Record<string, string>;
  limits: {
    title_max: number;
    body_max: number;
    carousel_min_cards: number;
    carousel_max_cards: number;
  };
  // Which card the strip and the editor panel below both show — owned by
  // AdCard so the feed preview beside this component agrees on the same card.
  activeIndex: number;
  onSelectCard: (i: number) => void;
  patchCard: (i: number, p: Partial<EditorCarouselCard>) => void;
  onAdd: () => void;
  onRemove: (i: number) => void;
  onReorder: (from: number, to: number) => void;
}

function getLinkAndParams(link: string): { url: string; params: string } {
  try {
    const u = new URL(link);
    const params = u.search.startsWith('?') ? u.search.substring(1) : '';
    const baseUrl = `${u.origin}${u.pathname}`;
    return { url: baseUrl, params };
  } catch {
    const parts = link.split('?');
    return {
      url: parts[0] || '',
      params: parts[1] || '',
    };
  }
}

function mergeLinkAndParams(url: string, params: string): string {
  const cleanUrl = url.split('?')[0];
  if (!params.trim()) return cleanUrl;
  return `${cleanUrl}?${params.trim()}`;
}

const hasMedia = (m: EditorMediaRef) =>
  Boolean(m.media_id || m.image_hash || m.video_id);

const cardInputClassNames = {
  ...selectClassNames,
  description: 'text-[11px]! text-secondary-text/50! mb-1.5!',
};

export default function CarouselCards({
  cards,
  pathPrefix,
  errors,
  limits,
  activeIndex,
  onSelectCard,
  patchCard,
  onAdd,
  onRemove,
  onReorder,
}: Props) {
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const multiFileRef = useRef<HTMLInputElement>(null);
  // The tile currently being dragged, for the HTML5 DnD handlers below.
  const dragFrom = useRef<number | null>(null);

  // clamp active in case cards length changes
  const active = Math.min(activeIndex, cards.length - 1);
  const card = cards[active];

  const uploadFiles = async (files: File[]) => {
    const results = await Promise.all(
      files.map((file) => {
        const fd = new FormData();
        fd.append('file', file);
        return uploadMediaAction(fd);
      })
    );
    return results
      .filter((res) => res.success && res.data)
      .map(
        (res): EditorMediaRef => ({
          media_id: res.data!.id,
          media_url: res.data!.file_path,
          media_kind: res.data!.media_type === 'video' ? 'video' : 'image',
          image_hash: null,
          video_id: null,
        })
      );
  };

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const [picked] = await uploadFiles([file]);
      if (picked) patchCard(active, picked);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  // One pick, up to 10 images: fills whichever cards have no media yet
  // (starting at the active one), appends fresh cards while there's room,
  // then — once both are exhausted — overwrites starting at the active card.
  // Ten images no longer means ten trips through a single-file dialog.
  const onMultiFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (!files.length) return;
    setUploading(true);
    try {
      const picked = await uploadFiles(files);
      if (!picked.length) return;
      const next = cards.map((c) => ({ ...c }));
      let cursor = active;
      let lastTouched = active;
      for (const media of picked) {
        const emptyIdx = next.findIndex(
          (c, i) => i >= cursor && !hasMedia(c)
        );
        if (emptyIdx !== -1) {
          next[emptyIdx] = { ...next[emptyIdx], ...media };
          lastTouched = emptyIdx;
          cursor = emptyIdx + 1;
          continue;
        }
        if (next.length < limits.carousel_max_cards) {
          const last = next[next.length - 1];
          next.push({
            title: last?.title ?? '',
            body: last?.body ?? null,
            link: last?.link ?? '',
            ...media,
          });
          lastTouched = next.length - 1;
          cursor = next.length;
          continue;
        }
        const idx = Math.min(cursor, next.length - 1);
        next[idx] = { ...next[idx], ...media };
        lastTouched = idx;
        cursor = idx + 1;
      }
      // Bulk-replace via as many patchCard calls as cards actually changed —
      // cheaper than threading a whole-array replace prop through for what is
      // otherwise a single-card-at-a-time component.
      next.forEach((c, i) => {
        if (c !== cards[i]) patchCard(i, c);
      });
      onSelectCard(lastTouched);
    } finally {
      setUploading(false);
      if (multiFileRef.current) multiFileRef.current.value = '';
    }
  };

  const onDrop = (to: number) => {
    const from = dragFrom.current;
    dragFrom.current = null;
    if (from === null || from === to) return;
    onReorder(from, to);
  };

  const { url, params } = card ? getLinkAndParams(card.link) : { url: '', params: '' };

  // A card's own errors only render while it is the open one, so nothing marked
  // card 3 while card 0 was on screen. The thumbnail carries the mark instead.
  const cardHasError = (i: number) =>
    Object.keys(errors).some((k) =>
      k.startsWith(`${pathPrefix}.creative.cards[${i}].`)
    );

  return (
    <div className="mt-3 flex flex-col gap-2.5">
      {/* Header section */}
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-0.5">
          <span className="text-secondary-text/80 text-[11px] font-medium tracking-wide uppercase">
            Cards ({cards.length}/{limits.carousel_max_cards})
          </span>
          <span className="text-secondary-text/50 text-[11px]">
            Drag to reorder. Click a card to edit it below.
          </span>
        </div>
      </div>

      {errors[`${pathPrefix}.creative.cards`] && (
        <span className="text-[11px] text-red-400">
          {errors[`${pathPrefix}.creative.cards`]}
        </span>
      )}

      {/* Thumbnails Row */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1.5">
        {cards.map((c, i) => {
          const isActive = i === active;
          const broken = cardHasError(i);
          return (
            <div
              key={i}
              draggable
              onDragStart={() => {
                dragFrom.current = i;
              }}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => onDrop(i)}
              onClick={() => onSelectCard(i)}
              className={`relative h-16 w-16 shrink-0 cursor-grab overflow-hidden rounded-xl border flex items-center justify-center bg-[#00000003] transition-all active:cursor-grabbing ${
                broken
                  ? 'border-red-400/80'
                  : isActive
                    ? 'border-white/80 shadow-[0px_4px_12px_#00000080]'
                    : 'border-underline/15 hover:border-white/40'
              }`}
            >
              {/* Badge/number */}
              <span className="absolute top-1 left-1 bg-black/60 text-white text-[9px] font-bold h-3.5 w-3.5 rounded flex items-center justify-center z-10">
                {i + 1}
              </span>

              <MediaThumb m={c} iconSize={18} />
            </div>
          );
        })}

        {/* Plus dotted box */}
        {cards.length < limits.carousel_max_cards && (
          <div
            onClick={onAdd}
            className="h-16 w-16 shrink-0 border border-dashed border-underline/30 hover:border-white/40 rounded-xl flex items-center justify-center bg-white/1 cursor-pointer transition-all"
          >
            <Plus size={18} className="text-secondary-text/60" />
          </div>
        )}
      </div>

      {/* Selected Card Editor Panel */}
      {card && (
        <div className="border border-underline/15 bg-white/2 p-4 rounded-2xl flex flex-col gap-4 mt-1">
          {/* Active Card Info / Replace Image Header */}
          <div className="flex items-center gap-3">
            <div className="h-12 w-12 rounded-lg bg-white/3 border border-underline/10 overflow-hidden flex items-center justify-center shrink-0">
              <MediaThumb m={card} iconSize={16} />
            </div>

            <div className="flex flex-col gap-0.5">
              <span className="text-primary-text text-[13px] font-medium">
                Editing card {active + 1} of {cards.length}
              </span>
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                disabled={uploading}
                className="text-secondary-text/60 text-[11px] font-medium hover:text-white underline cursor-pointer text-left flex items-center gap-1 disabled:opacity-50"
              >
                {uploading ? (
                  <>
                    <Loader size={10} />
                    Replacing...
                  </>
                ) : (
                  'Replace image'
                )}
              </button>
            </div>

            {cards.length > limits.carousel_min_cards && (
              <button
                type="button"
                onClick={() => onRemove(active)}
                className="ml-auto text-secondary-text/60 hover:text-red-400 flex h-7 w-7 items-center justify-center rounded-full hover:bg-red-500/10 cursor-pointer"
                title="Delete this card"
              >
                <Trash2 size={14} />
              </button>
            )}
          </div>

          <input
            ref={fileRef}
            type="file"
            accept="image/*,video/*"
            className="hidden"
            onChange={onFile}
          />

          {errors[`${pathPrefix}.creative.cards[${active}].media`] && (
            <span className="text-[11px] text-red-400">
              {errors[`${pathPrefix}.creative.cards[${active}].media`]}
            </span>
          )}

          {/* Form Fields */}
          <TextInput
            label={softLabel('Card headline', card.title.length, limits.title_max)}
            withAsterisk
            placeholder="e.g. Card Headline"
            value={card.title}
            maxLength={limits.title_max}
            onChange={(e) => patchCard(active, { title: e.currentTarget.value })}
            error={errors[`${pathPrefix}.creative.cards[${active}].title`]}
            classNames={cardInputClassNames}
            rightSection={<ChevronsUpDown size={13} className="text-secondary-text/50" />}
          />

          <TextInput
            label={softLabel(
              'Card description (optional)',
              (card.body ?? '').length,
              limits.body_max
            )}
            placeholder="e.g. Card description or key feature"
            value={card.body ?? ''}
            maxLength={limits.body_max}
            onChange={(e) =>
              patchCard(active, { body: e.currentTarget.value || null })
            }
            classNames={cardInputClassNames}
          />

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <TextInput
              label="Card link"
              withAsterisk
              description="Overrides the ad-level link."
              placeholder="https://example.com/product"
              value={url}
              onChange={(e) => {
                const nextUrl = e.currentTarget.value;
                patchCard(active, { link: mergeLinkAndParams(nextUrl, params) });
              }}
              error={errors[`${pathPrefix}.creative.cards[${active}].link`]}
              classNames={cardInputClassNames}
            />

            <TextInput
              label="Card URL parameters"
              description="Overrides the ad-level params."
              placeholder="Same as above"
              value={params}
              onChange={(e) => {
                const nextParams = e.currentTarget.value;
                patchCard(active, { link: mergeLinkAndParams(url, nextParams) });
              }}
              classNames={cardInputClassNames}
            />
          </div>
        </div>
      )}
    </div>
  );
}
