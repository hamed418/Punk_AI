import { createFileRoute } from '@tanstack/react-router'
import SubscriptionPage from './-components/page'

export const Route = createFileRoute('/(dashboard)/subscription/')({
  component: SubscriptionPage,
})

 
