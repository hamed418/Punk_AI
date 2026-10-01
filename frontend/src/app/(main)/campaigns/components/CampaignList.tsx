'use client'

import { useState, useEffect, useMemo } from 'react'
import { campaigns as dummyCampaigns, Campaign } from './dummyData'
import { Box, Flex, Text, Center, Loader } from '@mantine/core'
import { Inbox } from 'lucide-react'

import CategoryInfiniteScroll from './CategoryInfiniteScroll'
import PageHeader from './shared/PageHeader'
import { CampaignResponse } from '@/types/campaigns.dto'
import { useCampaigns } from '@/hooks/api/useCampaignsApi'
import { syncMetaCampaignsAction } from '@/actions/campaigns.actions'
import { useQueryClient } from '@tanstack/react-query'

const campaignTypes = [
  { value: 'Awareness', label: 'Awareness' },
  { value: 'Traffic', label: 'Traffic' },
  { value: 'Engagement', label: 'Engagement' },
  { value: 'LeadGeneration', label: 'Lead Generation' },
  { value: 'AppPromotion', label: 'App Promotion' },
  { value: 'SalesConversion', label: 'Sales' },
] as const

export const mapCampaignResponseToUI = (apiCamp: CampaignResponse): Campaign => {
  const plan = (apiCamp.campaign_plan as Partial<Campaign>) || {};

  let campaignType: Campaign['campaignType'] = 'Awareness';
  const nameLower = apiCamp.name.toLowerCase();
  if (nameLower.includes('traffic') || nameLower.includes('click')) campaignType = 'Traffic';
  else if (nameLower.includes('engage') || nameLower.includes('like')) campaignType = 'Engagement';
  else if (nameLower.includes('lead') || nameLower.includes('form')) campaignType = 'LeadGeneration';
  else if (nameLower.includes('app') || nameLower.includes('install')) campaignType = 'AppPromotion';
  else if (nameLower.includes('sale') || nameLower.includes('purchase') || nameLower.includes('conversion')) campaignType = 'SalesConversion';

  const dummyFallback = dummyCampaigns.find(c => c.campaignType === campaignType) || dummyCampaigns[0];

  return {
    id: apiCamp.id,
    campaignType: plan.campaignType || campaignType,
    adType: plan.adType || dummyFallback.adType || 'image',
    objective: plan.objective || dummyFallback.objective || 'UNKNOWN',
    campaignId: apiCamp.id,
    title: apiCamp.name,
    subtitle: plan.subtitle || `${apiCamp.platform} Ad`,
    dateRange: plan.dateRange || new Date(apiCamp.created_at).toLocaleDateString(),
    status: (() => {
      // Punk's own lifecycle status (draft/approved/published/archived) never
      // says whether the campaign is actually delivering — that's Meta's
      // effective_status, already stored in campaign_plan from the sync.
      const eff = String(apiCamp.campaign_plan?.effective_status ?? '');
      if (eff === 'ACTIVE') return 'Active';
      if (eff.includes('PAUSED')) return 'Paused';
      return 'Completed';
    })(),
    currency: (apiCamp.campaign_plan?.account_currency as string) || dummyFallback.currency || 'USD',
    isFromPunkAI: plan.isFromPunkAI !== undefined ? plan.isFromPunkAI : true,
    source: plan.source || 'PunkAI',
    heroStat: plan.heroStat || dummyFallback.heroStat || { label: 'Impressions', value: apiCamp.impressions.toString() },
    secondaryStat: plan.secondaryStat || dummyFallback.secondaryStat || { label: 'Clicks', value: apiCamp.clicks.toString() },
    cardStats: (plan.cardStats && plan.cardStats.length > 0) ? plan.cardStats : dummyFallback.cardStats,
    trend: (plan.trend && plan.trend.length > 0) ? plan.trend : dummyFallback.trend,
    breakdown: (plan.breakdown && Object.keys(plan.breakdown).length > 0) ? plan.breakdown : dummyFallback.breakdown,
    charts: plan.charts || dummyFallback.charts,
    rawSample: {
      spend: apiCamp.spend_usd || dummyFallback.rawSample?.spend || 0,
      budget: apiCamp.daily_budget_usd || apiCamp.monthly_budget_usd || dummyFallback.rawSample?.budget || 10000,
      ...dummyFallback.rawSample,
      ...plan.rawSample
    }
  };
};

const CampaignList = () => {
  const [activeTab, setActiveTab] = useState('All')
  const [campaignTypeFilter, setCampaignTypeFilter] = useState('All')
  const [mounted, setMounted] = useState(false)
  const queryClient = useQueryClient()

  const { data: apiData, isLoading } = useCampaigns()
  useEffect(() => {
    const timer = setTimeout(() => {
      setMounted(true)
    }, 0)
    
    // Sync campaigns from Meta in the background on first visit
    const syncCampaigns = async () => {
      try {
        await syncMetaCampaignsAction()
        queryClient.invalidateQueries({ queryKey: ["campaigns"] })
      } catch (error) {
        console.error("Failed to sync campaigns in background", error)
      }
    }
    syncCampaigns()
    
    return () => clearTimeout(timer)
  }, [queryClient])

  const campaigns = useMemo(() => {
    if (apiData?.results && apiData.results.length > 0) {
      const mapped = apiData.results.map(mapCampaignResponseToUI);
      return [...mapped, ...dummyCampaigns];
    }
    return dummyCampaigns;
  }, [apiData]);

  const filteredCampaigns = campaigns.filter((camp) => {
    if (activeTab === 'Running' && camp.status !== 'Active') return false
    if (activeTab === 'Ended' && camp.status !== 'Completed') return false
    if (
      campaignTypeFilter !== 'All' &&
      camp.campaignType !== campaignTypeFilter
    )
      return false
    return true
  })

  const getSectionSpend = (sectionCampaigns: typeof campaigns) => {
    let spend = 0
    sectionCampaigns.forEach((camp) => {
      const rawSpend = camp.rawSample?.spend
      const parsed =
        typeof rawSpend === 'string' ? parseFloat(rawSpend) : Number(rawSpend)
      if (!isNaN(parsed)) {
        spend += parsed
      }
    })
    return Math.round(spend).toLocaleString()
  }

  const sections = campaignTypes
    .map((type) => {
      const sectionCampaigns = filteredCampaigns.filter(
        (camp) => camp.campaignType === type.value,
      )
      return {
        ...type,
        campaigns: sectionCampaigns,
      }
    })
    .filter((sec) => sec.campaigns.length > 0)

  if (isLoading) {
    return (
      <Center className="h-full w-full py-20">
        <Loader size="lg" type="dots" />
      </Center>
    )
  }

  return (
    <div
      className={`relative flex h-full w-full flex-col font-body text-slate-900 transition-opacity duration-700 ${mounted ? 'opacity-100' : 'opacity-0'}`}
    >
      <Box className="custom-scrollbar mx-auto flex w-full flex-col overflow-auto font-sans">
        {/* Content Container */}
        <Box className="mt-12 w-full px-4 md:px-8 pb-12">
          {/* Header */}
          <Box>
            <PageHeader
              data={campaigns}
              activeTab={activeTab}
              setActiveTab={setActiveTab}
              campaignTypeFilter={campaignTypeFilter}
              setCampaignTypeFilter={setCampaignTypeFilter}
            />
          </Box>

          {/* Sections */}
          <Box className="mt-6 flex flex-col gap-10">
            {sections.length > 0 ? (
              sections.map((sec) => {
                const sectionSpend = getSectionSpend(sec.campaigns)
                return (
                  <CategoryInfiniteScroll
                    key={sec.value}
                    label={sec.label}
                    campaigns={sec.campaigns}
                    sectionSpend={sectionSpend}
                  />
                )
              })
            ) : (
              <Box
                className="flex flex-col items-center justify-center rounded-3xl py-20 px-4 text-center"
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
                  <Inbox size={26} className="text-secondary-text/60" />
                </Box>
                <Text fw={600} fz={17} className="text-primary-text mb-1">
                  No data found
                </Text>
                <Text fz={13} className="text-secondary-text/60 max-w-sm mb-5">
                  No campaigns match the selected filters. Try changing your campaign category or status filter.
                </Text>
                <button
                  type="button"
                  onClick={() => {
                    setActiveTab('All')
                    setCampaignTypeFilter('All')
                  }}
                  className="cursor-pointer rounded-full px-5 py-2 text-xs font-semibold text-primary-text transition-all duration-150 hover:bg-white/10 active:scale-95"
                  style={{
                    background: 'rgba(255, 255, 255, 0.08)',
                    border: '1px solid rgba(255, 255, 255, 0.15)',
                  }}
                >
                  Reset Filters
                </button>
              </Box>
            )}
          </Box>
        </Box>
      </Box>
    </div>
  )
}

export default CampaignList
