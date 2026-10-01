import { useMemo, useRef, useState } from 'react';
import { uploadMediaAction } from '@/actions/chat.actions';
import type {
  CampaignEditorSpec,
  EditorAd,
  EditorCarouselCard,
  EditorCatalog,
  EditorDestination,
  EditorMediaRef,
} from '@/types/chat';
import { attachMedia, mediaKindOf } from '../../editorUtils';
import type { CreativeLimits, FlattenedAdItem } from '../types';

interface UseCampaignAssetsModalStateParams {
  spec: CampaignEditorSpec;
  catalog: EditorCatalog;
  adsOnly: boolean;
  destinations: EditorDestination[];
  patchCreative: (
    a: number,
    d: number,
    p: Partial<EditorAd['creative']>
  ) => void;
}

export function useCampaignAssetsModalState({
  spec,
  catalog,
  adsOnly,
  destinations,
  patchCreative,
}: UseCampaignAssetsModalStateParams) {
  const [activeFlatAdIndex, setActiveFlatAdIndex] = useState(0);
  const [carouselTab, setCarouselTab] = useState<'shared' | 'card'>('shared');
  const [activeCardIndex, setActiveCardIndex] = useState(0);
  const [uploading, setUploading] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const multiFileInputRef = useRef<HTMLInputElement>(null);
  const replaceFileInputRef = useRef<HTMLInputElement>(null);

  // Flatten all ads across adsets for smooth pagination
  const flattenedAds = useMemo<FlattenedAdItem[]>(() => {
    const list: FlattenedAdItem[] = [];
    const sets = adsOnly ? spec.adsets.slice(0, 1) : spec.adsets;
    sets.forEach((as, aIdx) => {
      as.ads.forEach((ad, dIdx) => {
        list.push({ adsetIndex: aIdx, adIndex: dIdx, adset: as, ad });
      });
    });
    return list;
  }, [spec.adsets, adsOnly]);

  const currentFlatItem =
    flattenedAds[
      Math.min(activeFlatAdIndex, Math.max(0, flattenedAds.length - 1))
    ];
  const aIdx = currentFlatItem?.adsetIndex ?? 0;
  const dIdx = currentFlatItem?.adIndex ?? 0;
  const currentAdSet = currentFlatItem?.adset ?? spec.adsets[0];
  const currentAd = currentFlatItem?.ad ?? currentAdSet?.ads[0];
  const creative = currentAd?.creative;

  const limits: CreativeLimits = catalog.creative_limits ?? {
    title_max: 255,
    body_max: 2200,
    description_max: 255,
    description_recommended: 30,
    carousel_min_cards: 2,
    carousel_max_cards: 10,
    max_text_variants: 5,
    max_media_per_ad: 10,
  };

  const currentDest =
    destinations.find((d) => d.value === currentAdSet?.destination_type) ??
    destinations[0];
  const ctas = currentDest?.call_to_actions ?? [];

  const format = creative?.format ?? 'SINGLE';
  const isCarousel = format === 'CAROUSEL';
  const cards = creative?.cards ?? [];
  const safeActiveCardIndex = Math.min(
    activeCardIndex,
    Math.max(0, (cards.length || 1) - 1)
  );
  const currentCard = cards[safeActiveCardIndex];

  const extraMedia = creative?.extra_media ?? [];
  const mediaSlots: EditorMediaRef[] = creative
    ? [creative, ...extraMedia]
    : [];
  const primaryMediaUrl = creative?.media_url;
  const hasMediaAttached = Boolean(
    creative?.media_id ||
      creative?.image_hash ||
      creative?.video_id ||
      primaryMediaUrl
  );

  const patchCurrentCreative = (patch: Partial<EditorAd['creative']>) => {
    patchCreative(aIdx, dIdx, patch);
  };

  const patchCard = (cardIdx: number, patch: Partial<EditorCarouselCard>) => {
    const nextCards = cards.map((c, i) =>
      i === cardIdx ? { ...c, ...patch } : c
    );
    patchCreative(aIdx, dIdx, { cards: nextCards });
  };

  const handleAddCard = () => {
    if (cards.length >= limits.carousel_max_cards) return;
    const lastCard = cards[cards.length - 1];
    const newCard: EditorCarouselCard = {
      title: lastCard?.title ?? creative?.title ?? '',
      body: lastCard?.body ?? null,
      link: lastCard?.link ?? creative?.link ?? '',
      media_id: null,
      media_url: null,
      media_kind: 'image',
    };
    const newCards = [...cards, newCard];
    patchCreative(aIdx, dIdx, { cards: newCards });
    setActiveCardIndex(newCards.length - 1);
    setCarouselTab('card');
  };

  const handleRemoveCard = (cardIdx: number) => {
    if (cards.length <= limits.carousel_min_cards) return;
    const nextCards = cards.filter((_, idx) => idx !== cardIdx);
    patchCreative(aIdx, dIdx, { cards: nextCards });
    if (safeActiveCardIndex >= nextCards.length) {
      setActiveCardIndex(Math.max(0, nextCards.length - 1));
    }
  };

  const getMediaFileName = (url?: string | null) => {
    if (!url) return 'media-asset.jpg';
    try {
      const cleanUrl = url.split('?')[0].split('#')[0];
      const name = cleanUrl.substring(cleanUrl.lastIndexOf('/') + 1);
      if (name && name.includes('.')) {
        return decodeURIComponent(name);
      }
      return `${name || 'media-asset'}.${mediaKindOf(creative!) === 'video' ? 'mp4' : 'jpg'}`;
    } catch {
      return 'media-asset.jpg';
    }
  };

  // Handle format change between SINGLE and CAROUSEL
  const handleFormatChange = (next: string) => {
    if (next === format || !creative) return;
    if (next === 'CAROUSEL') {
      const attached = mediaSlots.filter(
        (m) => m.media_id || m.image_hash || m.video_id || m.media_url
      );
      const seeded: EditorCarouselCard[] = Array.from(
        {
          length: Math.min(
            Math.max(limits.carousel_min_cards, attached.length),
            limits.carousel_max_cards
          ),
        },
        (_, i) => ({
          title: creative.title || '',
          body: null,
          link: creative.link || '',
          media_id: attached[i]?.media_id ?? null,
          media_url: attached[i]?.media_url ?? null,
          media_kind: attached[i]?.media_kind ?? 'image',
          image_hash: attached[i]?.image_hash ?? null,
          video_id: attached[i]?.video_id ?? null,
        })
      );
      patchCreative(aIdx, dIdx, {
        format: 'CAROUSEL',
        cards: seeded,
        media_id: null,
        image_hash: null,
        video_id: null,
        media_url: null,
        title_variants: null,
        body_variants: null,
        extra_media: null,
      });
      setActiveCardIndex(0);
      setCarouselTab('card');
    } else {
      const firstCard = cards[0];
      const remainingCards = cards
        .slice(1)
        .filter(
          (c) => c.media_id || c.media_url || c.image_hash || c.video_id
        );
      const extraMediaItems: EditorMediaRef[] = remainingCards.map((c) => ({
        media_id: c.media_id ?? null,
        media_url: c.media_url ?? null,
        media_kind: c.media_kind ?? 'image',
        image_hash: c.image_hash ?? null,
        video_id: c.video_id ?? null,
      }));
      patchCreative(aIdx, dIdx, {
        format: 'SINGLE',
        cards: null,
        media_id: firstCard?.media_id ?? null,
        media_url: firstCard?.media_url ?? null,
        media_kind: firstCard?.media_kind ?? 'image',
        extra_media: extraMediaItems.length ? extraMediaItems : null,
      });
    }
  };

  // Upload single / multi media files
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (!files.length || !creative) return;
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

      if (!picked.length) return;

      if (isCarousel) {
        const updatedCards = [...cards];
        let targetIndex = safeActiveCardIndex;
        let lastTargetIndex = targetIndex;

        picked.forEach((p) => {
          if (
            updatedCards[targetIndex] &&
            !updatedCards[targetIndex].media_id &&
            !updatedCards[targetIndex].media_url &&
            !updatedCards[targetIndex].image_hash
          ) {
            updatedCards[targetIndex] = {
              ...updatedCards[targetIndex],
              media_id: p.media_id,
              media_url: p.media_url,
              media_kind: p.media_kind,
              image_hash: null,
              video_id: null,
            };
            lastTargetIndex = targetIndex;
            targetIndex++;
          } else if (updatedCards.length < limits.carousel_max_cards) {
            const lastCard = updatedCards[updatedCards.length - 1];
            const newIndex = updatedCards.length;
            updatedCards.push({
              title: lastCard?.title ?? creative.title ?? '',
              body: lastCard?.body ?? null,
              link: lastCard?.link ?? creative.link ?? '',
              media_id: p.media_id,
              media_url: p.media_url,
              media_kind: p.media_kind,
              image_hash: null,
              video_id: null,
            });
            lastTargetIndex = newIndex;
            targetIndex = newIndex + 1;
          } else if (updatedCards[targetIndex]) {
            updatedCards[targetIndex] = {
              ...updatedCards[targetIndex],
              media_id: p.media_id,
              media_url: p.media_url,
              media_kind: p.media_kind,
              image_hash: null,
              video_id: null,
            };
            lastTargetIndex = targetIndex;
            targetIndex = Math.min(
              targetIndex + 1,
              limits.carousel_max_cards - 1
            );
          }
        });

        patchCreative(aIdx, dIdx, { cards: updatedCards });
        setActiveCardIndex(lastTargetIndex);
        setCarouselTab('card');
      } else {
        patchCreative(
          aIdx,
          dIdx,
          attachMedia(creative, picked, limits.max_media_per_ad)
        );
      }
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
      if (multiFileInputRef.current) multiFileInputRef.current.value = '';
    }
  };

  // Dedicated handler for Replacing creative media
  const handleReplaceMedia = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !creative) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await uploadMediaAction(fd);
      if (res.success && res.data) {
        const picked: EditorMediaRef = {
          media_id: res.data.id,
          media_url: res.data.file_path,
          media_kind: (res.data.media_type === 'video' ? 'video' : 'image') as
            | 'video'
            | 'image',
          image_hash: null,
          video_id: null,
        };

        if (isCarousel) {
          const updatedCards = [...cards];
          if (updatedCards[safeActiveCardIndex]) {
            updatedCards[safeActiveCardIndex] = {
              ...updatedCards[safeActiveCardIndex],
              media_id: picked.media_id,
              media_url: picked.media_url,
              media_kind: picked.media_kind,
              image_hash: null,
              video_id: null,
            };
            patchCreative(aIdx, dIdx, { cards: updatedCards });
          }
        } else {
          patchCreative(aIdx, dIdx, {
            media_id: picked.media_id,
            media_url: picked.media_url,
            media_kind: picked.media_kind,
            image_hash: null,
            video_id: null,
          });
        }
      }
    } finally {
      setUploading(false);
      if (replaceFileInputRef.current) replaceFileInputRef.current.value = '';
    }
  };

  // Sparkle fill: cycles or fills from AI suggestions
  const handleSparkleHeadline = () => {
    if (!creative) return;
    const suggestions = creative.title_suggestions ?? [];
    if (!suggestions.length) return;
    const curIdx = suggestions.indexOf(creative.title);
    const nextVal = suggestions[(curIdx + 1) % suggestions.length];
    patchCreative(aIdx, dIdx, { title: nextVal });
  };

  const handleSparkleBody = () => {
    if (!creative) return;
    const suggestions = creative.body_suggestions ?? [];
    if (!suggestions.length) return;
    const curIdx = suggestions.indexOf(creative.body);
    const nextVal = suggestions[(curIdx + 1) % suggestions.length];
    patchCreative(aIdx, dIdx, { body: nextVal });
  };

  const handleSparkleDescription = () => {
    if (!creative) return;
    const directSuggestions = creative.description_suggestions ?? [];
    const campaignDescriptions: string[] = [];
    spec.adsets.forEach((as) => {
      as.ads.forEach((ad) => {
        const desc = ad.creative?.description?.trim();
        if (desc && desc.length <= limits.description_max) {
          campaignDescriptions.push(desc);
        }
        ad.creative?.description_suggestions?.forEach((s) => {
          if (s?.trim()) campaignDescriptions.push(s.trim());
        });
      });
    });
    const headlineCandidates = (creative.title_suggestions ?? [])
      .map((t) => t.trim())
      .filter((t) => t.length > 0 && t.length <= limits.description_recommended);

    const pool = Array.from(
      new Set([
        ...directSuggestions,
        ...campaignDescriptions,
        ...headlineCandidates,
      ])
    ).filter(Boolean);
    if (!pool.length) return;
    const curIdx = pool.indexOf(creative.description || '');
    const nextVal = pool[(curIdx + 1) % pool.length];
    patchCreative(aIdx, dIdx, { description: nextVal });
  };

  const handleSparkleCardHeadline = (cardIdx: number) => {
    if (!creative) return;
    const suggestions = creative.title_suggestions ?? [];
    if (!suggestions.length) return;
    const currentTitle = cards[cardIdx]?.title || '';
    const curIdx = suggestions.indexOf(currentTitle);
    const nextVal = suggestions[(curIdx + 1) % suggestions.length];
    patchCard(cardIdx, { title: nextVal });
  };

  const handleSparkleCardDescription = (cardIdx: number) => {
    if (!creative) return;
    const directSuggestions = creative.description_suggestions ?? [];
    const pool = Array.from(
      new Set([
        ...directSuggestions,
        ...(creative.title_suggestions ?? []).filter(
          (t) => t.length <= limits.description_recommended
        ),
      ])
    ).filter(Boolean);
    if (!pool.length) return;
    const currentBody = cards[cardIdx]?.body || '';
    const curIdx = pool.indexOf(currentBody);
    const nextVal = pool[(curIdx + 1) % pool.length];
    patchCard(cardIdx, { body: nextVal });
  };

  const handleSparkleCardLink = (cardIdx: number) => {
    if (!creative) return;
    const link = creative.link?.trim();
    if (!link) return;
    patchCard(cardIdx, { link });
  };

  // "Punk this ad" action: rewrites or applies suggestions to all fields
  const handlePunkThisAd = () => {
    if (!creative) return;
    const titles = Array.from(
      new Set([
        ...(creative.title_suggestions ?? []),
        ...spec.adsets.flatMap((as) => as.ads.map((ad) => ad.creative?.title)),
      ])
    ).filter(Boolean) as string[];

    const bodies = Array.from(
      new Set([
        ...(creative.body_suggestions ?? []),
        ...spec.adsets.flatMap((as) => as.ads.map((ad) => ad.creative?.body)),
      ])
    ).filter(Boolean) as string[];

    const descriptions = Array.from(
      new Set([
        ...(creative.description_suggestions ?? []),
        ...spec.adsets.flatMap((as) =>
          as.ads.map((ad) => ad.creative?.description)
        ),
      ])
    ).filter(Boolean) as string[];

    const patch: Partial<EditorAd['creative']> = {};
    if (titles.length) {
      const curIdx = titles.indexOf(creative.title);
      patch.title = titles[(curIdx + 1) % titles.length];
    }
    if (bodies.length) {
      const curIdx = bodies.indexOf(creative.body);
      patch.body = bodies[(curIdx + 1) % bodies.length];
    }
    if (descriptions.length) {
      const curIdx = descriptions.indexOf(creative.description || '');
      patch.description = descriptions[(curIdx + 1) % descriptions.length];
    }
    if (Object.keys(patch).length) {
      patchCreative(aIdx, dIdx, patch);
    }
  };

  // Add headline variant
  const handleAddHeadlineVariant = () => {
    if (!creative) return;
    const variants = creative.title_variants ?? [];
    if (variants.length < limits.max_text_variants) {
      patchCreative(aIdx, dIdx, { title_variants: [...variants, ''] });
    }
  };

  // Add body variant
  const handleAddBodyVariant = () => {
    if (!creative) return;
    const variants = creative.body_variants ?? [];
    if (variants.length < limits.max_text_variants) {
      patchCreative(aIdx, dIdx, { body_variants: [...variants, ''] });
    }
  };

  const handleDeleteSingleMedia = () => {
    patchCreative(aIdx, dIdx, {
      media_id: null,
      media_url: null,
      image_hash: null,
      video_id: null,
    });
  };

  return {
    activeFlatAdIndex,
    setActiveFlatAdIndex,
    carouselTab,
    setCarouselTab,
    activeCardIndex,
    setActiveCardIndex,
    safeActiveCardIndex,
    uploading,
    fileInputRef,
    multiFileInputRef,
    replaceFileInputRef,
    flattenedAds,
    currentFlatItem,
    aIdx,
    dIdx,
    currentAdSet,
    currentAd,
    creative,
    limits,
    ctas,
    format,
    isCarousel,
    cards,
    currentCard,
    primaryMediaUrl,
    hasMediaAttached,
    patchCurrentCreative,
    patchCard,
    handleAddCard,
    handleRemoveCard,
    getMediaFileName,
    handleFormatChange,
    handleFileUpload,
    handleReplaceMedia,
    handleSparkleHeadline,
    handleSparkleBody,
    handleSparkleDescription,
    handleSparkleCardHeadline,
    handleSparkleCardDescription,
    handleSparkleCardLink,
    handlePunkThisAd,
    handleAddHeadlineVariant,
    handleAddBodyVariant,
    handleDeleteSingleMedia,
  };
}
