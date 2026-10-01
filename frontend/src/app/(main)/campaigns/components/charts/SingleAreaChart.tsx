'use client'

import { AreaChart } from '@mantine/charts'
import '@mantine/charts/styles.css'
import { Box, Flex, Text } from '@mantine/core'

const SERIES_COLORS = ['var(--color-primary-text)']

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

interface SingleAreaChartProps {
  /** Raw trend data — date field + metric key */
  data: Array<Record<string, number | string | null>>
  /** Which key to plot as the area */
  dataKey: string
  height?: number
}

export default function SingleAreaChart({
  data,
  dataKey,
  height = 200,
}: SingleAreaChartProps) {
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
    // null → undefined so recharts shows a gap rather than zero
    obj[dataKey] = d[dataKey] === null ? undefined : d[dataKey]
    return obj
  })

  const series = [
    {
      name: dataKey,
      color: SERIES_COLORS[0],
      label: dataKey
        .replace(/([A-Z])/g, ' $1')
        .replace(/^./, (s) => s.toUpperCase()),
    },
  ]

  return (
    <Box className='mx-auto pl-5 pr-4 -ml-10'>
      <AreaChart
        h={height}
        data={formattedData}
        dataKey="date"
        series={series}
        curveType="natural"
        strokeWidth={3}
        fillOpacity={0.2}
        withLegend={false}
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
