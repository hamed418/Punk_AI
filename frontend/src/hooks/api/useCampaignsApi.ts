import { useQuery } from "@tanstack/react-query";
import { getCampaignsAction, getCampaignAction, getCampaignReviewAction } from "../../actions/campaigns.actions";

export const useCampaigns = () => {
  return useQuery({
    queryKey: ["campaigns"],
    queryFn: async () => {
      const result = await getCampaignsAction();
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
  });
};

export const useCampaign = (id: string) => {
  return useQuery({
    queryKey: ["campaigns", id],
    queryFn: async () => {
      const result = await getCampaignAction(id);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
    enabled: !!id,
    retry: false,
  });
};

// Meta's ad review for one campaign. An optional garnish on the page: a failed read
// is an empty list rather than an error state, and review resolves over hours, so a
// minute of staleness costs nothing.
export const useCampaignReview = (id: string) => {
  return useQuery({
    queryKey: ["campaigns", id, "review"],
    queryFn: async () => {
      const result = await getCampaignReviewAction(id);
      return result.success && result.data ? result.data : [];
    },
    enabled: !!id,
    retry: false,
    staleTime: 60_000,
  });
};
