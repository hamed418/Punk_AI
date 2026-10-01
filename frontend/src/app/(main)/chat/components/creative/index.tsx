/* eslint-disable react-hooks/set-state-in-effect */
'use client';
import {
  ChevronDown,
  ChevronUp,
  Sparkles,
  Upload,
  Image as ImageIcon,
  Video,
  Play,
  GripVertical,
  X,
  Plus,
} from 'lucide-react';
import { useState, useRef, forwardRef, useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';
import SecondaryBtn from '@/components/secondaryBtn';
import SecondaryActionIcon from '@/components/SecondaryActionIcon';
import WidgetHeaderV2 from '@/components/WidgetHeaderV2';
import { Box, Flex, Menu, Text, Textarea, Modal } from '@mantine/core';
import { useParams } from 'next/navigation';
import CreateAssetModal from './CreateAssetModal';
import GenerateAdOverlay from './GenerateAdOverlay';
import { uploadMediaAction } from '@/actions/chat.actions';

interface CampaignAsset {
  id: string;
  type: 'image' | 'video';
  name: string;
  displayName: string;
  size: string;
  url?: string;
}

export default function UploadCampaignContentUI({
  content,
  onConfirm,
}: {
  content?: Record<string, unknown> | null;
  onConfirm?: (value: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const [showCreateAsset, setShowCreateAsset] = useState(false);
  const [generatingAd, setGeneratingAd] = useState<'image' | 'video' | null>(
    null
  );
  const [assets, setAssets] = useState<CampaignAsset[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const params = useParams();
  const threadId = params.threadId as string;

  const activeContent = content || {};

  const [ctaValue, setCtaValue] = useState('');
  const [headlineValue, setHeadlineValue] = useState('');
  const [bodyCopyValue, setBodyCopyValue] = useState('');

  const { cta_options, headline_suggestions, body_copy_suggestions } =
    (activeContent.ad_copy || {}) as Record<string, string[]>;

  useEffect(() => {
    if (cta_options?.length > 0 && !ctaValue) {
      setCtaValue(cta_options[0]);
    }
    if (headline_suggestions?.length > 0 && !headlineValue) {
      setHeadlineValue(headline_suggestions[0]);
    }
    if (body_copy_suggestions?.length > 0 && !bodyCopyValue) {
      setBodyCopyValue(body_copy_suggestions[0]);
    }
  }, [
    cta_options,
    headline_suggestions,
    body_copy_suggestions,
    ctaValue,
    headlineValue,
    bodyCopyValue,
  ]);

  const removeAsset = (index: number) => {
    setAssets((prev) => prev.filter((_, i) => i !== index));
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const files = Array.from(e.target.files);
      for (const file of files) {
        try {
          const formData = new FormData();
          formData.append('file', file);
          const res = await uploadMediaAction(formData);

          if (res.success && res.data) {
            setAssets((prev) => [
              ...prev,
              {
                id: res.data.id,
                type: file.type.startsWith('video') ? 'video' : 'image',
                name: file.name,
                displayName: file.name,
                size: (file.size / 1024 / 1024).toFixed(1) + ' MB',
                url: res.data.file_path,
              },
            ]);
          } else {
            console.error('Failed to upload media:', res.error);
          }
        } catch (err) {
          console.error('Failed to upload media:', err);
        }
      }

      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const videoAssets = assets.filter((a) => a.type === 'video');
  const imageAssets = assets.filter((a) => a.type === 'image');

  return (
    <>
      <Box className="relative mx-auto max-w-[900px] rounded-[30px]">
        <Box
          className="border-stroke-widget bg-primary-widget! shadow-widget! light:shadow-lg! text-primary-text w-full overflow-hidden rounded-[30px] border transition-opacity duration-300"
          style={{
            backdropFilter: 'blur(75.9px)',
          }}
        >
          <AnimatePresence>
            {generatingAd && (
              <GenerateAdOverlay
                type={generatingAd}
                threadId={threadId}
                onClose={() => setGeneratingAd(null)}
                onAdd={(generated) => {
                  setAssets((prev) => [
                    ...prev,
                    ...generated.map((asset) => ({
                      id:
                        asset.id || Math.random().toString(36).substring(2, 9),
                      type: asset.type,
                      name: asset.name,
                      displayName: asset.name,
                      size: '---', // or generated size
                      url: asset.url,
                    })),
                  ]);
                  setGeneratingAd(null);
                }}
              />
            )}
          </AnimatePresence>

          <CreateAssetModal
            open={showCreateAsset}
            onClose={() => setShowCreateAsset(false)}
            onCreateAd={(type) => setGeneratingAd(type)}
          />

          {/* Header */}
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className={`flex w-full cursor-pointer items-center justify-between px-5 pt-5 pb-4 text-left ${
              open
                ? 'border-underline/15 border-b'
                : 'border-b border-transparent'
            }`}
          >
            <WidgetHeaderV2
              icon={<Upload size={16} className="text-primary-text" />}
              title="Upload campaign content"
              subtitle="Spring Launch · Draft"
            />
            {open ? (
              <ChevronDown size={14} className="text-secondary-text" />
            ) : (
              <ChevronUp size={14} className="text-secondary-text" />
            )}
          </button>

          <AnimatePresence initial={false}>
            {open && (
              <motion.div
                initial={{ height: 0, opacity: 0, overflow: 'hidden' }}
                animate={{
                  height: 'auto',
                  opacity: 1,
                  transitionEnd: { overflow: 'visible' },
                }}
                exit={{ height: 0, opacity: 0, overflow: 'hidden' }}
                transition={{ duration: 0.2, ease: 'easeInOut' }}
              >
                {/* Body */}
                <div className="custom-textarea-scrollbar grid max-h-[calc(100vh-280px)] grid-cols-1 gap-6 overflow-y-auto p-6 md:grid-cols-2">
                  {/* Left: Ad copy */}
                  <div>
                    <div className="mb-5 flex items-center gap-2">
                      <SecondaryActionIcon
                        size={20}
                        radius="sm"
                        className="pointer-events-none"
                      >
                        <span className="text-[11px]">1</span>
                      </SecondaryActionIcon>
                      <span className="text-secondary-text/80 text-xs font-medium tracking-wide">
                        AD COPY
                      </span>
                    </div>

                    <Field
                      label="Call to action"
                      count={`${ctaValue.replace(/_/g, ' ').length}/40`}
                      value={ctaValue.replace(/_/g, ' ')}
                      suggestions={cta_options?.map((opt: string) =>
                        opt.replace(/_/g, ' ')
                      )}
                      inputClassName="rounded-4xl!"
                      onSuggestionSelect={setCtaValue}
                    />
                    <Field
                      label="Headline"
                      count={`${headlineValue.length}/60`}
                      value={headlineValue}
                      inputClassName="rounded-4xl!"
                      suggestions={headline_suggestions}
                      onSuggestionSelect={setHeadlineValue}
                    />

                    <div>
                      <Flex
                        justify={'space-between'}
                        align={'center'}
                        className="mb-1.5"
                      >
                        <Flex align={'center'} gap={8}>
                          <span className="text-secondary-text text-[13px]">
                            Body copy
                          </span>
                          <span className="text-secondary-text/80 mt-1 text-[11px]">
                            {bodyCopyValue.length}/280
                          </span>
                        </Flex>
                        <Box>
                          <Menu
                            width={395}
                            position="bottom-end"
                            withinPortal
                            zIndex={1000000}
                            classNames={{
                              dropdown:
                                'bg-primary-widget! border border-stroke-widget! shadow-widget! light:shadow-lg! rounded-2xl! max-h-[300px] overflow-y-auto overflow-x-hidden custom-textarea-scrollbar',
                              item: 'text-primary-text/80! hover:text-black! hover:bg-[#FFFFFF90]! light:hover:bg-[#FFFFFF]! data-[hovered]:text-black! data-[hovered]:bg-[#D9D9D9]! data-[selected]:text-primary-text! font-semibold! text-[13px]! rounded-lg! my-0.5! transition-colors duration-200 bg-transparent! data-[selected]:bg-white/10! data-[selected]:light:bg-[#15151512]!',
                            }}
                            styles={{
                              dropdown: {
                                backdropFilter: 'blur(75.9px)',
                                WebkitBackdropFilter: 'blur(75.9px)',
                              },
                            }}
                          >
                            <Menu.Target>
                              <PunkPill />
                            </Menu.Target>
                            <Menu.Dropdown>
                              {body_copy_suggestions?.map(
                                (s: string, i: number) => (
                                  <Menu.Item
                                    key={i}
                                    onClick={() => setBodyCopyValue(s)}
                                  >
                                    <div className="flex w-full items-center gap-2">
                                      <span className="block text-[13px] whitespace-normal text-inherit">
                                        {s}
                                      </span>
                                    </div>
                                  </Menu.Item>
                                )
                              )}
                            </Menu.Dropdown>
                          </Menu>
                        </Box>
                      </Flex>
                      <Textarea
                        variant="unstyled"
                        value={bodyCopyValue}
                        autosize
                        maxRows={6}
                        minRows={4}
                        onChange={(e) =>
                          setBodyCopyValue(e.currentTarget.value)
                        }
                        className="border-underline/15 w-full rounded-xl border bg-transparent px-2"
                        classNames={{
                          input:
                            'text-primary-text! text-[13px]! p-3.5 w-full custom-textarea-scrollbar',
                        }}
                      />
                    </div>
                  </div>

                  {/* Right: Campaign assets */}
                  <div>
                    <div className="mb-5 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <SecondaryActionIcon
                          size={20}
                          radius="sm"
                          className="pointer-events-none"
                        >
                          <span className="text-[11px]">2</span>
                        </SecondaryActionIcon>
                        <span className="text-secondary-text/80 text-xs font-medium tracking-wide">
                          CAMPAIGN ASSETS
                        </span>
                      </div>
                      {assets.length > 0 ? (
                        <button
                          onClick={() => fileInputRef.current?.click()}
                          className="bg-secondary-widget border-stroke-widget text-secondary-text/90 flex cursor-pointer items-center gap-1 rounded-full border px-2.5 py-1.5 text-[11px] font-medium shadow-sm transition-colors hover:bg-white/5"
                        >
                          <Plus size={12} />
                          <Text fz={12} fw={500}>
                            Add files
                          </Text>
                        </button>
                      ) : (
                        <PunkPill onClick={() => setShowCreateAsset(true)} />
                      )}
                    </div>

                    {assets.length === 0 ? (
                      <div
                        onClick={() => fileInputRef.current?.click()}
                        className="border-underline/15 cursor-pointer rounded-2xl border border-dashed bg-transparent px-5 py-12 text-center transition-colors hover:bg-white/5"
                      >
                        <SecondaryActionIcon
                          size={36}
                          radius="xl"
                          className="pointer-events-none mx-auto mb-3.5"
                        >
                          <Upload size={16} />
                        </SecondaryActionIcon>
                        <p className="text-secondary-text text-[13px]">
                          Drop files or{' '}
                          <span className="text-primary-text underline underline-offset-2">
                            browse
                          </span>
                        </p>
                        <p className="text-secondary-text/80 mt-1.5 text-[11px]">
                          Images · Video &amp; Reels · Documents — auto-sorted
                        </p>
                      </div>
                    ) : (
                      <div className="flex flex-col gap-4">
                        {videoAssets.length > 0 && (
                          <AssetGroup
                            label="Video & Reels"
                            count={videoAssets.length}
                            icon={
                              <Video
                                size={13}
                                className="text-secondary-text"
                              />
                            }
                            items={videoAssets}
                            onRemove={(id) =>
                              removeAsset(assets.findIndex((a) => a.id === id))
                            }
                          />
                        )}
                        {imageAssets.length > 0 && (
                          <AssetGroup
                            label="Images"
                            count={imageAssets.length}
                            icon={
                              <ImageIcon
                                size={13}
                                className="text-secondary-text"
                              />
                            }
                            items={imageAssets}
                            onRemove={(id) =>
                              removeAsset(assets.findIndex((a) => a.id === id))
                            }
                          />
                        )}

                        <button
                          onClick={() => fileInputRef.current?.click()}
                          className="border-underline/15 flex items-center justify-center gap-1.5 rounded-xl border bg-transparent py-3.5 text-[13px] font-medium transition-colors hover:bg-white/5"
                        >
                          <Plus size={14} />
                          <Text fz={12} fw={500} className="text-primary-text!">
                            Upload
                          </Text>
                        </button>
                      </div>
                    )}
                  </div>
                </div>

                {/* Footer */}
                <div className="border-underline/15 flex items-center justify-between border-t px-6 py-4">
                  <SecondaryBtn radius="xl" size="sm">
                    Discard
                  </SecondaryBtn>
                  <PrimaryGlassBtn
                    radius="xl"
                    size="sm"
                    leftSection={<Upload size={14} />}
                    onClick={() => {
                      if (onConfirm) {
                        onConfirm(
                          JSON.stringify({
                            cta: ctaValue,
                            headline: headlineValue,
                            body: bodyCopyValue,
                            media_ids: assets.map((a) => a.id),
                            media_urls: assets
                              .map((a) => a.url)
                              .filter(Boolean),
                          })
                        );
                      }
                    }}
                  >
                    Upload
                  </PrimaryGlassBtn>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </Box>

      </Box>

      {/* Hidden file input for native file browsing */}
      <input
        type="file"
        multiple
        ref={fileInputRef}
        onChange={handleFileChange}
        className="hidden"
        accept="image/*,video/*"
      />
    </>
  );
}

function AssetGroup({
  label,
  count,
  icon,
  items,
  onRemove,
}: {
  label: string;
  count: number;
  icon: React.ReactNode;
  items: CampaignAsset[];
  onRemove: (id: string) => void;
}) {
  const [previewAsset, setPreviewAsset] = useState<CampaignAsset | null>(null);

  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5">
        {icon}
        <span className="text-secondary-text text-[12px] font-medium">
          {label}
        </span>
        <span className="text-secondary-text/60 text-[12px]">{count}</span>
      </div>
      <div className="flex flex-col gap-2">
        {items.map((asset) => (
          <div
            key={asset.id}
            className="group border-underline/15 flex items-center justify-between rounded-xl border bg-transparent px-3 py-2.5"
          >
            <div className="flex items-center gap-3">
              {asset.type === 'video' ? (
                <div
                  onClick={() => asset.url && setPreviewAsset(asset)}
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${asset.url ? 'cursor-pointer hover:bg-white/10' : 'bg-white/5'} light:bg-[#FFFFFF30]!`}
                >
                  <Play
                    size={14}
                    className="text-secondary-text"
                    fill="currentColor"
                  />
                </div>
              ) : asset.url ? (
                <img
                  src={asset.url}
                  alt={asset.displayName}
                  onClick={() => setPreviewAsset(asset)}
                  className="h-9 w-9 shrink-0 cursor-pointer rounded-lg object-cover transition-opacity hover:opacity-80"
                />
              ) : (
                <div className="light:bg-[#1515150D]! flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/5">
                  <ImageIcon size={14} className="text-secondary-text" />
                </div>
              )}
              <div className="flex flex-col">
                <span className="text-primary-text text-[13px] font-medium">
                  {asset.displayName}
                </span>
                <span className="text-secondary-text/60 text-[11px]">
                  {asset.size}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <button className="text-secondary-text/60 flex h-6 w-6 cursor-grab items-center justify-center">
                <GripVertical size={14} />
              </button>
              <button
                onClick={() => onRemove(asset.id)}
                className="text-secondary-text/60 hover:text-primary-text flex h-6 w-6 items-center justify-center rounded-full transition-colors hover:bg-white/10"
              >
                <X size={14} />
              </button>
            </div>
          </div>
        ))}
      </div>

      <Modal
        opened={!!previewAsset}
        onClose={() => setPreviewAsset(null)}
        title={previewAsset?.displayName || 'Preview'}
        size="xl"
        zIndex={1000000}
        centered
        classNames={{
          content:
            'bg-primary-widget! border border-stroke-widget! text-primary-text!',
          header: 'bg-transparent!',
          title: 'text-primary-text! font-medium',
          close:
            'text-secondary-text hover:text-primary-text hover:bg-white/10',
        }}
        styles={{
          content: {
            backdropFilter: 'blur(75.9px)',
            WebkitBackdropFilter: 'blur(75.9px)',
          },
        }}
      >
        {previewAsset && (
          <div className="flex items-center justify-center p-2">
            {previewAsset.type === 'video' ? (
              <video
                src={previewAsset.url}
                controls
                autoPlay
                className="max-h-[70vh] w-full rounded-xl object-contain"
              />
            ) : (
              <img
                src={previewAsset.url}
                alt={previewAsset.displayName}
                className="max-h-[70vh] w-full rounded-xl object-contain"
              />
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}

function Field({
  label,
  count,
  value,
  onPunkClick,
  suggestions,
  className,
  inputClassName,
  onSuggestionSelect,
}: {
  label: string;
  count: string;
  value: string;
  onPunkClick?: () => void;
  suggestions?: string[];
  className?: string;
  inputClassName?: string;
  onSuggestionSelect?: (val: string) => void;
}) {
  return (
    <div className={`mb-4 ${className}`}>
      <div className="mb-1.5 flex justify-between">
        <span className="text-secondary-text text-[13px]">{label}</span>
        <span className="text-secondary-text/80 text-[11px]">{count}</span>
      </div>
      <div
        className={`border-underline/15 flex items-center justify-between gap-2 rounded-xl border bg-transparent px-2 py-2 ${inputClassName}`}
      >
        {label.toLowerCase() === 'headline' ? (
          <input
            type="text"
            value={value}
            onChange={(e) => onSuggestionSelect?.(e.target.value)}
            className="text-primary-text ml-2 min-w-0 flex-1 border-0 bg-transparent p-0 text-[13px]! outline-none focus:ring-0 focus:outline-none"
          />
        ) : (
          <span className="text-primary-text ml-2 text-[12px]">{value}</span>
        )}
        {suggestions && suggestions.length > 0 ? (
          <Menu
            shadow="sm"
            width={280}
            position="bottom-end"
            withinPortal
            zIndex={1000000}
            classNames={{
              dropdown:
                'bg-primary-widget! border border-stroke-widget! pr-3! shadow-widget! light:shadow-lg! rounded-2xl! max-h-[300px] overflow-y-auto overflow-x-hidden custom-textarea-scrollbar',
              item: 'text-primary-text/80! hover:text-black! hover:bg-[#FFFFFF90]! light:hover:bg-[#FFFFFF]! data-[hovered]:text-black! data-[hovered]:bg-[#D9D9D9]! data-[selected]:text-primary-text! font-semibold! text-[13px]! rounded-lg! mx-1! my-0.5! transition-colors duration-200 bg-transparent! data-[selected]:bg-white/10! data-[selected]:light:bg-[#15151512]!',
            }}
            styles={{
              dropdown: {
                backdropFilter: 'blur(75.9px)',
                WebkitBackdropFilter: 'blur(75.9px)',
              },
            }}
          >
            <Menu.Target>
              <PunkPill />
            </Menu.Target>
            <Menu.Dropdown>
              {suggestions.map((s, i) => (
                <Menu.Item key={i} onClick={() => onSuggestionSelect?.(s)}>
                  <div className="flex w-full items-center gap-2">
                    <span className="block text-[13px] whitespace-normal text-inherit">
                      {s}
                    </span>
                  </div>
                </Menu.Item>
              ))}
            </Menu.Dropdown>
          </Menu>
        ) : (
          <PunkPill onClick={onPunkClick} />
        )}
      </div>
    </div>
  );
}

const PunkPill = forwardRef<
  HTMLButtonElement,
  { className?: string; onClick?: () => void }
>(({ className = '', onClick, ...props }, ref) => {
  return (
    <button
      ref={ref}
      onClick={onClick}
      className={`light:bg-[linear-gradient(0deg,#EEEEEC,#EEEEEC),_linear-gradient(0deg,#FAF9F5,#FAF9F5)]! border-stroke-widget text-secondary-text/80 flex shrink-0 cursor-pointer items-center gap-1 rounded-full border bg-[#FFFFFF08] px-3 py-1 text-[11px] shadow-md! transition-colors hover:bg-white/5 ${className}`}
      {...props}
    >
      <Sparkles size={10} className="text-primary-text" />
      <Text fz={11} fw={500} className="text-primary-text">
        Punk ideas
      </Text>
    </button>
  );
});
PunkPill.displayName = 'PunkPill';
