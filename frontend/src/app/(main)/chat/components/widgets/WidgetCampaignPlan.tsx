'use client'

import { Table, Text } from '@mantine/core'
import type { CampaignPlanContent, PlanSection } from '@/types/chat'
import WidgetLayout from './WidgetLayout'

interface WidgetCampaignPlanProps {
  content: CampaignPlanContent
  showLogo?: boolean
  isLatest?: boolean
}

function Section({ section }: { section: PlanSection }) {
  switch (section.type) {
    case 'metrics':
      return (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {section.items.map((it, i) => (
            <div
              key={i}
              className="border-stroke-widget bg-primary-widget/40 flex flex-col gap-1 rounded-xl border p-3"
            >
              <Text className="text-secondary-text/60 text-[11px] uppercase tracking-wide">
                {it.label}
              </Text>
              <Text className="text-primary-text text-[15px] font-semibold">{it.value}</Text>
            </div>
          ))}
        </div>
      )
    case 'kv':
      return (
        <div className="flex flex-col gap-2">
          {section.label && (
            <Text className="text-primary-text text-[12px] font-semibold uppercase tracking-wide">
              {section.label}
            </Text>
          )}
          {section.rows.map((r, i) => (
            <div key={i} className="flex flex-col gap-0.5">
              <Text className="text-secondary-text/60 text-[11px] uppercase tracking-wide">
                {r.label}
              </Text>
              <Text className="text-primary-text text-[13.5px]">{r.value}</Text>
            </div>
          ))}
        </div>
      )
    case 'text':
      return (
        <div className="flex flex-col gap-1">
          {section.label && (
            <Text className="text-primary-text text-[12px] font-semibold uppercase tracking-wide">
              {section.label}
            </Text>
          )}
          <Text className="text-secondary-text text-[13.5px] whitespace-pre-wrap">
            {section.text}
          </Text>
        </div>
      )
    case 'list':
      return (
        <div className="flex flex-col gap-1">
          {section.label && (
            <Text className="text-primary-text text-[12px] font-semibold uppercase tracking-wide">
              {section.label}
            </Text>
          )}
          <ul className="text-secondary-text list-disc pl-5 text-[13.5px]">
            {section.items.map((it, i) => (
              <li key={i}>{it}</li>
            ))}
          </ul>
        </div>
      )
    case 'table':
      return (
        <div className="flex flex-col gap-2">
          {section.label && (
            <Text className="text-primary-text text-[12px] font-semibold uppercase tracking-wide">
              {section.label}
            </Text>
          )}
          <div className="overflow-x-auto">
            <Table striped highlightOnHover className="text-[13px]">
              <Table.Thead>
                <Table.Tr>
                  {section.columns.map((c, i) => (
                    <Table.Th key={i}>{c}</Table.Th>
                  ))}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {section.rows.map((row, ri) => (
                  <Table.Tr key={ri}>
                    {row.map((cell, ci) => (
                      <Table.Td key={ci}>{cell}</Table.Td>
                    ))}
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </div>
        </div>
      )
    default:
      return null
  }
}

export default function WidgetCampaignPlan({
  content,
  showLogo = false,
}: WidgetCampaignPlanProps) {
  if (!content || typeof content !== 'object' || !('sections' in content)) return null

  return (
    <WidgetLayout mode="full" showLogo={showLogo}>
      <div className="border-stroke-widget bg-primary-widget shadow-widget mb-4 flex flex-col gap-5 rounded-3xl border p-6">
        <div className="flex flex-col gap-1">
          <Text className="text-primary-text text-[17px] font-semibold">{content.title}</Text>
          {content.subtitle && (
            <Text className="text-secondary-text/70 text-[13px]">{content.subtitle}</Text>
          )}
        </div>
        {content.sections.map((s, i) => (
          <Section key={s.key ?? i} section={s} />
        ))}
      </div>
    </WidgetLayout>
  )
}
