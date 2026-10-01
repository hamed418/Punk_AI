'use client';

import { useRef, useState, useEffect } from 'react';

import { AreaChart } from '@mantine/charts';
import '@mantine/charts/styles.css';
import { Box, Flex, Text, Tooltip, useMantineColorScheme } from '@mantine/core';
import { useRouter } from 'next/navigation';
import { ArrowRight } from 'lucide-react';
import type { Campaign } from '../dummyData';

interface AppCardProps {
  campaign: Campaign;
}

const formatValue = (raw: string): string => {
  const cleaned = raw.replace(/,/g, '');
  const num = parseFloat(cleaned);
  if (isNaN(num)) return raw;
  if (Math.abs(num) >= 1_000_000) {
    const val = num / 1_000_000;
    return (
      (val % 1 === 0 ? val.toFixed(0) : val.toFixed(1).replace(/\.0$/, '')) +
      'M'
    );
  }
  if (Math.abs(num) >= 1_000) {
    const val = num / 1_000;
    return (
      (val % 1 === 0 ? val.toFixed(0) : val.toFixed(1).replace(/\.0$/, '')) +
      'K'
    );
  }
  return parseFloat(num.toFixed(2)).toString();
};

const formatFullPrice = (raw: string | number | undefined | null): string => {
  if (raw === undefined || raw === null) return '0';
  const cleaned = String(raw).replace(/,/g, '');
  const num = parseFloat(cleaned);
  if (isNaN(num)) return String(raw);
  return num.toLocaleString('en-US', {
    minimumFractionDigits: num % 1 !== 0 ? 2 : 0,
    maximumFractionDigits: 2,
  });
};

const formatStatValue = (val: string, label: string) => {
  const formatted = formatValue(val);

  const isCurrency = [
    'CPM',
    'CPC',
    'Cost/View',
    'Spend',
    'Revenue',
    'Cost/Engagement',
    'CPL',
    'CPI',
    'Cost/Purchase',
    'Cost / Install',
    'Cost/Install',
  ].includes(label);

  if (isCurrency && !formatted.startsWith('$')) {
    return `$${formatted}`;
  }

  const isMultiplier = ['Frequency', 'In-App ROAS', 'App ROAS'].includes(label);

  if (isMultiplier && !formatted.toLowerCase().endsWith('x')) {
    return `${formatted}x`;
  }

  return formatted;
};

const AppCard = ({ campaign }: AppCardProps) => {
  const router = useRouter();
  const { colorScheme } = useMantineColorScheme();
  const isLight = colorScheme === 'light';
  const isActive = campaign.status === 'Active';

  const titleRef = useRef<HTMLParagraphElement>(null);
  const [isTruncated, setIsTruncated] = useState(false);
  useEffect(() => {
    const el = titleRef.current;
    if (!el) return;
    const check = () => setIsTruncated(el.scrollWidth > el.clientWidth || el.scrollHeight > el.clientHeight);
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [campaign.title]);

  const isVideo =
    campaign.subtitle.toLowerCase().includes('video') ||
    campaign.subtitle.toLowerCase().includes('reels') ||
    !!campaign.breakdown.videoRetention;

  const stat1 = campaign.heroStat;
  const stat2 =
    campaign.cardStats.find((s) =>
      ['Frequency', 'CTR', 'In-App ROAS'].includes(s.label)
    ) ?? campaign.cardStats[0];
  const stat3 =
    campaign.cardStats.find((s) =>
      ['CPM', 'CPI', 'Cost/Install', 'Cost / Install'].includes(s.label)
    ) ?? campaign.secondaryStat;
  const spendStat = campaign.cardStats.find((s) => s.label === 'Spend');
  const spendNum = parseFloat(
    String(campaign.rawSample?.spend || spendStat?.value || '0').replace(/,/g, '')
  );
  const budgetNum = parseFloat(
    String(campaign.rawSample?.budget || '0').replace(/,/g, '')
  );

  const primaryDataKey =
    campaign.charts?.trend?.[0]?.dataKey ??
    (campaign.trend[0] && 'installs' in campaign.trend[0]
      ? 'installs'
      : 'clicks');

  const chartData = campaign.trend.map((pt) => ({
    date: new Date(String(pt.date)).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
    }),
    value: Number(pt[primaryDataKey] ?? pt.clicks ?? 0),
  }));

  const first = chartData[0]?.value ?? 0;
  const last = chartData[chartData.length - 1]?.value ?? first;

  const change = first !== 0 ? ((last - first) / first) * 100 : 0;

  const changeText =
    change >= 0 ? `+${change.toFixed(0)}%` : `${change.toFixed(0)}%`;

  return (
    <Box
      className="light:backdrop-blur-[57px] flex h-full flex-col rounded-[30px] backdrop-blur-xs"
      style={{
        height: '100%',
        background: isLight ? '#FFFFFF' : '#151517',
        boxShadow: isLight
          ? `0px 15px 26px 0px #1D1D1D14, 0px 2px 2px 0px #FFFFFFB2 inset, 1px -1px 2px 0px #FFFFFF80 inset ${isActive ? ', 0px 2px 1.5px 0px #1071383B inset' : ''}`
          : `
        0px -1px 0px 0px #00000066 inset,
        0px 1px 0px 0px #FFFFFF1F inset,
        0px 8px 24px 0px #00000080${isActive ? ', 0px 2px 2px 0px #1071384A inset' : ''}`,
        border: isLight ? '1px solid #FFFFFFE5' : undefined,
        // borderLeft: campaign.isFromPunkAI ? '1px solid #D62575' : undefined,
      }}
    >
      {/* ── Header ── */}
      <Flex align="flex-start" gap={12} p={16} className="items-start">
        <Box
          className={`relative flex shrink-0 items-center justify-center overflow-hidden rounded-2xl border ${isLight ? 'border-[#1515150A]' : 'border-white/10'}`}
          style={{
            width: 52,
            height: 52,
            background: isLight
              ? 'rgba(21, 21, 21, 0.08)'
              : 'rgba(255,255,255,0.08)',
          }}
        >
          {isVideo ? (
            <svg
              width="12"
              height="14"
              viewBox="0 0 12 14"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path d="M11 7L2 12V2L11 7Z" fill={isLight ? 'black' : 'white'} />
            </svg>
          ) : (
            <Text
              fz={10}
              fw={700}
              className="text-secondary-text/30 light:text-secondary-text/60 tracking-wider uppercase"
            >
              Image
            </Text>
          )}
        </Box>

        <Box className="min-w-0 flex-1">
          <Tooltip
            label={campaign.title}
            disabled={!isTruncated}
            position="bottom-start"
            withArrow={false}
            multiline
            w={220}
            transitionProps={{ transition: 'fade', duration: 200 }}
            zIndex={100000}
            styles={{
              tooltip: {
                background: isLight
                  ? 'rgba(21, 21, 21, 0.08)'
                  : 'rgba(255,255,255,0.08)',
                padding: '4px 8px',
                backdropFilter: 'blur(10px)',
                lineHeight: 1.4,
                fontSize: 11,
                fontWeight: 600,
                boxShadow: isLight
                  ? 'var(--shadow-widget)'
                  : '0px 8px 24px 0px #00000080',
                border: isLight
                  ? '1px solid #FFFFFFE6'
                  : '1px solid rgba(255,255,255,0.08)',
                borderRadius: 12,
                color: 'var(--color-primary-text)',
              },
            }}
          >
            <Text
              ref={titleRef}
              fz={13}
              fw={700}
              truncate="end"
              className="text-primary-text truncate! cursor-default leading-snug"
            >
              {campaign.title}
            </Text>
          </Tooltip>
          <Text
            fz={11}
            className="text-secondary-text/40 light:text-secondary-text/60 mt-2.25! truncate leading-none"
          >
            {campaign.campaignType} · {campaign.dateRange} ·{' '}
            {isVideo ? 'Video' : 'Image'}
          </Text>
        </Box>

        {/* Status indicator — green when Active */}
        <Box
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full border ${
            isActive
              ? 'border-[#00B415]/30 bg-[#00B415]/15'
              : isLight
                ? 'border-black/10 bg-[#1515150A]'
                : 'border-white/10 bg-white/3'
          }`}
        >
          <Box
            className={`h-2 w-2 rounded-full ${
              isActive
                ? 'bg-[#00B415]'
                : isLight
                  ? 'bg-black/40'
                  : 'bg-white/40'
            }`}
          />
        </Box>
      </Flex>

      <Box
        className={`border-t ${isLight ? 'border-[#1515150A]' : 'border-t-2 border-white/6'}`}
      />

      {/* ── 3-Stats Row ── */}
      <Box className="grid grid-cols-3 px-4.75 py-4">
        {[stat1, stat2, stat3].filter(Boolean).map((stat, i) => (
          <Box
            key={i}
            className={`${i !== 0 ? `border-l ${isLight ? 'border-[#1515150D]' : 'border-white/10'} pl-4!` : ''}`}
          >
            <Text
              fw={700}
              mb={4}
              className="text-primary-text w-full text-2xl! leading-none tracking-tight whitespace-nowrap md:text-xl! xl:text-2xl!"
            >
              {formatStatValue(stat!.value, stat!.label)}
            </Text>
            <Text
              fz={10}
              fw={600}
              className="text-secondary-text/30 light:text-secondary-text/60 mt-1.5 w-full leading-none tracking-wider whitespace-nowrap uppercase sm:mt-2"
            >
              {stat!.label}
            </Text>
          </Box>
        ))}
      </Box>

      <Box
        className={`border-t ${isLight ? 'border-[#1515150A]' : 'border-t-2 border-white/6'}`}
      />

      {/* ── Chart Box ── */}
      <Box className="flex-1 flex flex-col justify-center py-4">
        <Box
          className={`mx-4 overflow-hidden rounded-2xl border ${isLight ? 'border-[#1515150A]' : 'border-white/6'}`}
          style={{
            background: isLight
              ? 'rgba(21, 21, 21, 0.03)'
              : 'rgba(255,255,255,0.03)',
          }}
        >
          <Flex justify="space-between" align="center" px={14} pt={14} pb={2}>
            <Text
              fw={600}
              fz={10}
              className="text-secondary-text/30 light:text-secondary-text/60 tracking-wider uppercase"
            >
              <span className="text-primary-text">{stat1.label}</span> · Last 30D
            </Text>
            <Text fz={13} fw={600} className="text-secondary-text/70">
              {changeText}
            </Text>
          </Flex>
          {chartData.length > 0 ? (
            <Box style={{ height: 130 }}>
              <AreaChart
                h={130}
                data={chartData}
                dataKey="date"
                series={[{ name: 'value', color: isLight ? 'black' : 'white' }]}
                curveType="natural"
                strokeWidth={1.5}
                fillOpacity={isLight ? 0.15 : 0.07}
                withLegend={false}
                withDots={false}
                withXAxis={false}
                withYAxis={false}
                gridAxis="none"
                withTooltip={false}
                styles={{ root: { fontFamily: 'inherit' } }}
              />
            </Box>
          ) : (
            <Flex align="center" justify="center" h={130}>
              <Text fz={11} className="text-secondary-text/40">
                No data found
              </Text>
            </Flex>
          )}
        </Box>
      </Box>

      <Box
        className={`border-t ${isLight ? 'border-[#1515150A]' : 'border-t-2 border-white/6'}`}
      />

      {/* ── Footer ── */}
      <Flex
        justify="space-between"
        align="flex-end"
        mb={5}
        className="w-full items-end p-4"
      >
        <Box className="mr-4 flex-1">
          <Text
            fz={10}
            fw={600}
            className="text-secondary-text/30 light:text-secondary-text/60 tracking-wider uppercase"
          >
            {campaign.rawSample?.budget ? 'Spend · Budget' : 'Total Spent'}
          </Text>
          {campaign.rawSample?.budget ? (
            <>
              <Flex align="baseline" gap={4} mt={2}>
                <Text fz={15} fw={700} className="text-primary-text leading-none">
                  ${formatFullPrice(String(campaign.rawSample?.spend || spendStat?.value || '0'))}
                </Text>
                <Text
                  fz={13}
                  className="text-secondary-text/35 light:text-secondary-text/60 leading-none"
                >
                  / ${formatFullPrice(String(campaign.rawSample.budget))}
                </Text>
              </Flex>
              <Box
                className={`mt-1 h-1 w-32 overflow-hidden rounded-full ${isLight ? 'bg-[#1515150A]' : 'bg-white/7'}`}
              >
                <Box
                  className={
                    isLight ? 'h-full rounded-full' : 'h-full rounded-full bg-white'
                  }
                  style={
                    isLight
                      ? {
                          width: `${budgetNum > 0 ? Math.min((spendNum / budgetNum) * 100, 100) : 0}%`,
                          background:
                            'linear-gradient(90deg, rgba(21, 21, 21, 0.5) 0%, rgba(21, 21, 21, 0.85) 100%)',
                        }
                      : {
                          width: `${budgetNum > 0 ? Math.min((spendNum / budgetNum) * 100, 100) : 0}%`,
                        }
                  }
                />
              </Box>
            </>
          ) : (
            <Text
              fz={15}
              fw={700}
              className="text-primary-text mt-0.5! leading-tight"
            >
              ${formatFullPrice(spendStat?.value || '0')}
            </Text>
          )}
        </Box>

        {/* Wide pill arrow button */}
        <Box
          onClick={() => router.push(`/campaigns/${campaign.id}`)}
          className={
            isLight
              ? 'flex h-10 w-14 shrink-0 cursor-pointer items-center justify-center self-end rounded-full bg-white/16 transition-all duration-150 active:scale-95'
              : 'flex h-10 cursor-pointer items-center justify-center gap-2 self-end rounded-full bg-white/10 px-5 transition-all duration-150 hover:bg-white/10 active:scale-95'
          }
          style={
            isLight
              ? {
                  boxShadow:
                    '0px 2px 6px 0px #00000033, 0px 1.5px 0px 0px #FFFFFF59 inset',
                }
              : {
                  borderTop: '1px solid #FFFFFF29',
                  boxShadow: `0px 2px 6px 0px #00000033,
                              0px 8px 32px 0px #00000059,
                              0px 1.5px 0px 0px #FFFFFF59 inset`,
                }
          }
        >
          <ArrowRight size={16} color={isLight ? '#151515' : 'white'} />
        </Box>
      </Flex>
    </Box>
  );
};

export default AppCard;
