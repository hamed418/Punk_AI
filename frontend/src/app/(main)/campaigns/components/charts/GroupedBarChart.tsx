'use client'

import { BarChart } from '@mantine/charts'
import '@mantine/charts/styles.css'
import type { GroupedBarPoint } from '../dummyData'
import { Box, Flex, Text } from '@mantine/core'

const SERIES_COLORS = ['var(--color-primary-text)', 'var(--color-divider)']

const formatTick = (val: unknown) => {
  const n = Number(val)
  if (isNaN(n)) return String(val)
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(Number(n.toFixed(2)))
}

const toLabel = (key: string) =>
  key
    .replace(/([A-Z])/g, ' $1')
    .replace(/^./, (s) => s.toUpperCase())
    .replace(/_/g, ' ')
    .trim()

interface GroupedBarChartProps {
  data: GroupedBarPoint[]
  /** Keys to group by (everything except "label") */
  groupKeys: string[]
  height?: number
}

export default function GroupedBarChart({
  data,
  groupKeys,
  height = 200,
}: GroupedBarChartProps) {
  if (!data || data.length === 0 || !groupKeys || groupKeys.length === 0) {
    return (
      <Flex align="center" justify="center" h={height} className="w-full">
        <Text fz={13} className="text-secondary-text/50">
          No data found
        </Text>
      </Flex>
    )
  }

  // Mantine BarChart expects plain Record<string, unknown>[]
  const formattedData = data.map((d) => {
    const obj: Record<string, unknown> = { label: d.label }
    for (const key of groupKeys) {
      obj[key] = d[key]
    }
    return obj
  })

  const series = groupKeys.map((key, i) => ({
    name: key,
    color: SERIES_COLORS[i % SERIES_COLORS.length],
    label: toLabel(key),
  }))

  return (
    <Box className="mx-auto -ml-10 px-4">
      <BarChart
        h={height}
        data={formattedData}
        dataKey="label"
        series={series}
        type="default"
        withLegend
        style={{
          '--chart-text-color': 'var(--color-secondary-text)',
          '--chart-grid-color': 'var(--color-divider)',
        } as React.CSSProperties}
        legendProps={{ verticalAlign: 'top', height: 36 }}
        tickLine="none"
        gridAxis="y"
        withTooltip
        yAxisProps={{ tickFormatter: formatTick }}
        styles={{
          root: { fontFamily: 'inherit' },
          bar: { rx: 3, ry: 3 },
        }}
        classNames={{
          root: '[&_.recharts-cartesian-grid-vertical_line:last-child]:hidden',
        }}
      />
    </Box>
  )
}
