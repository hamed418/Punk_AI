import React from 'react';
import { Box, Button, Text } from '@mantine/core';
import { ArrowRight } from 'lucide-react';
import type { CampaignAssetsModalFooterProps } from './types';

export default function CampaignAssetsModalFooter({
  adsOnly,
  onClose,
  onSubmit,
}: CampaignAssetsModalFooterProps) {
  return (
    <Box className="border-primary-text/6! bg-primary-text/1! flex! shrink-0! items-center! justify-end! gap-2! border-t! px-4! py-3!">
      <Box className="flex! items-center! gap-2! sm:gap-3.5!">
        <Button
          variant="transparent"
          type="button"
          onClick={onClose}
          className="border-primary-text/14! text-primary-text/80! hover:bg-primary-text/5! rounded-[53px]! border! pb-0.5! text-[13px]! font-bold! transition-colors!"
        >
          Back
        </Button>

        {!adsOnly && (
          <Button
            type="button"
            onClick={() => onSubmit('save')}
            className="border-primary-text/16! bg-primary-text/10! text-primary-text! hover:bg-primary-text/5! rounded-[53px]! border! transition-all!"
          >
            Save
          </Button>
        )}

        <Button
          type="button"
          onClick={() => onSubmit('publish')}
          className="border-primary-text/16! bg-primary-text/10! text-primary-text! hover:bg-primary-text/5! flex! items-center! gap-1.5! rounded-[53px]! border! transition-all!"
          style={{
            boxShadow:
              '0px 2px 6px 0px #00000033, 0px 8px 32px 0px #00000059, 0px 1.5px 0px 0px #FFFFFF59 inset',
          }}
        >
          <Text
            fz={{ base: 12, sm: 13 }}
            fw={600}
            className="text-primary-text! mr-1! sm:mr-2!"
          >
            {adsOnly ? 'Continue' : 'To Review'}
          </Text>
          <ArrowRight size={13} className="mt-0.5!" />
        </Button>
      </Box>
    </Box>
  );
}
