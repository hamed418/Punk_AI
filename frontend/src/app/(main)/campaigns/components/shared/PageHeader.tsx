'use client';

import {
  Box,
  Flex,
  Text,
  SegmentedControl,
  Select,
  Button,
  useMantineColorScheme,
} from '@mantine/core';
import type { Campaign } from '../dummyData';
import { Plus } from 'lucide-react';
import Link from 'next/link';

interface PageHeaderProps {
  data: Campaign[];
  activeTab: string;
  setActiveTab: (tab: string) => void;
  campaignTypeFilter: string;
  setCampaignTypeFilter: (value: string) => void;
}

const PageHeader = ({
  data,
  activeTab,
  setActiveTab,
  campaignTypeFilter,
  setCampaignTypeFilter,
}: PageHeaderProps) => {
  const { colorScheme } = useMantineColorScheme();
  const isLight = colorScheme === 'light';
  const tabs = ['All', 'Running', 'Ended'];

  const getCount = (tab: string) => {
    const typeFiltered =
      campaignTypeFilter === 'All'
        ? data
        : data.filter((camp) => camp.campaignType === campaignTypeFilter);

    if (tab === 'Running') {
      return typeFiltered.filter((camp) => camp.status === 'Active').length;
    }
    if (tab === 'Ended') {
      return typeFiltered.filter((camp) => camp.status === 'Completed').length;
    }
    return typeFiltered.length;
  };

  const filteredCount = data.filter((camp) => {
    if (activeTab === 'Running' && camp.status !== 'Active') return false;
    if (activeTab === 'Ended' && camp.status !== 'Completed') return false;
    if (
      campaignTypeFilter !== 'All' &&
      camp.campaignType !== campaignTypeFilter
    )
      return false;
    return true;
  }).length;

  let totalSpend = 0;
  data.forEach((camp) => {
    const rawSpend = camp.rawSample?.spend;
    const parsed =
      typeof rawSpend === 'string' ? parseFloat(rawSpend) : Number(rawSpend);
    if (!isNaN(parsed)) {
      totalSpend += parsed;
    }
  });

  let activeCampaigns = 0;
  data.forEach((camp) => {
    if (camp.status === 'Active') {
      activeCampaigns += 1;
    }
  });

  return (
    <Box className="">
      <Box>
        <Flex
          direction={{ base: 'column-reverse', sm: 'row' }}
          align={{ base: 'start', sm: 'center' }}
          justify={'space-between'}
          gap={{ base: 4, sm: 0 }}
        >
          <Box>
            <Text fz={36} fw={700} className="text-primary-text sm:leading-0!">
              Campaigns
            </Text>
          </Box>
          <Box className="grid grid-cols-3 sm:flex items-center justify-center">
            <Box className="border-underline/50 flex flex-col items-start sm:items-end justify-center border-r sm:px-4">
              <Text
                fz={10}
                fw={600}
                className="text-secondary-text/50 uppercase"
              >
                total spend
              </Text>
              <Text fz={22} fw={700} className="font-body text-primary-text">
                {`$${totalSpend.toLocaleString('en-US', {
                  minimumFractionDigits: totalSpend % 1 !== 0 ? 2 : 0,
                  maximumFractionDigits: 2,
                })}`}
              </Text>
            </Box>
            <Box className="border-underline/50 flex flex-col items-start pl-4 sm:pl-0 sm:items-end justify-center border-r sm:px-4!">
              <Text
                fz={10}
                fw={600}
                className="text-secondary-text/50 uppercase"
              >
                active
              </Text>
              <Text fz={22} fw={700} className="font-body text-primary-text">
                {activeCampaigns}
              </Text>
            </Box>
            <Box className="pl-1 sm:pl-4 scale-80 sm:scale-100">
              <Button
                component={Link}
                href="/chat"
                radius={9999}
                leftSection={
                  <Plus
                    size={16}
                    strokeWidth={2}
                    className="text-primary-text"
                  />
                }
                className="light:bg-[#FAF9F5]! bg-[#ffffff]/16! transition-all duration-300 hover:opacity-90! active:scale-98!"
                styles={{
                  root: {
                    height: '38px',
                    paddingLeft: '16px',
                    paddingRight: '20px',
                    background: 'transparent',
                    // border: isLight ? '1px solid rgba(21, 21, 21, 0.08)' : 'none',
                    borderTop: '1px solid #FFFFFF29',
                    borderBottom: isLight
                      ? '1px solid rgba(21, 21, 21, 0.08)'
                      : '1px solid #FFFFFF29',
                    boxShadow: isLight
                      ? '0px 1.5px 0px 0px #FFFFFF59 inset, 0px 1px 6px 0px #00000033'
                      : '0px 2px 6px 0px #00000026, 0px 8px 32px 0px #0000004D, 0px 1.5px 0px 0px #FFFFFF59 inset',
                  },
                  label: {
                    fontSize: '13px',
                    fontWeight: 600,
                    color: '#ffffff',
                    textShadow: '0 1px 2px rgba(0,0,0,0.3)',
                  },
                }}
              >
                <span className="text-primary-text!">New chat</span>
              </Button>
            </Box>
          </Box>
        </Flex>
        <Box>
          <Text
            fw={400}
            fz={14}
            className="text-secondary-text/30 light:text-secondary-text/60"
          >
            All active and past campaigns across every objective, with the KPIs
            that matter per type.
          </Text>
        </Box>
      </Box>
      {/* Tabs and Filters Section */}
      <Flex
        direction={{ base: 'column', md: 'row' }}
        align="center"
        justify="space-between"
        gap={{ base: 12, md: 0 }}
        className="border-divider/30 my-6 w-full rounded-2xl border bg-white/5 px-2.5 py-2.5 sm:px-3 sm:py-2 backdrop-blur-3xl"
      >
        {/* Left Controls */}
        <Flex className='w-full! md:w-auto! ' direction={{base: "column", md: "row"}} align="center" gap={16}>
          <SegmentedControl
            value={activeTab}
            onChange={setActiveTab}
            className='w-full! md:w-auto!'
            data={tabs.map((tab) => {
              const isActive = activeTab === tab;
              return {
                label: (
                  <Flex align="center" justify="center" gap={6} className="px-3 py-1">
                    <span
                      className={`text-sm font-semibold transition-colors ${
                        isActive
                          ? 'light:text-primary-text! text-white'
                          : 'text-secondary-text/60!'
                      }`}
                    >
                      {tab}
                    </span>
                    <span
                      className={`text-xs transition-colors ${
                        isActive
                          ? 'light:text-secondary-text/90! text-white/70!'
                          : 'text-secondary-text/40!'
                      }`}
                    >
                      {getCount(tab)}
                    </span>
                  </Flex>
                ),
                value: tab,
              };
            })}
            radius="xl"
            bg="transparent"
            classNames={{
              root: 'border-0! bg-transparent! p-0!',
              indicator:
                'bg-[#ffffff]/15! light:bg-[#1515151F]! border border-white/20! shadow-none!',
              control: 'before:hidden!',
              label: 'bg-transparent!',
            }}
          />

          {/* Vertical Divider */}
          <span className="bg-divider/50 hidden h-5 w-0.5 min-[540px]:block" />

          {/* Campaign Type Dropdown */}
          <Flex align="center" className='w-full! md:w-auto!' justify={{ base: "space-between", xl: "start" }} gap={8}>
            <Text
              // size="sm"
              className="text-secondary-text/50 light:text-secondary-text/70! font-medium! whitespace-nowrap! text-sm! xl:text-base!"
            >
              Campaign Type
            </Text>
            <Select
              value={campaignTypeFilter}
              onChange={(val) => setCampaignTypeFilter(val || 'All')}
              data={[
                { value: 'All', label: 'All' },
                { value: 'Awareness', label: 'Awareness' },
                { value: 'Traffic', label: 'Traffic' },
                { value: 'Engagement', label: 'Engagement' },
                { value: 'LeadGeneration', label: 'Lead Generation' },
                { value: 'AppPromotion', label: 'App Promotion' },
                { value: 'SalesConversion', label: 'Sales' },
              ]}
              allowDeselect={false}
              w={{base:160, md: 120, lg:140, xl:160}}
              classNames={{
                input:
                  'bg-[#ffffff]/8! border border-white/10! text-primary-text! light:bg-[#15151508]! light:border-black/10!',
                dropdown:
                  'bg-primary-widget! w-[160px]! border border-stroke-widget! shadow-widget! light:shadow-lg! rounded-2xl!',
                option:
                  'text-primary-text/80! data-[hovered]:text-primary-text! data-[selected]:text-primary-text! font-semibold! text-[13px]! rounded-lg! mx-1! my-0.5! transition-colors duration-200 bg-transparent! data-[hovered]:bg-white/10! data-[hovered]:light:bg-[#15151512]! data-[selected]:bg-white/10! data-[selected]:light:bg-[#15151512]!',
              }}
              styles={{
                input: {
                  borderRadius: '12px',
                  fontWeight: 600,
                  height: '36px',
                  minHeight: '36px',
                  cursor: 'pointer',
                  paddingLeft: '12px',
                  paddingRight: '32px',
                },
                dropdown: {
                  backdropFilter: 'blur(75.9px)',
                  WebkitBackdropFilter: 'blur(75.9px)',
                  width: '250px',
                },
              }}
            />
          </Flex>
        </Flex>

        {/* Right Info */}
        <Text size="sm" className="text-secondary-text/50 font-medium text-center md:text-right">
          {filteredCount} of {data.length} campaigns
        </Text>
      </Flex>
    </Box>
  );
};

export default PageHeader;
