import React from 'react';
import { Box, Button, Select, Text, TextInput, Textarea } from '@mantine/core';
import { Plus, Sparkles, Trash2 } from 'lucide-react';
import { toSelectData } from '../editorUtils';
import { SoftCounter } from '../CopyField';
import type { SingleAdCreativeFormProps } from './types';

export default function SingleAdCreativeForm({
  creative,
  limits,
  ctas,
  onPatchCreative,
  onPunkThisAd,
  onSparkleHeadline,
  onSparkleBody,
  onSparkleDescription,
  onAddHeadlineVariant,
  onAddBodyVariant,
}: SingleAdCreativeFormProps) {
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

      {/* Headline */}
      <Box className="flex! flex-col!">
        <Box className="mb-1.75! flex! items-center! justify-between!">
          <Text fw={700} fz={12} className="text-primary-text/80!">
            Headline
          </Text>
          <SoftCounter len={(creative.title || '').length} max={limits.title_max} />
        </Box>
        <TextInput
          value={creative.title || ''}
          onChange={(e) =>
            onPatchCreative({
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
              onClick={onSparkleHeadline}
              title="Fill with AI idea"
              className="bg-primary-text/8! border-primary-text/14! text-primary-text/80! hover:bg-primary-text/10! hover:text-primary-text! flex h-5.5! w-5.5! cursor-pointer! items-center justify-center! rounded-full! border! transition-colors!"
            >
              <Sparkles size={12} />
            </button>
          }
        />

        {/* Headline variants */}
        {(creative.title_variants ?? []).map((variant, vIdx) => (
          <Box key={vIdx} className="mt-2! flex! items-center! gap-2!">
            <TextInput
              value={variant}
              onChange={(e) => {
                const next = [...(creative.title_variants ?? [])];
                next[vIdx] = e.currentTarget.value;
                onPatchCreative({
                  title_variants: next,
                });
              }}
              placeholder={`Headline variant ${vIdx + 2}`}
              maxLength={limits.title_max}
              className="flex-1"
              classNames={{
                input:
                  'bg-primary-text/4! border-primary-text/9! shadow-[0px_1px_0px_0px_#FFFFFF0D_inset]! text-primary-text! rounded-2xl! text-xs! h-9! px-3.5! pb-0.5!',
              }}
            />
            <button
              type="button"
              onClick={() => {
                const next = (creative.title_variants ?? []).filter(
                  (_, j) => j !== vIdx
                );
                onPatchCreative({
                  title_variants: next.length ? next : null,
                });
              }}
              className="rounded-full p-1.5 text-zinc-500 hover:bg-white/5 hover:text-red-400"
            >
              <Trash2 size={13} />
            </button>
          </Box>
        ))}

        <button
          type="button"
          onClick={onAddHeadlineVariant}
          className="text-primary-text/30! hover:text-primary-text/90! mt-3.5 flex w-fit cursor-pointer items-center gap-1 text-[8px]!"
        >
          <Plus size={12} /> Add another headline
        </button>
      </Box>

      {/* Body */}
      <Box className="flex! flex-col!">
        <Box className="mb-1.75! flex! items-center! justify-between!">
          <Text fw={700} fz={12} className="text-primary-text/80!">
            Body
          </Text>
          <SoftCounter len={(creative.body || '').length} max={limits.body_max} />
        </Box>
        <Box className="relative">
          <Textarea
            value={creative.body || ''}
            onChange={(e) =>
              onPatchCreative({
                body: e.currentTarget.value,
              })
            }
            placeholder="e.g. Sensitive skin? Harsh chemicals can make it worse. Our plant-based formulas soothe and nourish from day one."
            maxLength={limits.body_max}
            autosize
            minRows={3}
            maxRows={5}
            classNames={{
              input:
                'bg-primary-text/4! border-primary-text/9! shadow-[0px_1px_0px_0px_#FFFFFF0D_inset]! text-primary-text! rounded-xl! text-xs! px-2.5! py-2! pr-9!',
              section: 'items-start! pt-2.5! pr-2.5!',
            }}
            rightSection={
              <button
                type="button"
                onClick={onSparkleBody}
                title="Fill with AI idea"
                className="bg-primary-text/8! border-primary-text/14! text-primary-text/80! hover:bg-primary-text/10! hover:text-primary-text! flex h-5.5! w-5.5! cursor-pointer! items-center justify-center! rounded-full! border! transition-colors!"
              >
                <Sparkles size={12} />
              </button>
            }
          />
        </Box>

        {/* Body variants */}
        {(creative.body_variants ?? []).map((variant, vIdx) => (
          <Box key={vIdx} className="mt-2! flex! items-start! gap-2!">
            <Textarea
              value={variant}
              onChange={(e) => {
                const next = [...(creative.body_variants ?? [])];
                next[vIdx] = e.currentTarget.value;
                onPatchCreative({
                  body_variants: next,
                });
              }}
              placeholder={`Body variant ${vIdx + 2}`}
              maxLength={limits.body_max}
              autosize
              minRows={2}
              className="flex-1"
              classNames={{
                input:
                  'bg-primary-text/4! border-primary-text/9! shadow-[0px_1px_0px_0px_#FFFFFF0D_inset]! text-primary-text! rounded-xl! text-xs! pt-5!',
              }}
            />
            <button
              type="button"
              onClick={() => {
                const next = (creative.body_variants ?? []).filter(
                  (_, j) => j !== vIdx
                );
                onPatchCreative({
                  body_variants: next.length ? next : null,
                });
              }}
              className="rounded-full p-1.5 text-zinc-500 hover:bg-white/5 hover:text-red-400"
            >
              <Trash2 size={13} />
            </button>
          </Box>
        ))}

        <button
          type="button"
          onClick={onAddBodyVariant}
          className="text-primary-text/30! hover:text-primary-text/90! mt-3.5 flex w-fit cursor-pointer items-center gap-1 text-[8px]!"
        >
          <Plus size={12} /> Add another body
        </button>
      </Box>

      {/* Description */}
      <Box className="flex! flex-col!">
        <Box className="mb-1.75! flex! items-center! justify-between!">
          <Text fw={700} fz={12} className="text-primary-text/80!">
            Description
          </Text>
          <SoftCounter len={(creative.description || '').length} max={limits.description_max} />
        </Box>
        <TextInput
          value={creative.description || ''}
          onChange={(e) =>
            onPatchCreative({
              description: e.currentTarget.value || null,
            })
          }
          placeholder="e.g. Cruelty-Free & Vegan Formulas"
          maxLength={limits.description_max}
          classNames={{
            input:
              'bg-primary-text/4! border-primary-text/9! shadow-[0px_1px_0px_0px_#FFFFFF0D_inset]! text-primary-text! rounded-[49px]! text-xs! h-10! px-3.5! pb-0.75!',
          }}
          rightSection={
            <button
              type="button"
              onClick={onSparkleDescription}
              title="Fill with AI idea"
              className="bg-primary-text/8! border-primary-text/14! text-primary-text/80! hover:bg-primary-text/10! hover:text-primary-text! flex h-5.5! w-5.5! cursor-pointer! items-center justify-center! rounded-full! border! transition-colors!"
            >
              <Sparkles size={12} />
            </button>
          }
        />
      </Box>

      {/* Call to action */}
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
            position: 'bottom-start',
            offset: 2,
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

      {/* Link */}
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
      </Box>

      {/* URL parameters */}
      <Box className="-mb-3.5! flex! flex-col! pb-4">
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
  );
}
