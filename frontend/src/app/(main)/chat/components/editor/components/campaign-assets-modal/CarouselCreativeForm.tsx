import React from 'react';
import {
  Box,
  Button,
  SegmentedControl,
  Select,
  Text,
  TextInput,
  Textarea,
} from '@mantine/core';
import { Sparkles } from 'lucide-react';
import { toSelectData } from '../editorUtils';
import { SoftCounter } from '../CopyField';
import type { CarouselCreativeFormProps } from './types';

export default function CarouselCreativeForm({
  creative,
  limits,
  ctas,
  cards,
  safeActiveCardIndex,
  currentCard,
  carouselTab,
  onTabChange,
  onPatchCard,
  onPatchCreative,
  onSparkleBody,
  onSparkleCardHeadline,
  onSparkleCardDescription,
  onPunkThisAd,
}: CarouselCreativeFormProps) {
  return (
    <>
      {/* "✦ Punk this ad" Button */}
      <Box className="flex! flex-col!">
        <Button
          type="button"
          onClick={onPunkThisAd}
          className="group! border-primary-text/13! bg-primary-text/7! text-primary-text/85! hover:bg-primary-text/4! flex! w-full! items-center! justify-center! gap-2! rounded-[36px]! border! px-3! py-2! text-xs! font-bold! transition-all!"
          style={{
            boxShadow:
              '0px 1.5px 0px 0px #FFFFFF2E inset, 0px 4px 12px 0px #00000033',
          }}
        >
          <Sparkles
            size={14}
            className="text-primary-text pr-0.5 transition-transform group-hover:rotate-12"
          />
          <Text fw={700} fz={12}>
            Punk this ad
          </Text>
        </Button>
        <Text
          fz={13}
          className="text-primary-text/30! mt-1.5! text-center! sm:text-left!"
        >
          Rewrites the full copy Or fill one field with its own ✦.
        </Text>
      </Box>

      {/* Carousel Sub-toggle: [ Shared ] [ Card X of Y ] */}
      <SegmentedControl
        value={carouselTab}
        onChange={(val) => onTabChange(val as 'shared' | 'card')}
        data={[
          { label: 'Shared', value: 'shared' },
          {
            label: `Card ${safeActiveCardIndex + 1} of ${cards.length}`,
            value: 'card',
          },
        ]}
        radius={30}
        fullWidth
        classNames={{
          root: 'bg-primary-bg/4! border border-white/8! p-0.5! mt-1!',
          indicator:
            'bg-primary-bg-2! shadow-[0px_1px_0px_0px_#FFFFFF2E_inset]!',
          label:
            'text-xs! font-medium! text-primary-text/40! data-[active]:text-primary-text! py-1.5!',
        }}
      />

      {/* Card Tab Form */}
      {carouselTab === 'card' && currentCard ? (
        <>
          {/* Card headline */}
          <Box className="flex! flex-col!">
            <Box className="mb-1.75! flex! items-center! justify-between!">
              <Text fw={700} fz={12} className="text-primary-text/80!">
                Card headline
              </Text>
              <SoftCounter
                len={(currentCard.title || '').length}
                max={limits.title_max}
              />
            </Box>
            <TextInput
              value={currentCard.title || ''}
              onChange={(e) =>
                onPatchCard(safeActiveCardIndex, {
                  title: e.currentTarget.value,
                })
              }
              placeholder="e.g. Get Glowing Skin, Naturally"
              maxLength={limits.title_max}
              classNames={{
                input:
                  'bg-primary-text/4! border-primary-text/9! shadow-[0px_1px_0px_0px_#FFFFFF0D_inset]! text-primary-text! rounded-[49px]! text-xs! h-10! px-3.5! pb-0.5!',
              }}
              rightSection={
                <button
                  type="button"
                  onClick={() => onSparkleCardHeadline?.(safeActiveCardIndex)}
                  title="Fill with AI idea"
                  className="bg-primary-text/8! border-primary-text/14! text-primary-text/80! hover:bg-primary-text/10! hover:text-primary-text! flex h-5.5! w-5.5! cursor-pointer! items-center justify-center! rounded-full! border! transition-colors!"
                >
                  <Sparkles size={12} />
                </button>
              }
            />
          </Box>

          {/* Card description */}
          <Box className="flex! flex-col!">
            <Box className="mb-1.75! flex! items-center! justify-between!">
              <Text fw={700} fz={12} className="text-primary-text/80!">
                Card description
              </Text>
              <SoftCounter
                len={(currentCard.body || '').length}
                max={limits.body_max}
              />
            </Box>
            <TextInput
              value={currentCard.body || ''}
              onChange={(e) =>
                onPatchCard(safeActiveCardIndex, {
                  body: e.currentTarget.value || null,
                })
              }
              placeholder="e.g. Cruelty-Free & Vegan"
              maxLength={limits.body_max}
              classNames={{
                input:
                  'bg-primary-text/4! border-primary-text/9! shadow-[0px_1px_0px_0px_#FFFFFF0D_inset]! text-primary-text! rounded-[49px]! text-xs! h-10! px-3.5! pb-0.5!',
              }}
              rightSection={
                <button
                  type="button"
                  onClick={() => onSparkleCardDescription?.(safeActiveCardIndex)}
                  title="Fill with AI idea"
                  className="bg-primary-text/8! border-primary-text/14! text-primary-text/80! hover:bg-primary-text/10! hover:text-primary-text! flex h-5.5! w-5.5! cursor-pointer! items-center justify-center! rounded-full! border! transition-colors!"
                >
                  <Sparkles size={12} />
                </button>
              }
            />
          </Box>

          {/* Card link */}
          <Box className="flex! flex-col!">
            <Text fw={700} fz={12} className="text-primary-text/80! mb-1.75!">
              Card link
            </Text>
            <TextInput
              value={currentCard.link || ''}
              onChange={(e) =>
                onPatchCard(safeActiveCardIndex, {
                  link: e.currentTarget.value,
                })
              }
              placeholder="Using shared link"
              classNames={{
                input:
                  'bg-primary-text/4! border-primary-text/9! shadow-[0px_1px_0px_0px_#FFFFFF0D_inset]! text-primary-text! rounded-[49px]! text-xs! h-10! px-3.5! pb-0.75!',
              }}
            />
          </Box>
        </>
      ) : (
        /* Shared Tab Form */
        <>
          {/* Primary text (Shared) */}
          <Box className="flex! flex-col!">
            <Box className="mb-1.75! flex! items-center! justify-between!">
              <Text fw={700} fz={12} className="text-primary-text/80!">
                Primary text
              </Text>
              <SoftCounter
                len={(creative.body || '').length}
                max={limits.body_max}
              />
            </Box>
            <div className="relative">
              <Textarea
                value={creative.body || ''}
                onChange={(e) =>
                  onPatchCreative({
                    body: e.currentTarget.value,
                  })
                }
                placeholder="e.g. Sensitive skin? Harsh chemicals can make it worse..."
                maxLength={limits.body_max}
                autosize
                minRows={3}
                classNames={{
                  input:
                    'bg-primary-text/4! border-primary-text/9! shadow-[0px_1px_0px_0px_#FFFFFF0D_inset]! text-primary-text! rounded-2xl! text-xs! px-2.5! py-2! pr-9!',
                  section: 'items-start! pt-2.5! pr-2.5!',
                }}
                rightSection={
                  <button
                    type="button"
                    onClick={onSparkleBody}
                    className="bg-primary-text/8! border-primary-text/14! text-primary-text/80! hover:bg-primary-text/10! hover:text-primary-text! flex h-5.5! w-5.5! cursor-pointer! items-center justify-center! rounded-full! border! transition-colors!"
                  >
                    <Sparkles size={12} />
                  </button>
                }
              />
            </div>
          </Box>

          {/* Call to action (Shared) */}
          <Box className="flex! flex-col!">
            <Text fw={700} fz={12} className="text-primary-text/80! mb-1.75!">
              Call to action
            </Text>
            <Select
              data={toSelectData(ctas)}
              value={creative.call_to_action}
              onChange={(v) => v && onPatchCreative({ call_to_action: v })}
              maxDropdownHeight={180}
              comboboxProps={{
                withinPortal: true,
                zIndex: 1000000,
                position: 'top-start',
                offset: 6,
                middlewares: { flip: true, shift: true },
              }}
              styles={{
                dropdown: {
                  maxHeight: '180px',
                  overflow: 'hidden',
                  backdropFilter: 'blur(15px)',
                  WebkitBackdropFilter: 'blur(15px)',
                  scrollbarWidth: 'none',
                  msOverflowStyle: 'none',
                },
                options: {
                  maxHeight: '168px',
                  overflowY: 'auto',
                  scrollbarWidth: 'none',
                  msOverflowStyle: 'none',
                },
              }}
              classNames={{
                input:
                  'bg-primary-text/4! border-primary-text/9! shadow-[0px_1px_0px_0px_#FFFFFF0D_inset]! text-primary-text! rounded-[49px]! text-xs! h-10! px-3.5! pb-0.75!',
                dropdown:
                  'bg-primary-bg/40! light:backdrop-blur-[7.7px] border-primary-text/20 backdrop-blur-[15px] rounded-xl! shadow-xl! p-1.5! overflow-hidden! custom-scrollbar',
                options: 'max-h-[168px]! overflow-y-auto! custom-scrollbar',
                option:
                  'text-xs! rounded-lg! text-secondary-text! hover:text-primary-text! hover:bg-white/5! dark:hover:bg-white/5! light:hover:bg-black/5! data-[selected]:bg-white/10! data-[selected]:text-primary-text! transition-colors!',
              }}
            />
          </Box>

          {/* Link (Shared) */}
          <Box className="flex! flex-col!">
            <Text fw={700} fz={12} className="text-primary-text/80! mb-1.75!">
              Link
            </Text>
            <TextInput
              value={creative.link || ''}
              onChange={(e) =>
                onPatchCreative({
                  link: e.currentTarget.value,
                })
              }
              placeholder="https://facebook.com/1803996873218871"
              classNames={{
                input:
                  'bg-primary-text/4! border-primary-text/9! shadow-[0px_1px_0px_0px_#FFFFFF0D_inset]! text-primary-text! rounded-[49px]! text-xs! h-10! px-3.5! pb-0.75!',
              }}
            />
            <Text fz={11} className="text-primary-text/30! mt-1 px-1">
              Each card can override this.
            </Text>
          </Box>

          {/* URL parameters (Shared) */}
          <Box className="flex! flex-col!">
            <Text fw={700} fz={12} className="text-primary-text/80! mb-1.75!">
              URL parameters
            </Text>
            <TextInput
              value={creative.url_tags || ''}
              onChange={(e) =>
                onPatchCreative({
                  url_tags: e.currentTarget.value || null,
                })
              }
              placeholder="utm_source=facebook&utm_medium=pa..."
              classNames={{
                input:
                  'bg-primary-text/4! border-primary-text/9! shadow-[0px_1px_0px_0px_#FFFFFF0D_inset]! text-primary-text! rounded-[49px]! text-xs! h-10! px-3.5! pb-0.75!',
              }}
            />
          </Box>
        </>
      )}
    </>
  );
}
