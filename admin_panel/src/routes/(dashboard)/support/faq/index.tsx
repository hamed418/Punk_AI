import FaqPage from "./-components/page";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/(dashboard)/support/faq/")({
  component: FaqPage,
});
