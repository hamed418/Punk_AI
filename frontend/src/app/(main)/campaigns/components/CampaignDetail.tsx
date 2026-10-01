'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  ArrowLeft,
  ChevronDown,
  ChevronUp,
  Calendar,
  ListFilter,
  BarChart3,
} from 'lucide-react';
import { Popover, Checkbox, Text, Box, Flex, Center, Loader } from '@mantine/core';
import { motion, AnimatePresence } from 'framer-motion';
import {
  type BarPoint,
  type Campaign,
  type CampaignBreakdown,
  type GroupedBarPoint,
  type TrendPoint,
  campaigns as dummyCampaigns,
} from './dummyData';
import GroupedBarChart from './charts/GroupedBarChart';
import HorizontalBarChart from './charts/HorizontalBarChart';
import MultiLineChart from './charts/MultiLineChart';
import SingleAreaChart from './charts/SingleAreaChart';
import VerticalBarChart from './charts/VerticalBarChart';
import CampaignNotFound from './CampaignNotFound';
import { useCampaign, useCampaignReview } from '@/hooks/api/useCampaignsApi';
import { MetaFixItList } from '@/components/MetaFixItCard';
import { mapCampaignResponseToUI } from './CampaignList';

function resolveSource(
  camp: Campaign,
  source: string
): TrendPoint[] | BarPoint[] | GroupedBarPoint[] {
  if (source === 'trend') return camp.trend;
  if (source.startsWith('breakdown.')) {
    const key = source.slice('breakdown.'.length) as keyof CampaignBreakdown;
    return (
      (camp.breakdown[key] as TrendPoint[] | BarPoint[] | GroupedBarPoint[]) ??
      []
    );
  }
  return [];
}

function groupKeysFrom(data: GroupedBarPoint[]): string[] {
  if (!data.length) return [];
  return Object.keys(data[0]).filter((k) => k !== 'label');
}

function ChartCard({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="relative flex h-full flex-col overflow-hidden rounded-2xl"
      style={{
        background: '#FAF9F505',
        boxShadow:
          '0px -1px 0px 0px #00000066 inset, 0px 1px 0px 0px #FFFFFF1F inset, 0px 8px 24px 0px #00000080',
        backdropFilter: 'blur(60.6px)',
      }}
    >
      {/* Header row: title+subtitle left | value+change right */}
      <div className="border-underline/30 mb-4 flex items-start justify-between border-b p-4">
        {/* Left: title + subtitle */}
        <div className="flex flex-col gap-0.5">
          <span className="text-primary-text text-[15px] font-semibold">
            {title}
          </span>
          <span className="text-secondary-text/60 text-[11px] font-normal">
            Daily delivery
          </span>
        </div>

        {/* Right: value + % change */}
        <div className="flex flex-col items-end gap-0.5">
          <span className="text-primary-text text-[22px] leading-tight font-bold tracking-tight">
            5,420
          </span>
          <span className="text-[11px] font-semibold text-[#4ADE80]">+52%</span>
        </div>
      </div>

      <div className="mt-6 px-4 pb-6">{children}</div>
    </div>
  );
}

// ─── Main component

interface CampaignDetailProps {
  threadId: string;
}

const CampaignDetail = ({ threadId }: CampaignDetailProps) => {
  const router = useRouter();

  const { data: apiCamp, isLoading } = useCampaign(threadId);
  const { data: review } = useCampaignReview(threadId);
  const dummyCamp = dummyCampaigns.find(
    (c) => c.id === threadId || c.campaignId === threadId
  );
  const camp = apiCamp ? mapCampaignResponseToUI(apiCamp) : dummyCamp;

  const allChartsConfigs = camp
    ? [...camp.charts.trend, ...camp.charts.comparison]
    : [];
  const metricsOptions = allChartsConfigs.map((c) => c.title);

  const [selectedMetrics, setSelectedMetrics] = useState<string[]>(
    metricsOptions.slice(0, 6)
  );
  const [open, setOpen] = useState(true);
  const [metricsOpen, setMetricsOpen] = useState(false);

  const MAX_METRICS = 6;
  const toggleMetric = (title: string) => {
    setSelectedMetrics((prev) =>
      prev.includes(title)
        ? prev.filter((m) => m !== title)
        : prev.length < MAX_METRICS
          ? [...prev, title]
          : prev
    );
  };

  if (isLoading && !dummyCamp) {
    return (
      <Center className="h-full w-full py-20">
        <Loader size="lg" type="dots" />
      </Center>
    );
  }

  if (!camp) {
    return <CampaignNotFound/>
  }

  const chartsToDisplay = allChartsConfigs.filter((c) =>
    selectedMetrics.includes(c.title)
  );
  const trendData = camp.trend as Record<string, number | string | null>[];

  return (
    <div className="custom-scrollbar font-inter! relative flex h-full w-full flex-col overflow-auto">
      {/* ── Header ── */}
      <Flex direction={'column'} gap={20} mt={32} mx={{ base: 12, lg: 32 }}>
        {/* back to all campaign */}
        <Text
          fz={12.5}
          fw={600}
          w={106}
          onClick={() => router.push('/campaigns')}
          className="hover:text-secondary-text flex cursor-pointer items-center justify-start gap-1 text-[#FAF9F58C]"
        >
          <ArrowLeft size={12.5} /> All campaigns
        </Text>
        {/* Meta reviews every new ad before it delivers — say where it stands, and
            why when an ad was turned down. Renders nothing when there is nothing to say. */}
        <MetaFixItList fixes={review} />
        <Box
          px={{ base: 13, md: 22 }}
          py={{ base: 13, md: 23 }}
          className="rounded-[18px] bg-[#FAF9F503]"
          style={{
            boxShadow:
              '0px 10px 30px -20px #00000099, 0px 1px 0px 1px #FFFFFF0D inset, 0px -1px 0px 0px #00000066 inset,0px 1px 0px 0px #FFFFFF1F inset, 0px 8px 24px 0px #00000080',
            backdropFilter: 'blur(75.9000015258789px)',
          }}
        >
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className="flex w-full cursor-pointer items-center justify-between text-left"
          >
            <Flex gap={{ base: 8, md: 14 }} className="w-full">
              {/* icon */}
              <Box
                w={{ base: 48, md: 52 }}
                h={{ base: 50, md: 52 }}
                className="rounded-[14px] border border-[#FAF9F51A] bg-[#FAF9F514]"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}
              >
                <svg
                  width="9"
                  height="10"
                  viewBox="0 0 9 10"
                  fill="none"
                  className="fill-primary-text"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path
                    d="M8.33333 4.16667V5H7.91667V5.41667H7.5V5.83333H6.66667V6.25H5.83333V6.66667H5.41667V7.08333H4.58333V7.5H3.75V7.91667H3.33333V8.33333H2.5V8.75H1.66667V9.16667H0.416667V8.75H0V0.416667H0.416667V0H1.66667V0.416667H2.5V0.833333H3.33333V1.25H3.75V1.66667H4.58333V2.08333H5.41667V2.5H5.83333V2.91667H6.66667V3.33333H7.5V3.75H7.91667V4.16667H8.33333Z"
                    // fill="#FAF9F5"
                  />
                </svg>
              </Box>
              <Box className="flex flex-col items-start justify-center gap-1.75">
                <Flex
                  className="w-full flex-wrap"
                  gap={10}
                  justify={'start'}
                  align={'center'}
                >
                  <Text
                    fz={{ base: 15, md: 22 }}
                    fw={700}
                    className="text-primary-text leading-0"
                  >
                    {camp?.title || 'Tittle not found'}
                  </Text>
                  {open ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
                  <Flex
                    gap={6}
                    align={'center'}
                    justify={'center'}
                    className="hidden! rounded-full border border-[#FAF9F512] bg-[#30302E] sm:flex!"
                    px={10.67}
                    py={5}
                  >
                    <Box
                      h={6}
                      w={6}
                      className="animate-pulse rounded-full bg-[#FAF9F5]"
                    ></Box>
                    <Text className="text-[#FAF9F5]" fz={10.5} fw={600}>
                      {camp?.status === 'Active' ? 'Running' : 'Completed'}
                    </Text>
                  </Flex>
                </Flex>
                <Flex mt={-4} align={'center'} justify={'start'}>
                  <Text
                    fz={12.5}
                    fw={400}
                    className="text-secondary-text/60 flex items-center justify-center gap-1"
                  >
                    {camp?.campaignType === 'AppPromotion'
                      ? 'App Promotion'
                      : camp?.campaignType === 'LeadGeneration'
                        ? 'Lead Generation'
                        : camp?.campaignType === 'SalesConversion'
                          ? 'Sales Conversion'
                          : camp?.campaignType || undefined}{' '}
                    <span className="text-[8px]">•</span> {camp?.adType}{' '}
                    <span className="text-[8px]">•</span>{' '}
                    {camp?.dateRange || undefined}
                  </Text>
                </Flex>
              </Box>
            </Flex>
          </button>
          <AnimatePresence initial={false}>
            {open && (
              <motion.div
                initial={{ height: 0, opacity: 0, marginTop: 0 }}
                animate={{ height: 'auto', marginTop: 16, opacity: 1 }}
                exit={{ height: 0, opacity: 0, marginTop: 0 }}
                transition={{ duration: 0.2, ease: 'easeInOut' }}
                className={`overflow-hidden border-t ${open ? 'border-underline/30' : 'border-transparent'}`}
              >
                {(() => {
                  const visibleFields = [
                    'campaignType',
                    'adType',
                    'spend',
                    'impressions',
                    'reach',
                    'frequency',
                  ].filter((key) => {
                    if (key === 'campaignType') return !!camp?.campaignType;
                    if (key === 'adType') return !!camp?.adType;
                    return !!(camp.rawSample?.[
                      key as keyof typeof camp.rawSample
                    ] as string);
                  });
                  const lastField = visibleFields[visibleFields.length - 1];
                  const getBorderClass = (field: string) => {
                    const idx = visibleFields.indexOf(field);
                    const isLastTwo = idx >= visibleFields.length - 2;
                    const isLastThree = idx >= visibleFields.length - 3;
                    const isLast = field === lastField;

                    // mobile (grid-2): show border-b for all except the last two
                    const mobileBorder = isLastTwo ? '' : 'border-b pb-3';

                    // md (grid-3): items in last-3 but NOT last-2 had a mobile border — clear it at md
                    const mdClear =
                      !isLastTwo && isLastThree ? 'md:border-b-0 md:pb-0' : '';

                    // lg (flex row): clear border-b for everyone, add border-r for all except the very last
                    const lgBorder = `lg:border-b-0 lg:pb-0${isLast ? '' : ' lg:border-r'}`;

                    const parts = [
                      mobileBorder,
                      mdClear,
                      lgBorder,
                      'border-[#FAF9F514]',
                    ].filter(Boolean);
                    return parts.join(' ');
                  };

                  return (
                    <Box
                      mt={19}
                      className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:flex"
                    >
                      {camp?.campaignType && (
                        <Box
                          pr={{ base: 0, lg: 21.54 }}
                          className={`flex flex-col items-center justify-center lg:items-start lg:justify-center ${getBorderClass('campaignType')}`}
                        >
                          <Text
                            className="text-secondary-text/60 tracking-wider uppercase"
                            fw={600}
                            fz={9.5}
                          >
                            Objective
                          </Text>
                          <Text fz={16} fw={700} className="text-primary-text">
                            {camp?.campaignType === 'AppPromotion'
                              ? 'App Promotion'
                              : camp?.campaignType === 'LeadGeneration'
                                ? 'Lead Generation'
                                : camp?.campaignType === 'SalesConversion'
                                  ? 'Sales Conversion'
                                  : camp?.campaignType}
                          </Text>
                        </Box>
                      )}
                      {camp?.adType && (
                        <Box
                          px={{ base: 0, lg: 22 }}
                          className={`flex flex-col items-center justify-center lg:items-start lg:justify-center ${getBorderClass('adType')}`}
                        >
                          <Text
                            className="text-secondary-text/60 tracking-wider uppercase"
                            fw={600}
                            fz={9.5}
                          >
                            Creative
                          </Text>
                          <Text
                            fz={16}
                            fw={700}
                            className="text-primary-text capitalize"
                          >
                            {camp?.adType}
                          </Text>
                        </Box>
                      )}
                      {(camp.rawSample?.spend as string) && (
                        <Box
                          px={{ base: 0, lg: 22 }}
                          className={`flex flex-col items-center justify-center lg:items-start lg:justify-center ${getBorderClass('spend')}`}
                        >
                          <Text
                            className="text-secondary-text/60 tracking-wider uppercase"
                            fw={600}
                            fz={9.5}
                          >
                            Spend <span className="text-[8px]">•</span> Budget
                          </Text>
                          <Text
                            fz={16}
                            fw={700}
                            className="text-primary-text capitalize"
                          >
                            $
                            {Math.floor(
                              parseFloat(camp.rawSample?.spend as string)
                            ).toLocaleString('en-US')}{' '}
                            / $
                            {Math.floor(
                              parseFloat(camp.rawSample?.budget as string)
                            ).toLocaleString('en-US')}
                          </Text>
                        </Box>
                      )}
                      {(camp.rawSample?.impressions as string) && (
                        <Box
                          px={{ base: 0, lg: 22 }}
                          className={`flex flex-col items-center justify-center lg:items-start lg:justify-center ${getBorderClass('impressions')}`}
                        >
                          <Text
                            className="text-secondary-text/60 tracking-wider uppercase"
                            fw={600}
                            fz={9.5}
                          >
                            Impressions
                          </Text>
                          <Text
                            fz={16}
                            fw={700}
                            className="text-primary-text capitalize"
                          >
                            {camp.rawSample?.impressions as string}
                          </Text>
                        </Box>
                      )}
                      {(camp.rawSample?.reach as string) && (
                        <Box
                          px={{ base: 0, lg: 22 }}
                          className={`flex flex-col items-center justify-center lg:items-start lg:justify-center ${getBorderClass('reach')}`}
                        >
                          <Text
                            className="text-secondary-text/60 tracking-wider uppercase"
                            fw={600}
                            fz={9.5}
                          >
                            Reach
                          </Text>
                          <Text
                            fz={16}
                            fw={700}
                            className="text-primary-text capitalize"
                          >
                            {camp.rawSample?.reach as string}
                          </Text>
                        </Box>
                      )}
                      {(camp.rawSample?.frequency as string) && (
                        <Box
                          px={{ base: 0, lg: 22 }}
                          className={`flex flex-col items-center justify-center lg:items-start lg:justify-center ${getBorderClass('frequency')}`}
                        >
                          <Text
                            className="text-secondary-text/60 tracking-wider uppercase"
                            fw={600}
                            fz={9.5}
                          >
                            Frequency
                          </Text>
                          <Text
                            fz={16}
                            fw={700}
                            className="text-primary-text capitalize"
                          >
                            {camp.rawSample?.frequency as string}
                          </Text>
                        </Box>
                      )}
                    </Box>
                  );
                })()}
              </motion.div>
            )}
          </AnimatePresence>
        </Box>
      </Flex>

      <Flex
        justify="space-between"
        align="center"
        px={{ base: 16, lg: 32 }}
        mt={29}
        pb={13}
        className="flex-col gap-3 sm:flex-row sm:gap-0"
      >
        {/* performance */}
        <Flex
          align="center"
          justify={'space-between'}
          gap={10}
          className="w-full sm:w-auto! sm:justify-start!"
        >
          <Text fw={700} fz={17} className="text-primary-text">
            Performance
          </Text>
          <Text fz={12.5} fw={400} mt={3.5} className="text-secondary-text/50">
            {selectedMetrics.length} of {metricsOptions.length} charts shown
          </Text>
        </Flex>

        {/* selection */}
        <Flex justify={'space-between'} gap={8} className="w-full sm:w-auto!">
          {/* Last 28 days pill */}
          <Flex
            align="center"
            gap={7}
            px={14}
            py={8}
            className="cursor-pointer rounded-full"
            style={{
              background: '#00000014',
              border: '1px solid rgba(255, 255, 255, 0.1)',
              boxShadow:
                '0px 2px 12px 0px #00000040, 0px 1px 0px 0px #FFFFFF40 inset',
              backdropFilter: 'blur(45.1px)',
            }}
          >
            <Calendar size={13} className="text-primary-text/70" />
            <Text fz={12.5} fw={600} className="text-primary-text">
              Last 28 days
            </Text>
          </Flex>

          {/* Metrics pill */}
          <Popover
            opened={metricsOpen}
            onChange={setMetricsOpen}
            position="bottom-end"
            offset={8}
            withinPortal
            styles={{
              dropdown: {
                background: '#212121C9',
                backdropFilter: 'blur(75.9px)',
                boxShadow:
                  '0px 8px 24px 0px #00000080, 0px -1px 0px 0px #00000066 inset, 0px 1px 0px 0px #FFFFFF1F inset',
                border: 'none',
                borderRadius: '18px',
                padding: 0,
              },
            }}
          >
            <Popover.Target>
              <Flex
                align="center"
                gap={7.65}
                px={14}
                py={8}
                className="cursor-pointer rounded-full"
                onClick={() => setMetricsOpen(!metricsOpen)}
                style={{
                  background: '#FFFFFF1A',
                  border: '1px solid rgba(255, 255, 255, 0.14)',
                  boxShadow:
                    '0px 1.5px 0px 0px #FFFFFF59 inset, 0px 2px 6px 0px #00000033, 0px 8px 32px 0px #00000059',
                  backdropFilter: 'blur(47.1px)',
                }}
              >
                <ListFilter size={12.5} className="text-primary-text/70" />
                <Text fz={13} fw={600} className="text-primary-text">
                  Metrics{' '}
                  <span className="text-primary-text/50 text-[11px] font-semibold">
                    {selectedMetrics.length}/{metricsOptions.length}
                  </span>
                </Text>
              </Flex>
            </Popover.Target>

            <Popover.Dropdown>
              <Box w={340}>
                {/* header */}
                <Box
                  px={16}
                  py={13.37}
                  className="border-underline/30 border-b"
                >
                  <Text
                    fw={600}
                    fz={17}
                    className="text-primary-text tracking-wider"
                  >
                    Choose metrics
                  </Text>
                  <Text
                    fz={11}
                    fw={400}
                    mt={4}
                    className="text-secondary-text/60"
                    style={{
                      opacity: selectedMetrics.length >= MAX_METRICS ? 1 : 0,
                      transition: 'opacity 0.2s',
                    }}
                  >
                    Maximum {MAX_METRICS} reached — deselect one to add another.
                  </Text>
                </Box>

                {/* list */}
                <Box p={14} className="flex flex-col gap-2">
                  {metricsOptions.map((title) => {
                    const isSelected = selectedMetrics.includes(title);
                    const isDisabled =
                      !isSelected && selectedMetrics.length >= MAX_METRICS;
                    return (
                      <Box
                        key={title}
                        onClick={() => !isDisabled && toggleMetric(title)}
                        className="flex cursor-pointer items-center gap-3 rounded-[10px] transition-all duration-150"
                        style={{
                          opacity: isDisabled ? 0.4 : 1,
                          cursor: isDisabled ? 'not-allowed' : 'pointer',
                        }}
                      >
                        <Checkbox
                          checked={isSelected}
                          onChange={() => {}}
                          size="xs"
                          styles={{
                            root: { pointerEvents: 'none' },
                            input: {
                              borderRadius: '4px',
                              pointerEvents: 'none',
                              ...(isSelected
                                ? {
                                    background: '#FAF9F51A',
                                    backdropFilter: 'blur(47.1px)',
                                    boxShadow:
                                      '0px 2px 6px 0px #00000033, 0px 8px 32px 0px #00000059, 0px 1.5px 0px 0px #FFFFFF59 inset',
                                  }
                                : {}),
                            },
                          }}
                        />
                        <Text
                          fz={13}
                          fw={500}
                          className="text-primary-text select-none"
                        >
                          {title}
                        </Text>
                      </Box>
                    );
                  })}
                </Box>
              </Box>
            </Popover.Dropdown>
          </Popover>
        </Flex>
      </Flex>

      {/* ── Charts Grid with Framer Motion ── */}
      <section className="w-full px-4 pb-12 lg:px-8">
        {selectedMetrics.length === 0 ? (
          <Box
            className="mx-auto flex w-full max-w-[1800px] flex-col items-center justify-center rounded-2xl py-20 px-4 text-center"
            style={{
              background: '#FAF9F505',
              boxShadow:
                '0px -1px 0px 0px #00000066 inset, 0px 1px 0px 0px #FFFFFF1F inset, 0px 8px 24px 0px #00000080',
              backdropFilter: 'blur(60.6px)',
              border: '1px dashed rgba(255, 255, 255, 0.1)',
            }}
          >
            <Box
              className="mb-4 flex h-14 w-14 items-center justify-center rounded-full"
              style={{
                background: 'rgba(255, 255, 255, 0.04)',
                border: '1px solid rgba(255, 255, 255, 0.08)',
              }}
            >
              <BarChart3 size={24} className="text-secondary-text/60" />
            </Box>
            <Text fw={600} fz={17} className="text-primary-text mb-1.5">
              Please select a metric first
            </Text>
            <Text fz={13} className="text-secondary-text/60 max-w-md mb-6 leading-relaxed">
              No metrics are currently selected. Choose up to 6 metrics from the Metrics selector above to display performance charts.
            </Text>
          </Box>
        ) : (
          <motion.div
            layout
            className="mx-auto grid w-full max-w-[1800px] grid-cols-1 gap-5 lg:grid-cols-2 xl:grid-cols-3"
          >
            <AnimatePresence mode="popLayout">
              {chartsToDisplay.map((cfg) => {
                let chartComponent = null;

                if ('dataKey' in cfg) {
                  // Trend chart
                  chartComponent = (
                    <SingleAreaChart
                      data={trendData}
                      dataKey={cfg.dataKey}
                      height={180}
                    />
                  );
                } else {
                  // Comparison chart
                  const rawData = resolveSource(camp, cfg.source);
                  if (cfg.type === 'multiLine' && cfg.dataKeys) {
                    chartComponent = (
                      <MultiLineChart
                        data={rawData as TrendPoint[]}
                        dataKeys={cfg.dataKeys}
                        height={180}
                      />
                    );
                  } else if (cfg.type === 'verticalBar') {
                    chartComponent = (
                      <VerticalBarChart
                        data={rawData as BarPoint[]}
                        height={180}
                      />
                    );
                  } else if (cfg.type === 'horizontalBar') {
                    chartComponent = (
                      <Box className="mx-auto! h-50 w-full max-w-120!">
                        <HorizontalBarChart data={rawData as BarPoint[]} />
                      </Box>
                    );
                  } else if (cfg.type === 'groupedBar') {
                    const gData = rawData as GroupedBarPoint[];
                    chartComponent = (
                      <GroupedBarChart
                        data={gData}
                        groupKeys={groupKeysFrom(gData)}
                        height={180}
                      />
                    );
                  }
                }

                if (!chartComponent) {
                  chartComponent = (
                    <Flex align="center" justify="center" h={180}>
                      <Text fz={13} className="text-secondary-text/50">
                        No data found
                      </Text>
                    </Flex>
                  );
                }

                return (
                  <motion.div
                    layout
                    initial={{ opacity: 0, scale: 0.8, y: 20 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.8, y: -20 }}
                    transition={{ duration: 0.3, type: 'spring', bounce: 0.2 }}
                    key={cfg.title}
                    className="backdrop-blur-3xl"
                  >
                    <ChartCard title={cfg.title}>{chartComponent}</ChartCard>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </motion.div>
        )}
      </section>
    </div>
  );
};

export default CampaignDetail;
