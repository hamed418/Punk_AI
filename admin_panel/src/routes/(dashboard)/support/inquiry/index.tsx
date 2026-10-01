import InquiryPage from "./-components/page";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/(dashboard)/support/inquiry/")({
  component: InquiryPage,
});
