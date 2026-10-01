import AnalyticsPage from "./-components/page";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/(dashboard)/analytics/")({
  component: AnalyticsPage,
});