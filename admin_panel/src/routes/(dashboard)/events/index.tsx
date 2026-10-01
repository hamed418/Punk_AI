import { createFileRoute } from '@tanstack/react-router';
import PostHogEventsPage from './-components/page';

export const Route = createFileRoute('/(dashboard)/events/')({
  component: PostHogEventsPage,
});
