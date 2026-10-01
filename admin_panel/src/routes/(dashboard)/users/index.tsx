import UsersPage from "./-components/page";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/(dashboard)/users/")({
  component: UsersPage,
});
