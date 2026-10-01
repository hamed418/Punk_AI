import { useRef, useState } from 'react';
import {
  Select,
  SegmentedControl,
  TextInput,
  Loader,
  Tooltip,
  Box,
  Accordion,
} from '@mantine/core';
import { Trash2, Upload, ImagePlus, Plus } from 'lucide-react';
import { uploadMediaAction } from '@/actions/chat.actions';
import type {
  EditorAd,
  EditorCarouselCard,
  EditorMediaRef,
  EditorOption,
} from '@/types/chat';
import {
  selectClassNames,
  segmentedControlClassNames,
  tooltipStyles,
  toSelectData,
  accordionClassNames,
  attachMedia,
  mediaKindOf,
  switchFormat,
} from './editorUtils';
import CopyField from './CopyField';
import PagePostPicker from './PagePostPicker';
import CarouselCards from './CarouselCards';
import CarouselFeedPreview from './CarouselFeedPreview';
import MediaThumb from './MediaThumb';
import AdFeedPreview from './AdFeedPreview';

interface Props {
  ad: EditorAd;
  pathPrefix: string;
  errors: Record<string, string>;
  ctas: EditorOption[];
  adFormats: EditorOption[];
  limits: {
    title_max: number;
    body_max: number;
    description_max: number;
    carousel_min_cards: number;
    carousel_max_cards: number;
    max_text_variants: number;
    max_media_per_ad: number;
  };
  canRemove: boolean;
  onRemove: () => void;
  patchAd: (p: Partial<EditorAd>) => void;
  patchCreative: (p: Partial<EditorAd['creative']>) => void;
  onAddAds: (patches?: Partial<EditorAd['creative']>[]) => void;
  onGenerate: () => void;
  requiresVideo?: boolean;
  objectStoryKind?: string;
  // Whether this conversion location PERMITS an existing post as an alternative
  // to composed copy (as opposed to objectStoryKind, which requires one).
  allowsExistingPost?: boolean;
  pageId?: string | null;
  // The Page's display name — shown on the live feed preview beside the form
  // ("Sponsored" line). Purely cosmetic; publishing still resolves the Page
  // from pageId.
  pageName?: string;
  // The intake form's "what your ad should be" answer. Only decides how an
  // untouched card opens — once anything is picked the spec speaks for itself.
  creativeSource?: string;
  // "Do it for me". That mode is never asked where the creative comes from —
  // a generated ad is the answer it exists to give — so the choice is not
  // offered here either. Same reasoning as the intake form's guide-only field.
  expressMode?: boolean;
  // Overrides the header name. Ads-only ("do it for me") passes one: `ad.name` is
  // built from ONE ad set ("Acme | Custom Audience Ad 1") but this card publishes
  // to every ad set, so its own name reads as a lie about where it runs.
  label?: string;
}

export default function AdCard({
  ad,
  pathPrefix,
  errors,
  ctas,
  adFormats,
  limits,
  canRemove,
  onRemove,
  // patchAd,
  patchCreative,
  onAddAds,
  onGenerate,
  requiresVideo,
  objectStoryKind,
  allowsExistingPost,
  pageId,
  pageName,
  creativeSource,
  expressMode,
  label,
}: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [open, setOpen] = useState(true);
  // Set when attachMedia turns a pick away for being the wrong kind. Cleared on
  // the next pick, so it reads as a response to what the user just did.
  const [refused, setRefused] = useState<string | null>(null);
  // Which card the carousel preview and card editor both show. Lives here,
  // not in CarouselCards, so the two agree on the open card.
  const [activeCardIndex, setActiveCardIndex] = useState(0);
  const c = ad.creative;
  const err = (k: string) => errors[`${pathPrefix}.${k}`];
  const format = c.format ?? 'SINGLE';
  const isCarousel = format === 'CAROUSEL';
  const cards = c.cards ?? [];
  const activeCard = Math.min(activeCardIndex, Math.max(cards.length - 1, 0));

  // Does this ad promote a post that already exists, rather than copy composed
  // here? Either platform counts.
  const promotesPost = !!(c.object_story_id || c.source_instagram_media_id);
  // Someone who answered "use a post from your Page" / "reuse a post from an
  // older ad" on the intake form is shown the picker straight away. Without
  // this the card opens on composed copy — promotesPost is false until a post
  // is actually picked — so the answer they gave changed nothing.
  // Which half of the choice the card is showing. Local state, because the
  // spec cannot answer it before a post is picked: "promote an existing post"
  // used to patch nothing, so the toggle sprang straight back to "write a new
  // ad" and the picker never opened. Seeded from the intake answer.
  const [useExistingPost, setUseExistingPost] = useState(
    promotesPost || (creativeSource ?? '').startsWith('existing')
  );
  // The boost destinations REQUIRE a post, so there is nothing to choose there.
  // Elsewhere the choice is offered only where it is known to work — see
  // DestinationRules.allows_existing_post, which is measured, not assumed.
  const canChooseSource =
    !objectStoryKind && allowsExistingPost && !expressMode;
  // promotesPost on its own, not only via canChooseSource: an express ad that
  // already carries a post (a reused template) must still show what it promotes,
  // even though express is not offered the choice.
  const showPostPicker =
    !!objectStoryKind || promotesPost || (canChooseSource && useExistingPost);

  // Variations — extra headlines/bodies and extra media — ride on an asset feed,
  // which a carousel (copy and media per card) and a boosted post (the post IS
  // the ad) have no room for. Those keep one headline, one body, one image. The
  // AI's copy dropdown is offered either way.
  const canVary = !isCarousel && !showPostPicker;

  // Every image/video on this ad — the primary first, then the combined extras.
  // The primary is a slot rather than a value: an ad with nothing attached still
  // shows one empty frame to upload into.
  const extraMedia = c.extra_media ?? [];
  const mediaSlots: EditorMediaRef[] = [c, ...extraMedia];
  const mediaCount =
    (c.media_id || c.image_hash || c.video_id ? 1 : 0) + extraMedia.length;
  const roomForMedia =
    canVary && mediaKindOf(c) !== 'video'
      ? limits.max_media_per_ad - mediaCount
      : Number(mediaCount === 0);
  const isGallery = mediaCount > 1;
  // Combining media on one ad works for images only — Meta strips videos out of
  // the asset feed. So an ad holding a video is full at one, and the picker below
  // narrows to images once anything is attached.
  const adKind = mediaKindOf(mediaSlots.find(mediaKindOf) ?? {});
  // Meta stores the combined media only when a text field also has more than one
  // option — a feed whose sole extra is media comes back empty and the ad runs
  // one image. Publish covers that by borrowing a second headline from the AI's
  // suggestions, so a gallery without a copy variant is only a problem when there
  // is nothing to borrow.
  const hasCopyVariant = Boolean(
    (c.title_variants ?? []).some(Boolean) || (c.body_variants ?? []).some(Boolean)
  );
  const canBorrowCopy = Boolean(
    (c.title_suggestions ?? []).some((t) => t && t !== c.title) ||
      (c.body_suggestions ?? []).some((b) => b && b !== c.body)
  );

  // Both directions of the switch — carrying every attached image/video along
  // either way — live in editorUtils so they are unit-tested there; see
  // editorUtils.check.ts.
  const changeFormat = (next: string) => {
    setActiveCardIndex(0);
    patchCreative(switchFormat(c, next, limits));
  };

  const patchCard = (i: number, patch: Partial<EditorCarouselCard>) =>
    patchCreative({
      cards: cards.map((card, idx) =>
        idx === i ? { ...card, ...patch } : card
      ),
    });

  const setVariants = (key: 'title_variants' | 'body_variants') => (
    (v: string[]) => patchCreative({ [key]: v.length ? v : null })
  );

  const patchExtras = (next: EditorMediaRef[]) =>
    patchCreative({ extra_media: next.length ? next : null });

  // Dropping the primary promotes the first extra rather than leaving a filled
  // ad with an empty first frame — the server rejects extras with no primary.
  const removeMedia = (i: number) => {
    if (i > 0) {
      patchExtras(extraMedia.filter((_, j) => j !== i - 1));
      return;
    }
    const [promoted, ...rest] = extraMedia;
    patchCreative({
      media_id: promoted?.media_id ?? null,
      media_url: promoted?.media_url ?? null,
      media_kind: promoted?.media_kind ?? null,
      image_hash: promoted?.image_hash ?? null,
      video_id: promoted?.video_id ?? null,
      extra_media: rest.length ? rest : null,
    });
  };

  // Move the combined media onto ads of their own — the other way Ads Manager
  // runs several creatives, and the one that reports per-image cost. `onAddAds`
  // clones this ad once per patch.
  const splitIntoAds = () => {
    if (!extraMedia.length) return;
    onAddAds(extraMedia.map((m) => ({ ...m, extra_media: null })));
    patchCreative({ extra_media: null });
  };

  // A multi-file pick fills the empty slots on THIS ad, which is what current
  // Ads Manager does: up to 10 media on one ad, combined with the copy per
  // viewer. Use "Split into separate ads" for one ad per image instead.
  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []).slice(0, roomForMedia);
    if (!files.length) return;
    setUploading(true);
    try {
      const results = await Promise.all(
        files.map((file) => {
          const fd = new FormData();
          fd.append('file', file);
          return uploadMediaAction(fd);
        })
      );
      const picked: EditorMediaRef[] = results
        .filter((res) => res.success && res.data)
        .map((res) => ({
          media_id: res.data!.id,
          media_url: res.data!.file_path,
          media_kind: (res.data!.media_type === 'video' ? 'video' : 'image') as
            | 'video'
            | 'image',
          image_hash: null,
          video_id: null,
        }));
      // With nothing attached yet the first upload becomes the primary; with a
      // primary already in place every upload joins the extras — of the same
      // kind only, which is what the refusal below reports.
      setRefused(null);
      patchCreative(
        attachMedia(c, picked, limits.max_media_per_ad, (n) =>
          setRefused(
            `${n === 1 ? 'One file was' : `${n} files were`} left out — Meta drops ` +
              `videos from an ad carrying several media, so a video needs an ad of ` +
              `its own. Use “Add another ad” below.`
          )
        )
      );
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const multiFileRef = useRef<HTMLInputElement>(null);
  const [carouselUploading, setCarouselUploading] = useState(false);

  const handleAddCard = () => {
    const last = cards[cards.length - 1];
    patchCreative({
      cards: [
        ...cards,
        {
          title: last?.title ?? c.title,
          body: last?.body ?? null,
          link: last?.link ?? c.link,
        },
      ],
    });
    setActiveCardIndex(cards.length);
  };

  const onCarouselMultiFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (!files.length) return;
    setCarouselUploading(true);
    try {
      const results = await Promise.all(
        files.map((file) => {
          const fd = new FormData();
          fd.append('file', file);
          return uploadMediaAction(fd);
        })
      );
      const picked = results
        .filter((res) => res.success && res.data)
        .map((res): EditorMediaRef => ({
          media_id: res.data!.id,
          media_url: res.data!.file_path,
          media_kind: res.data!.media_type === 'video' ? 'video' : 'image',
          image_hash: null,
          video_id: null,
        }));

      if (!picked.length) return;
      const next = cards.map((cardItem) => ({ ...cardItem }));
      let cursor = activeCard;
      let lastTouched = activeCard;
      for (const media of picked) {
        const emptyIdx = next.findIndex(
          (cardItem, i) => i >= cursor && !Boolean(cardItem.media_id || cardItem.image_hash || cardItem.video_id)
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
      patchCreative({ cards: next });
      setActiveCardIndex(lastTouched);
    } finally {
      setCarouselUploading(false);
      if (multiFileRef.current) multiFileRef.current.value = '';
    }
  };



  // "Add media" — the one control that can turn a single image into a
  // gallery (the preview card's own click only replaces the primary). Lives
  // under the gallery grid once there is one; under the preview card
  // otherwise — one element, two positions, so neither copy drifts.
  const addMediaButton = (
    <div className="flex w-full">
      <Tooltip
        label={
          roomForMedia <= 0 && adKind === 'video'
            ? 'A video ad carries one video — Meta drops the rest. Add another ad for a second video.'
            : roomForMedia <= 0
              ? `This ad already carries ${mediaCount} media — Meta's limit for one ad`
              : canVary
                ? `Add ${adKind ? `${adKind}s` : requiresVideo ? 'videos' : 'images or videos'} — up to ${limits.max_media_per_ad} on one ad, combined with your copy`
                : `Upload ${requiresVideo ? 'a video' : 'an image or video'}`
        }
        styles={tooltipStyles}
      >
        <button
          onClick={() => fileRef.current?.click()}
          disabled={roomForMedia <= 0}
          className="border-primary-text/8 cursor-pointer! text-secondary-text/90 bg-primary-text/5 flex w-full items-center justify-center gap-1.5 rounded-lg border py-1.5 text-[11px] shadow-[0px_8px_24px_0px_#00000080,0px_1px_0px_0px_#FFFFFF1F_inset] hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
        >
          {uploading ? (
            <Loader size={11} />
          ) : (
            <>
              <Upload size={12} />
            </>
          )}
        </button>
      </Tooltip>
    </div>
  );

  return (
    <div className="flex h-full min-h-0 w-full flex-1 flex-col overflow-hidden">
      {err('creative.format') && (
        <span className="mb-1 block px-5 pt-3 text-[11px] text-red-400">
          {err('creative.format')}
        </span>
      )}

      {/* Full-width Source Toggle (Write a new ad / Promote an existing post) at the very top */}
      {canChooseSource && (
        <div className="border-primary-text/8 shrink-0 border-b px-5 py-3">
          <SegmentedControl
            fullWidth
            size="sm"
            value={useExistingPost ? 'existing' : 'new'}
            onChange={(v) => {
              setUseExistingPost(v === 'existing');
              if (v !== 'existing') {
                patchCreative({
                  object_story_id: null,
                  source_instagram_media_id: null,
                });
              }
            }}
            data={[
              { value: 'new', label: 'Write a new ad' },
              { value: 'existing', label: 'Promote an existing post' },
            ]}
            classNames={segmentedControlClassNames}
          />
        </div>
      )}

      {showPostPicker ? (
        <div className="custom-scrollbar flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-5">
          <PagePostPicker
            kind={objectStoryKind || 'post'}
            pageId={pageId}
            value={c.object_story_id ?? null}
            igValue={c.source_instagram_media_id ?? null}
            allowInstagram={!objectStoryKind}
            creativeSource={creativeSource}
            onSelect={(source, id) =>
              patchCreative(
                source === 'instagram'
                  ? { source_instagram_media_id: id, object_story_id: null }
                  : { object_story_id: id, source_instagram_media_id: null }
              )
            }
            error={err('creative.object_story_id')}
          />
        </div>
      ) : (
        <div className="custom-scrollbar flex h-full min-h-0 w-full flex-1 flex-col lg:flex-row items-stretch overflow-y-auto lg:overflow-hidden">
          {/* Left Column: Form Controls (Scrollable) */}
          <div className="custom-scrollbar flex w-full shrink-0 flex-col gap-3.5 overflow-y-visible p-4 md:p-5 lg:min-h-0 lg:flex-1 lg:shrink lg:overflow-y-auto">
            {/* Format Toggle Pills (Single / Carousel) */}
            {adFormats.length > 1 && (
              <SegmentedControl
                fullWidth
                size="sm"
                value={format}
                onChange={changeFormat}
                data={adFormats.map((f) => ({
                  value: f.value,
                  label: f.label === 'Single image or video' ? 'Single image' : f.label === 'Carousel' ? 'Carousel image' : f.label,
                }))}
                classNames={segmentedControlClassNames}
              />
            )}

            {/* Headline */}
            {!isCarousel && (
              <CopyField
                label="Headline"
                withAsterisk
                value={c.title}
                suggestions={c.title_suggestions ?? []}
                maxLength={limits.title_max}
                error={err('creative.title')}
                onChange={(v) => patchCreative({ title: v })}
                variants={c.title_variants ?? []}
                onVariantsChange={
                  canVary ? setVariants('title_variants') : undefined
                }
                maxVariants={limits.max_text_variants}
              />
            )}

            {/* Body */}
            <CopyField
              label={isCarousel ? 'Primary text' : 'Body'}
              withAsterisk
              value={c.body}
              suggestions={c.body_suggestions ?? []}
              maxLength={limits.body_max}
              error={err('creative.body')}
              multiline
              onChange={(v) => patchCreative({ body: v })}
              variants={c.body_variants ?? []}
              onVariantsChange={
                canVary ? setVariants('body_variants') : undefined
              }
              maxVariants={limits.max_text_variants}
            />
            {isCarousel && (
              <span className="text-secondary-text/50 -mt-2 text-[11px]">
                Shown once, above all cards.
              </span>
            )}

            {/* Description */}
            {!isCarousel && (
              <CopyField
                label="Description"
                value={c.description ?? ''}
                suggestions={c.description_suggestions ?? (c.title_suggestions ?? [])}
                maxLength={limits.description_max}
                error={err('creative.description')}
                placeholder="Cruelty-Free & Vegan Formulas"
                onChange={(v) =>
                  patchCreative({
                    description: v || null,
                  })
                }
              />
            )}

            {/* Call to action */}
            <Select
              label="Call to action"
              data={toSelectData(ctas)}
              value={c.call_to_action}
              onChange={(v) => v && patchCreative({ call_to_action: v })}
              error={err('creative.call_to_action')}
              classNames={selectClassNames}
              comboboxProps={{ withinPortal: true, zIndex: 1000000 }}
            />

            {/* Link */}
            <TextInput
              label={isCarousel ? 'Link (Each card can override this.)' : 'Link'}
              placeholder="facebook.com/..."
              value={c.link}
              onChange={(e) =>
                patchCreative({ link: e.currentTarget.value })
              }
              error={err('creative.link')}
              classNames={selectClassNames}
            />

            {/* URL parameters */}
            <TextInput
              label="URL parameters (optional)"
              placeholder="utm_source=facebook&utm_medium=paid"
              value={c.url_tags ?? ''}
              onChange={(e) =>
                patchCreative({
                  url_tags: e.currentTarget.value || null,
                })
              }
              error={err('creative.url_tags')}
              classNames={selectClassNames}
            />

            {/* Media gallery upload controls if gallery mode */}
            {isGallery && (
              <div className="flex flex-col gap-2 pt-2 border-t border-primary-text/6">
                <span className="text-[12px] font-semibold text-primary-text/80">
                  Media gallery ({mediaCount}/{limits.max_media_per_ad})
                </span>
                <div className="grid grid-cols-4 gap-1.5">
                  {mediaSlots.map((m, i) => (
                    <button
                      key={m.media_id ?? m.image_hash ?? m.video_id ?? i}
                      onClick={() => removeMedia(i)}
                      title="Remove this media"
                      className="border-primary-text/8 bg-primary-text/1 group relative aspect-square overflow-hidden rounded-lg border"
                    >
                      <MediaThumb m={m} />
                      <span className="absolute inset-0 hidden items-center justify-center bg-black/60 group-hover:flex">
                        <Trash2 size={14} className="text-white" />
                      </span>
                    </button>
                  ))}
                </div>
                {addMediaButton}
              </div>
            )}

            {/* Carousel cards sub-list inside scrollable form */}
            {isCarousel && (
              <CarouselCards
                cards={cards}
                pathPrefix={pathPrefix}
                errors={errors}
                limits={limits}
                activeIndex={activeCard}
                onSelectCard={setActiveCardIndex}
                patchCard={patchCard}
                onAdd={() => {
                  const last = cards[cards.length - 1];
                  patchCreative({
                    cards: [
                      ...cards,
                      {
                        title: last?.title ?? c.title,
                        body: last?.body ?? null,
                        link: last?.link ?? c.link,
                      },
                    ],
                  });
                  setActiveCardIndex(cards.length);
                }}
                onRemove={(i) => {
                  patchCreative({
                    cards: cards.filter((_x, idx) => idx !== i),
                  });
                  if (i <= activeCard && activeCard > 0) {
                    setActiveCardIndex(activeCard - 1);
                  }
                }}
                onReorder={(from, to) => {
                  const next = cards.slice();
                  const [moved] = next.splice(from, 1);
                  next.splice(to, 0, moved);
                  patchCreative({ cards: next });
                  if (activeCard === from) setActiveCardIndex(to);
                }}
              />
            )}

            {!isCarousel && (
              <input
                ref={fileRef}
                type="file"
                multiple
                accept={
                  adKind
                    ? `${adKind}/*`
                    : requiresVideo
                      ? 'video/*'
                      : 'image/*,video/*'
                }
                className="hidden"
                onChange={onFile}
              />
            )}
          </div>

          {/* Right Column: Live Feed Preview (Fixed in place) */}
          <div className="border-primary-text/8 flex w-full lg:w-[320px] shrink-0 flex-col justify-start overflow-hidden border-t lg:border-t-0 lg:border-l p-4 md:p-5 xl:w-[350px]">
            <div className="flex flex-col gap-2.5">
              {isCarousel ? (
                <>
                  <CarouselFeedPreview
                    cards={cards}
                    activeIndex={activeCard}
                    onSelect={setActiveCardIndex}
                    pageName={pageName}
                    body={c.body}
                    callToAction={c.call_to_action}
                  />

                  {/* Carousel Actions: Full-width Icon Buttons */}
                  <div className="flex w-full items-center gap-2 pt-1">
                    <Tooltip label="Upload images" styles={tooltipStyles} className="flex-1">
                      <button
                        type="button"
                        onClick={() => multiFileRef.current?.click()}
                        disabled={carouselUploading}
                        aria-label="Upload images"
                        className="border-primary-text/12 bg-primary-text/6 hover:bg-primary-text/10 text-primary-text/85 hover:text-primary-text flex h-8.5 w-full flex-1 cursor-pointer items-center justify-center rounded-xl border transition-all shadow-[0px_1px_0px_0px_#FFFFFF1F_inset,0px_2px_6px_0px_#00000033]"
                      >
                        {carouselUploading ? (
                          <Loader size={13} />
                        ) : (
                          <ImagePlus size={16} />
                        )}
                      </button>
                    </Tooltip>

                    <Tooltip label="Add card" styles={tooltipStyles} className="flex-1">
                      <button
                        type="button"
                        onClick={handleAddCard}
                        disabled={cards.length >= limits.carousel_max_cards}
                        aria-label="Add card"
                        className="border-primary-text/12 bg-primary-text/6 hover:bg-primary-text/10 text-primary-text/85 hover:text-primary-text flex h-8.5 w-full flex-1 cursor-pointer items-center justify-center rounded-xl border transition-all shadow-[0px_1px_0px_0px_#FFFFFF1F_inset,0px_2px_6px_0px_#00000033] disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        <Plus size={16} />
                      </button>
                    </Tooltip>
                  </div>

                  <input
                    ref={multiFileRef}
                    type="file"
                    multiple
                    accept="image/*,video/*"
                    className="hidden"
                    onChange={onCarouselMultiFile}
                  />
                </>
              ) : (
                <AdFeedPreview
                  creative={c}
                  pageName={pageName}
                  interactive={!isGallery}
                  uploading={uploading}
                  onUploadClick={() => fileRef.current?.click()}
                  onReplaceClick={() => {
                    removeMedia(0);
                    fileRef.current?.click();
                  }}
                  onDelete={() => removeMedia(0)}
                />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
