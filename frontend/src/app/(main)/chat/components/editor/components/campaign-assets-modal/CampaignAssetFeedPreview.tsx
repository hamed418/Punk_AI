import { Box, Button, Loader, Text } from '@mantine/core';
import { Image as ImageIcon, Info, Plus, Trash2, Upload } from 'lucide-react';
import { mediaKindOf } from '../editorUtils';
import type { CampaignAssetFeedPreviewProps } from './types';

export default function CampaignAssetFeedPreview({
  creative,
  pageName,
  isCarousel,
  cards,
  safeActiveCardIndex,
  limits,
  primaryMediaUrl,
  hasMediaAttached,
  uploading,
  fileInputRef,
  multiFileInputRef,
  replaceFileInputRef,
  onFileUpload,
  onReplaceMedia,
  onSelectCard,
  onAddCard,
  onRemoveCard,
  onDeleteSingleMedia,
  getMediaFileName,
}: CampaignAssetFeedPreviewProps) {
  return (
    <Box className="border-primary-bg/50! order-1! ml-0.75! flex! w-full! shrink-0! flex-col! gap-3! border-b! p-3.5! sm:ml-px! sm:p-4! xl:order-2! xl:-ml-1.25! xl:w-96.75! xl:shrink-0! xl:border-b-0!">
      {/* Facebook Feed Card Preview */}
      <Box className="border-primary-text/8! bg-primary-text/3! flex! flex-col! gap-3! rounded-2xl! border! px-2.5! pt-2.5! pb-1.75!">
        {/* Page header */}
        <Box className="flex! items-center! gap-1.75!">
          <Box className="border-primary-text/10! bg-primary-text/8! text-primary-text! flex! h-8! w-8! items-center! justify-center! overflow-hidden! rounded-full! border! text-xs! font-semibold!">
            {pageName.charAt(0).toUpperCase()}
          </Box>
          <Box className="flex! flex-col!">
            <Text
              fz={11}
              fw={700}
              className="text-primary-text! leading-tight!"
            >
              {pageName}
            </Text>
            <Text fz={9} className="text-primary-text/35! mt-1! leading-tight!">
              Sponsored · ⊙
            </Text>
          </Box>
        </Box>

        {/* Body text in preview */}
        <Text
          fz={11}
          className="text-primary-text/65! mb-2! leading-relaxed! whitespace-pre-wrap!"
        >
          {creative?.body ||
            'Sensitive skin? Harsh chemicals can make it worse. Our plant-based formulas soothe and nourish from day one.'}
        </Text>

        {/* ── Media Display Area (Single Mode) ── */}
        {!isCarousel && (
          <>
            {!hasMediaAttached ? (
              /* Case A: Drop files / browse dropzone */
              <Box
                onClick={() => fileInputRef.current?.click()}
                className="group! border-primary-text/8! bg-primary-text/4! hover:border-primary-text/9! hover:bg-primary-text/2! relative mb-1.75! flex aspect-4/3! cursor-pointer! flex-col! items-center! justify-center! overflow-hidden! rounded-xl! border! text-center! transition-colors!"
              >
                <Box className="border-primary-text/10! bg-primary-text/6! text-primary-text! mb-3! flex h-9! w-9! items-center! justify-center! rounded-[14px]! border! shadow-[0px_1px_0px_0px_#FFFFFF1A_inset]! transition-transform! group-hover:scale-105!">
                  {uploading ? (
                    <Loader size={18} color="white" />
                  ) : (
                    <Upload size={18} />
                  )}
                </Box>
                <Text
                  fz={13}
                  fw={600}
                  className="text-primary-text/65! flex! items-center! gap-1!"
                >
                  Drop files or{' '}
                  <span className="text-primary-text/90! underline!">
                    browse
                  </span>
                </Text>
              </Box>
            ) : (
              /* Case B: Uploaded Image / Video Preview */
              <Box className="group border-primary-text/8! bg-primary-text/4! relative! flex! aspect-4/3! flex-col! overflow-hidden! rounded-md! border!">
                {/* File top header bar */}
                <Box className="border-primary-text/8! flex! shrink-0! items-center! gap-1.5! border-b! px-3! py-2!">
                  <ImageIcon className="text-primary-text/40!" size={13} />
                  <Text
                    fz={10}
                    className="text-primary-text/40! truncate! leading-none!"
                  >
                    {getMediaFileName(primaryMediaUrl)}
                  </Text>
                </Box>

                {/* Media display area */}
                <Box className="relative! flex! min-h-0! flex-1! items-center! justify-center! overflow-hidden!">
                  {primaryMediaUrl ? (
                    mediaKindOf(creative!) === 'video' ? (
                      <video
                        src={primaryMediaUrl}
                        className="h-full w-full object-cover"
                        autoPlay
                        loop
                        muted
                        playsInline
                      />
                    ) : (
                      <img
                        src={primaryMediaUrl}
                        alt="Ad creative preview"
                        className="h-full w-full object-cover"
                      />
                    )
                  ) : (
                    <Box className="text-primary-text/25! flex! flex-col! items-center! justify-center!">
                      <ImageIcon size={38} />
                    </Box>
                  )}

                  {/* Hover action overlay */}
                  <Box className="absolute! inset-0 flex items-center! justify-center! gap-2! bg-black/60! opacity-0! transition-opacity! group-hover:opacity-100!">
                    <button
                      type="button"
                      onClick={() => replaceFileInputRef.current?.click()}
                      className="bg-primary-text/4! text-primary-text! hover:bg-primary-text/1! border-primary-text/8! cursor-pointer! rounded-2xl! border! px-3! py-1.5! text-xs! font-medium! backdrop-blur-[75px]!"
                    >
                      Replace
                    </button>
                    <button
                      type="button"
                      onClick={onDeleteSingleMedia}
                      className="cursor-pointer rounded-full bg-red-500/20 p-1.5 text-xs text-red-400 backdrop-blur-sm hover:bg-red-500/30"
                    >
                      <Trash2 size={14} />
                    </button>
                  </Box>
                </Box>
              </Box>
            )}

            {/* Bottom bar of ad preview */}
            <Box className="flex! items-center! justify-between! gap-3!">
              <Box className="flex! min-w-0! flex-1! flex-col!">
                <Text fz={11} fw={700} className="text-primary-text! truncate!">
                  {creative?.title || 'Get Glowing Skin, Naturally'}
                </Text>
                <Text fz={9} className="text-primary-text/35! truncate!">
                  {creative?.description || 'Cruelty-Free & Vegan Formulas'}
                </Text>
              </Box>
              <Button
                type="button"
                className="border-primary-text/12! bg-primary-text/8! text-primary-text! hover:bg-primary-text/5! shrink-0! rounded-[6px]! border! px-2.5! text-[10px]! font-bold! shadow-[0px_1px_0px_0px_#FFFFFF1F_inset]!"
              >
                {creative?.call_to_action?.replace(/_/g, ' ') || 'Learn More'}
              </Button>
            </Box>
          </>
        )}

        {/* ── Media Display Area (Carousel Mode) ── */}
        {isCarousel && (
          <>
            {/* Horizontal preview cards */}
            <Box className="flex! scrollbar-thin! gap-2.5! overflow-x-auto! pb-2!">
              {cards.map((card, cIdx) => (
                <Box
                  key={cIdx}
                  onClick={() => onSelectCard(cIdx)}
                  className={`group/card flex h-61.25! w-48 shrink-0 cursor-pointer flex-col overflow-hidden rounded-md border transition-all ${
                    cIdx === safeActiveCardIndex
                      ? 'border-primary-text/40! bg-primary-text/4! shadow-[0px_0px_0px_2px_#FFFFFF14]!'
                      : 'border-primary-text/0! bg-primary-text/4! hover:border-primary-text/15!'
                  }`}
                >
                  {/* Card Media Preview */}
                  <Box className="relative! flex! min-h-0! flex-1! items-center! justify-center! overflow-hidden! bg-transparent!">
                    <Text className="text-primary-text! absolute! top-1! left-1! z-10! flex! h-3.5! w-3.5! items-center! justify-center! rounded-[3px]! bg-[#00000099]! text-[10px]! font-bold!">
                      {cIdx + 1}
                    </Text>
                    {card.media_url ? (
                      <img
                        src={card.media_url}
                        alt=""
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <Box className="text-primary-text/25 flex items-center justify-center">
                        <ImageIcon size={24} />
                      </Box>
                    )}

                    {/* Hover overlay on card */}
                    <Box className="absolute! inset-0 flex items-center! justify-center! gap-1.5! bg-black/60! opacity-0! transition-opacity! group-hover/card:opacity-100!">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectCard(cIdx);
                          replaceFileInputRef.current?.click();
                        }}
                        className="bg-primary-text/10! text-primary-text! hover:bg-primary-text/20! border-primary-text/15! cursor-pointer! rounded-xl! border! px-2! py-1! text-[10px]! font-medium! backdrop-blur-[75px]!"
                      >
                        {card.media_url ? 'Replace' : 'Upload'}
                      </button>
                      {cards.length > limits.carousel_min_cards && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onRemoveCard(cIdx);
                          }}
                          className="cursor-pointer rounded-full bg-red-500/20 p-1 text-red-400 backdrop-blur-sm hover:bg-red-500/30"
                          title="Delete this card"
                        >
                          <Trash2 size={12} />
                        </button>
                      )}
                    </Box>
                  </Box>

                  {/* Card Text & CTA */}
                  <Box className="border-primary-text/6 flex shrink-0 flex-col gap-0.5 border-t px-1.5 py-1.25!">
                    <Text
                      fz={9}
                      fw={700}
                      className="text-primary-text! truncate!"
                    >
                      {card.title ||
                        creative?.title ||
                        'Get Glowing Skin, Naturally'}
                    </Text>
                    <Text fz={8} className="text-primary-text/40! truncate!">
                      {card.body || creative?.body || 'Cruelty-Free & Vegan'}
                    </Text>
                  </Box>
                </Box>
              ))}
            </Box>

            {/* Bottom bar of carousel preview */}
            <Box className="border-primary-text/15! flex! items-center! justify-between! border-t! pt-2! text-[11px]!">
              <Text fz={9} className="text-primary-text/30!">
                swipe · {cards.length} cards
              </Text>
              <Button
                type="button"
                className="border-primary-text/12! bg-primary-text/8! text-primary-text! hover:bg-primary-text/5! shrink-0! rounded-[6px]! border! px-2.5! py-1! text-[10px]! font-bold! shadow-[0px_1px_0px_0px_#FFFFFF1F_inset]!"
              >
                {creative?.call_to_action?.replace(/_/g, ' ') || 'Learn More'}
              </Button>
            </Box>
          </>
        )}
      </Box>

      {/* ── Carousel Cards Grid Selector ── */}
      {isCarousel && (
        <Box className="border-primary-text/6! mt-1 flex flex-col gap-3 border-t pt-2">
          <Box className="flex items-center justify-between text-xs">
            <Text fz={11} fw={700} className="text-primary-text/55!">
              Cards {cards.length}/{limits.carousel_max_cards}
            </Text>
            <button
              type="button"
              onClick={() => multiFileInputRef.current?.click()}
              className="text-primary-text/55 hover:text-primary-text/90 cursor-pointer text-[11px] font-bold"
            >
              Upload images
            </button>
          </Box>

          <Box className="flex flex-wrap items-center gap-1.25!">
            {cards.map((card, cIdx) => (
              <button
                key={cIdx}
                type="button"
                onClick={() => onSelectCard(cIdx)}
                className={`relative flex h-20 w-20 shrink-0 cursor-pointer items-center justify-center overflow-hidden rounded-[7px] transition-all ${
                  cIdx === safeActiveCardIndex
                    ? 'border-primary-text/40 bg-primary-text/4 hover:bg-primary-text/7 border shadow-[0px_0px_0px_2px_#FFFFFF12]!'
                    : 'border-primary-text/9 bg-primary-text/4 hover:bg-primary-text/7 border'
                }`}
              >
                <Text className="text-primary-text! absolute! top-1! left-1! z-10! flex! h-3.5! w-3.5! items-center! justify-center! rounded-[3px]! bg-[#00000099]! text-[10px]! font-bold!">
                  {cIdx + 1}
                </Text>
                {card.media_url ? (
                  <img
                    src={card.media_url}
                    alt=""
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <ImageIcon size={20} className="text-primary-text/25" />
                )}
              </button>
            ))}
            {cards.length < limits.carousel_max_cards && (
              <button
                type="button"
                onClick={onAddCard}
                className="border-primary-text/14 hover:bg-primary-text/2! text-primary-text/60 hover:text-primary-text flex h-20 w-20 shrink-0 cursor-pointer items-center justify-center rounded-[7px] border border-dashed bg-transparent transition-colors"
              >
                <Plus size={18} />
              </button>
            )}
          </Box>
        </Box>
      )}

      {/* ── Supported Formats Under Preview ── */}
      <Box className="flex flex-col gap-1 rounded-xl border border-[#FFFFFF14] px-3 py-2.5">
        <Box className="flex items-start gap-2">
          <Info size={14} className="shrink-0 text-[#FAF9F5A6]" />
          <Box className="flex flex-col">
            <Text fz={10} fw={700} className="tracking-wider text-[#FAF9F5A6]">
              SUPPORTED FORMATS
            </Text>
            <Text fz={12} fw={500} className="text-primary-text leading-tight">
              Image: JPG JPEG PNG WEBP HEIC HEIF PSD TIFF BMP DIB JFIF · Video:
              MP4 MOV AVI WMV GIF 3GP MKV FLV MPEG MPG MTS
            </Text>
          </Box>
        </Box>
      </Box>

      {/* Hidden file inputs */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*,video/*"
        multiple={!isCarousel}
        onChange={onFileUpload}
        className="hidden"
      />
      <input
        ref={replaceFileInputRef}
        type="file"
        accept="image/*,video/*"
        onChange={onReplaceMedia}
        className="hidden"
      />
      <input
        ref={multiFileInputRef}
        type="file"
        accept="image/*"
        multiple
        onChange={onFileUpload}
        className="hidden"
      />
    </Box>
  );
}
