import { Box } from '@mantine/core'
import { createFileRoute } from '@tanstack/react-router'
import RedeemPage from './-components/page'

export const Route = createFileRoute('/(dashboard)/support/Redeem/')({
  component: RouteComponent,
})

function RouteComponent() {
  return (
    <Box>
      <RedeemPage />
    </Box>
  )
}
