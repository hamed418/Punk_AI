import { Select, Checkbox, Loader } from '@mantine/core';
import SecondaryBtn from '@/components/secondaryBtn';
import type { EditorCatalog, CampaignTreeAdSet } from '@/types/chat';
import { selectClassNames } from './editorUtils';

interface Props {
  previousCampaigns?: EditorCatalog['previous_campaigns'];
  templateId: string | null;
  onPickTemplate: (id: string | null) => void;
  templateLoading: boolean;
  templateTree: CampaignTreeAdSet[];
  pickedAdsets: Set<string>;
  pickedAds: Set<string>;
  onToggleAdset: (adset: CampaignTreeAdSet, on: boolean) => void;
  onToggleAd: (adId: string, on: boolean) => void;
  onApplyTemplate: () => void;
}

export default function CampaignTemplatePicker({
  previousCampaigns,
  templateId,
  onPickTemplate,
  templateLoading,
  templateTree,
  pickedAdsets,
  pickedAds,
  onToggleAdset,
  onToggleAd,
  onApplyTemplate,
}: Props) {
  if (!previousCampaigns) return null;

  return (
    <div className="mb-4 mx-2">
      <Select
        label="Start from a previous campaign"
        description="Reuses its objective, optimization goal, bidding and ad copy. Your geo and audience stay as they are."
        data={previousCampaigns.map((c) => ({
          value: c.id,
          label: c.created_time
            ? `${c.name} — ${c.created_time.slice(0, 10)}`
            : c.name,
        }))}
        value={templateId}
        clearable
        disabled={!previousCampaigns.length}
        placeholder={
          previousCampaigns.length
            ? 'Set up fresh'
            : 'No previous campaigns on this ad account'
        }
        onChange={onPickTemplate}
        classNames={{
          ...selectClassNames,
          label: 'font-medium! text-xs! text-primary-text!',
          description: 'text-primary-text/70! opacity-80! text-[11px]! mb-2!',
        }}
        comboboxProps={{ withinPortal: true, zIndex: 1000001 }}
      />

      {templateId && (
        <div className="border-underline/15 mt-3 rounded-xl border p-3">
          {templateLoading ? (
            <div className="text-secondary-text flex items-center gap-2 text-[12px]">
              <Loader size={13} /> Reading that campaign…
            </div>
          ) : templateTree.length === 0 ? (
            <div className="text-secondary-text text-[12px]">
              Couldn&apos;t read this campaign&apos;s ad sets —
              Apply will copy the whole campaign.
            </div>
          ) : (
            <>
              <div className="text-secondary-text mb-2 text-[12px]">
                What to copy from it
              </div>
              <div className="flex flex-col gap-2">
                {templateTree.map((as) => (
                  <div key={as.id}>
                    <Checkbox
                      size="xs"
                      label={as.name}
                      checked={pickedAdsets.has(as.id)}
                      onChange={(e) =>
                        onToggleAdset(as, e.currentTarget.checked)
                      }
                      classNames={{
                        label:
                          'text-primary-text! text-[13px]! cursor-pointer',
                      }}
                    />
                    {as.ads.length > 0 && (
                      <div className="mt-1.5 ml-6 flex flex-col gap-1.5">
                        {as.ads.map((ad) => (
                          <Checkbox
                            key={ad.id}
                            size="xs"
                            label={ad.name}
                            checked={pickedAds.has(ad.id)}
                            disabled={!pickedAdsets.has(as.id)}
                            onChange={(e) =>
                              onToggleAd(ad.id, e.currentTarget.checked)
                            }
                            classNames={{
                              label:
                                'text-secondary-text! text-[12px]! cursor-pointer',
                            }}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <div className="text-secondary-text/70 mt-2 text-[11px]">
                Untick every ad under an ad set to copy its settings and keep your own copy.
              </div>
            </>
          )}

          <div className="mt-3 flex justify-end">
            <SecondaryBtn
              radius="xl"
              size="xs"
              disabled={
                templateLoading ||
                (templateTree.length > 0 && pickedAdsets.size === 0)
              }
              onClick={onApplyTemplate}
            >
              Apply selection
            </SecondaryBtn>
          </div>
        </div>
      )}
    </div>
  );
}
