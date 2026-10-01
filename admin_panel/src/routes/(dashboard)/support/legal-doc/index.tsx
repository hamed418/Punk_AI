import { Box } from '@mantine/core'
import { createFileRoute } from '@tanstack/react-router'
import LegalDocPage from './-components/page'

export const Route = createFileRoute('/(dashboard)/support/legal-doc/')({
  component: RouteComponent,
})

function RouteComponent() {
  return <Box>
    <LegalDocPage/>
  </Box>
}
