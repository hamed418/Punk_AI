import AdCampaignsPage from "./-components/page";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/(dashboard)/campaigns/")({
  component: AdCampaignsPage,
});
