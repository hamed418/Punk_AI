'use client';

import React from 'react';
import { Box, Modal, ScrollArea, SegmentedControl } from '@mantine/core';
import GenerateAdOverlay from '../../creative/GenerateAdOverlay';
import LeadFormOverlay from '../LeadFormOverlay';
import { attachMedia } from './editorUtils';
import {
  type CampaignAssetsModalProps,
  useCampaignAssetsModalState,
  CampaignAssetsModalHeader,
  SingleAdCreativeForm,
  CarouselCreativeForm,
  CampaignAssetFeedPreview,
  CampaignAssetsModalFooter,
} from './campaign-assets-modal';

export default function CampaignAssetsModal({
  opened,
  onClose,
  spec,
  catalog,
  adsOnly,
  currentPage,
  pageId,
  destinations,
  update,
  patchCreative,
  onGenerate,
  threadId,
  generating,
  setGenerating,
  buildingForm,
  setBuildingForm,
  setNewForms,
  onSubmit,
  errorBanner,
  complianceBanner,
  title,
  subtitle,
}: CampaignAssetsModalProps) {
  const {
    activeFlatAdIndex,
    setActiveFlatAdIndex,
    carouselTab,
    setCarouselTab,
    setActiveCardIndex,
    safeActiveCardIndex,
    uploading,
    fileInputRef,
    multiFileInputRef,
    replaceFileInputRef,
    flattenedAds,
    aIdx,
    dIdx,
    currentAdSet,
    currentAd,
    creative,
    limits,
    ctas,
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
  } = useCampaignAssetsModalState({
    spec,
    catalog,
    adsOnly,
    destinations,
    patchCreative,
  });

  const pageName = currentPage?.name || spec.name || 'Autopaws';

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      centered
      size="min(850px, calc(100vw - 16px))"
      radius="24px"
      padding={0}
      withCloseButton={false}
      zIndex={100000}
      overlayProps={{ backgroundOpacity: 0, blur: 5, color: 'transparent' }}
      classNames={{
        content:
          'bg-primary-text/1! overflow-hidden! rounded-[20px]! sm:rounded-[24px]!',
        body: 'p-0!',
      }}
      styles={{
        content: {
          maxWidth: '90vw',
          width: '90vw',
          margin: 'auto',
          boxShadow: `
            0px -1px 0px 0px #00000066 inset,
            0px 1px 0px 0px #FFFFFF1F inset,
            0px 8px 24px 0px #00000080
          `,
          backdropFilter: 'blur(75.9000015258789px)',
          WebkitBackdropFilter: 'blur(75.9000015258789px)',
        },
        inner: {
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '8px',
        },
      }}
    >
      <Box className="relative! flex! max-h-[90vh]! flex-col! overflow-hidden!">
        {/* Header & Ad Selection */}
        <CampaignAssetsModalHeader
          title={title}
          subtitle={subtitle}
          currentAd={currentAd}
          currentAdSet={currentAdSet}
          dIdx={dIdx}
          flattenedAdsCount={flattenedAds.length}
          activeFlatAdIndex={activeFlatAdIndex}
          onPrevAd={() => setActiveFlatAdIndex((prev) => Math.max(0, prev - 1))}
          onNextAd={() =>
            setActiveFlatAdIndex((prev) =>
              Math.min(flattenedAds.length - 1, prev + 1)
            )
          }
          onClose={onClose}
        />

        {/* Main Scrollable Body */}
        <ScrollArea.Autosize
          mah="calc(90vh - 155px)"
          type="hover"
          scrollbars="y"
          scrollbarSize={6}
          offsetScrollbars
          className="custom-textarea-scrollbar flex-1"
          styles={{
            scrollbar: {
              background: 'transparent',
            },
            thumb: {
              background:
                'color-mix(in srgb, var(--color-primary-text) 18%, transparent)',
              borderRadius: '999px',
            },
          }}
        >
          <Box className="flex! flex-col! xl:grid! xl:grid-cols-[457px_368px]! w-full! justify-center!">
            {/* Left Column: Form Inputs */}
            <Box className="border-primary-bg/50! order-2! ml-0.5! flex! w-full! shrink-0! flex-col! gap-3.5! p-3.5! sm:ml-1! sm:p-4! xl:order-1! xl:-ml-2.5! xl:w-115.75! xl:shrink-0! xl:border-r!">
              {/* Single / Carousel Format Switcher on top of Punk this ad button */}
              <SegmentedControl
                value={isCarousel ? 'CAROUSEL' : 'SINGLE'}
                onChange={(val) => handleFormatChange(val)}
                data={[
                  { label: 'Single', value: 'SINGLE' },
                  { label: 'Carousel', value: 'CAROUSEL' },
                ]}
                radius={30}
                fullWidth
                classNames={{
                  root: 'bg-primary-bg/4! border border-white/8! p-0.5!',
                  indicator:
                    'bg-primary-bg-2! shadow-[0px_1px_0px_0px_#FFFFFF2E_inset]!',
                  label:
                    'text-xs! font-medium! text-primary-text/40! data-[active]:text-primary-text! py-1.5!',
                }}
              />

              {errorBanner}
              {complianceBanner}

              {!isCarousel && creative && (
                <SingleAdCreativeForm
                  creative={creative}
                  limits={limits}
                  ctas={ctas}
                  onPatchCreative={patchCurrentCreative}
                  onPunkThisAd={handlePunkThisAd}
                  onSparkleHeadline={handleSparkleHeadline}
                  onSparkleBody={handleSparkleBody}
                  onSparkleDescription={handleSparkleDescription}
                  onAddHeadlineVariant={handleAddHeadlineVariant}
                  onAddBodyVariant={handleAddBodyVariant}
                />
              )}

              {isCarousel && creative && (
                <CarouselCreativeForm
                  creative={creative}
                  limits={limits}
                  ctas={ctas}
                  cards={cards}
                  safeActiveCardIndex={safeActiveCardIndex}
                  currentCard={currentCard}
                  carouselTab={carouselTab}
                  onTabChange={setCarouselTab}
                  onPatchCard={patchCard}
                  onPatchCreative={patchCurrentCreative}
                  onSparkleBody={handleSparkleBody}
                  onSparkleCardHeadline={handleSparkleCardHeadline}
                  onSparkleCardDescription={handleSparkleCardDescription}
                  onSparkleCardLink={handleSparkleCardLink}
                  onPunkThisAd={handlePunkThisAd}
                />
              )}
            </Box>

            {/* Right Column: Live Facebook Ad Preview & Media Controls */}
            <CampaignAssetFeedPreview
              creative={creative}
              pageName={pageName}
              isCarousel={isCarousel}
              cards={cards}
              safeActiveCardIndex={safeActiveCardIndex}
              limits={limits}
              primaryMediaUrl={primaryMediaUrl}
              hasMediaAttached={hasMediaAttached}
              uploading={uploading}
              fileInputRef={fileInputRef}
              multiFileInputRef={multiFileInputRef}
              replaceFileInputRef={replaceFileInputRef}
              onFileUpload={handleFileUpload}
              onReplaceMedia={handleReplaceMedia}
              onSelectCard={(cIdx) => {
                setActiveCardIndex(cIdx);
                setCarouselTab('card');
              }}
              onAddCard={handleAddCard}
              onRemoveCard={handleRemoveCard}
              onGenerate={() => onGenerate(aIdx, dIdx)}
              onDeleteSingleMedia={handleDeleteSingleMedia}
              getMediaFileName={getMediaFileName}
            />
          </Box>
        </ScrollArea.Autosize>

        {/* Modal Footer */}
        <CampaignAssetsModalFooter
          adsOnly={adsOnly}
          onClose={onClose}
          onSubmit={onSubmit}
        />

        {/* Overlays */}
        {generating && (
          <GenerateAdOverlay
            type="image"
            threadId={threadId}
            onClose={() => setGenerating(null)}
            onAdd={(generated) => {
              if (!generated.length) return;
              const asCreative = (a: (typeof generated)[number]) => ({
                media_id: a.id ?? null,
                media_url: a.url ?? null,
                media_kind: 'image' as const,
                image_hash: null,
                video_id: null,
              });
              update((d) => {
                const cr = d.adsets[generating.a].ads[generating.d].creative;
                if (cr.format === 'CAROUSEL') {
                  const currentCards = cr.cards ?? [];
                  const updatedCards = [...currentCards];
                  let targetIndex = safeActiveCardIndex;
                  let lastTargetIndex = targetIndex;

                  generated.forEach((gen) => {
                    const p = asCreative(gen);
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
                        title: lastCard?.title ?? cr.title ?? '',
                        body: lastCard?.body ?? null,
                        link: lastCard?.link ?? cr.link ?? '',
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
                  cr.cards = updatedCards;
                  setActiveCardIndex(lastTargetIndex);
                  setCarouselTab('card');
                } else {
                  Object.assign(
                    cr,
                    attachMedia(
                      cr,
                      generated.map(asCreative),
                      catalog.creative_limits.max_media_per_ad
                    )
                  );
                }
              });
              setGenerating(null);
            }}
          />
        )}

        {buildingForm !== null && spec.adsets[buildingForm] && (
          <LeadFormOverlay
            catalog={catalog}
            pageId={pageId}
            draft={spec.adsets[buildingForm].lead_form_draft}
            campaignName={spec.name}
            adHeadline={spec.adsets[buildingForm].ads[0]?.creative.title}
            onClose={() => setBuildingForm(null)}
            onSaveDraft={(draft) => {
              update((d) => {
                const as = d.adsets[buildingForm];
                as.lead_form_draft = draft;
                as.ads.forEach((ad) => (ad.creative.lead_gen_form_id = null));
              });
              setBuildingForm(null);
            }}
            onCreated={(form) => {
              setNewForms((prev) => [...prev, form]);
              update((d) => {
                const as = d.adsets[buildingForm];
                as.lead_form_draft = null;
                as.ads.forEach(
                  (ad) => (ad.creative.lead_gen_form_id = form.id)
                );
              });
              setBuildingForm(null);
            }}
          />
        )}
      </Box>
    </Modal>
  );
}
