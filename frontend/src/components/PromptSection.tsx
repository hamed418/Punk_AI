import { Box, Text } from '@mantine/core'
import type { PropsWithChildren } from 'react'

const PromptSection = ({ children }: PropsWithChildren) => {
  return (
    <Box className="w-full">
      <Box className="bg-secondary-widget rounded-md p-3">
        <Text fz={14} fw={600}>
          {children}
        </Text>
      </Box>
    </Box>
  )
}
export default PromptSection
