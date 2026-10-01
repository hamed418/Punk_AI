'use client'

import { LineChart } from '@mantine/charts'
import '@mantine/charts/styles.css'
import { Box, Flex, Text } from '@mantine/core'

const SERIES_COLORS = ['var(--color-primary-text)', 'var(--color-divider)']

const formatDate = (dateStr: string) =>
  new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
  })

const formatTick = (val: unknown) => {
  const n = Number(val)
  if (isNaN(n)) return String(val)
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(Number(n.toFixed(2)))
}

interface MultiLineChartProps {
  /** Raw trend data — date field + any metric keys */
  data: Array<Record<string, number | string | null>>
  /** Which keys to plot as lines */
  dataKeys: string[]
  height?: number
}

export default function MultiLineChart({
  data,
  dataKeys,
  height = 200,
}: MultiLineChartProps) {
  if (!data || data.length === 0) {
    return (
      <Flex align="center" justify="center" h={height} className="w-full">
        <Text fz={13} className="text-secondary-text/50">
          No data found
        </Text>
      </Flex>
    )
  }

  const formattedData = data.map((d) => {
    const obj: Record<string, unknown> = {
      date: formatDate(String(d.date)),
    }
    for (const key of dataKeys) {
      // null → undefined so recharts shows a gap rather than zero
      obj[key] = d[key] === null ? undefined : d[key]
    }
    return obj
  })

  const series = dataKeys.map((key, i) => ({
    name: key,
    color: SERIES_COLORS[i % SERIES_COLORS.length],
    label: key.replace(/([A-Z])/g, ' $1').replace(/^./, (s) => s.toUpperCase()),
  }))

  return (
    <Box className="mx-auto -ml-10 pr-5 pl-6">
      <LineChart
        h={height}
        data={formattedData}
        dataKey="date"
        series={series}
        curveType="natural"
        strokeWidth={3}
        withLegend={dataKeys.length > 1}
        legendProps={{ verticalAlign: 'top', height: 36 }}
        withDots={false}
        connectNulls={false}
        tickLine="none"
        gridAxis="y"
        style={{
          '--chart-text-color': 'var(--color-secondary-text)',
          '--chart-grid-color': 'var(--color-divider)',
        } as React.CSSProperties}
        yAxisProps={{ tickFormatter: formatTick }}
        xAxisProps={{
          interval: 0,
        }}
        styles={{
          root: { fontFamily: 'inherit' },
        }}
      />
    </Box>
  )
}
