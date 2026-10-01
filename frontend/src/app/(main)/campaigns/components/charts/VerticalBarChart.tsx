'use client'

import { BarChart } from '@mantine/charts'
import '@mantine/charts/styles.css'
import type { BarPoint } from '../dummyData'
import { Box, Flex, Text } from '@mantine/core'

const formatTick = (val: unknown) => {
  const n = Number(val)
  if (isNaN(n)) return String(val)
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(Number(n.toFixed(2)))
}

interface VerticalBarChartProps {
  data: BarPoint[]
  height?: number
  color?: string
}

export default function VerticalBarChart({
  data,
  height = 200,
  color = 'var(--color-primary-text)',
}: VerticalBarChartProps) {
  if (!data || data.length === 0) {
    return (
      <Flex align="center" justify="center" h={height} className="w-full">
        <Text fz={13} className="text-secondary-text/50">
          No data found
        </Text>
      </Flex>
    )
  }

  const formattedData = data.map((d) => ({
    name: d.label,
    value: d.value,
  }))

  return (
    <Box className='mx-auto pl-7 -ml-10'>
      <BarChart
        h={height}
        data={formattedData}
        dataKey="name"
        series={[{ name: 'value', color }]}
        tickLine="none"
        gridAxis="x"
        style={{
          '--chart-text-color': 'var(--color-secondary-text)',
          '--chart-grid-color': 'var(--color-divider)',
        } as React.CSSProperties}
        withTooltip
        yAxisProps={{ tickFormatter: formatTick, interval: 0 }}
        styles={{
          root: { fontFamily: 'inherit' },
          bar: { rx: 4, ry: 4 },
        }}
      />
    </Box>
  )
}
