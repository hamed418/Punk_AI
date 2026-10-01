'use client'

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Flex, Text } from '@mantine/core'
import type { BarPoint } from '../dummyData'

const formatTick = (val: unknown) => {
  const n = Number(val)
  if (isNaN(n)) return String(val)
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(Number(n.toFixed(2)))
}

const HIGHLIGHT_COLOR = 'var(--color-primary-text)'
const BASE_COLOR = 'var(--color-divider)'

interface HorizontalBarChartProps {
  data: BarPoint[]
  height?: number
}

export default function HorizontalBarChart({
  data,
  height,
}: HorizontalBarChartProps) {
  if (!data || data.length === 0) {
    return (
      <Flex align="center" justify="center" h={height || 180} className="w-full">
        <Text fz={13} className="text-secondary-text/50">
          No data found
        </Text>
      </Flex>
    )
  }

  const max = Math.max(...data.map((d) => d.value))

  const formattedData = data.map((d) => ({
    name: d.label,
    value: d.value,
  }))

  return (
    <ResponsiveContainer className="-ml-6" width="100%" height="100%">
      <BarChart
        layout="vertical"
        data={formattedData}
        margin={{ top: 0, right: 8, left: 0, bottom: 0 }}
      >
        <CartesianGrid
          strokeDasharray="3 3"
          horizontal={false}
          vertical
          stroke="var(--color-divider)"
        />
        <XAxis
          type="number"
          axisLine={false}
          tickLine={false}
          tick={{
            fontSize: 10,
            fill: 'var(--color-secondary-text)',
            fontFamily: 'inherit',
          }}
          tickFormatter={formatTick}
        />
        <YAxis
          dataKey="name"
          type="category"
          axisLine={false}
          tickLine={false}
          width={90}
          tick={{
            fontSize: 11,
            fill: 'var(--color-secondary-text)',
            fontWeight: 500,
            fontFamily: 'inherit',
          }}
        />
        <Tooltip
          cursor={{ fill: 'var(--color-secondary-widget)' }}
          formatter={(val) => [formatTick(val), 'Value']}
          contentStyle={{
            borderRadius: 8,
            border: '1px solid var(--color-divider)',
            backgroundColor: 'var(--color-campaign-bg)',
            color: 'var(--color-primary-text)',
            fontFamily: 'inherit',
            fontSize: 12,
          }}
          itemStyle={{
            color: 'var(--mantine-color-text-secondary)',
          }}
        />
        <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={14}>
          {formattedData.map((entry) => (
            <Cell
              key={entry.name}
              fill={entry.value === max ? HIGHLIGHT_COLOR : BASE_COLOR}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
