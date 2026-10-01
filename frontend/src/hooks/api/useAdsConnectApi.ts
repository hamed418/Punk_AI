import { useMutation, useQueryClient } from "@tanstack/react-query";
import { metaAdsRegisterAction, metaAdsDisconnectAction, metaAdsDisconnectConnectionAction, removeMetaAdsAccountAction } from "../../actions/connect.actions";

export const useMetaAdsRegister = () => {
  return useMutation({
    mutationFn: async () => {
      const result = await metaAdsRegisterAction();
      if (!result.success) throw new Error(result.error);
      return result.data;
    },
  });
};

export const useMetaAdsDisconnect = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const result = await metaAdsDisconnectAction();
      if (!result.success) throw new Error(result.error);
      return result.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user"] });
    },
  });
};

export const useMetaAdsDisconnectConnection = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (tokenId: string) => {
      const result = await metaAdsDisconnectConnectionAction(tokenId);
      if (!result.success) throw new Error(result.error);
      return result.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user"] });
    },
  });
};

export const useRemoveMetaAdsAccount = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (adAccountId: string) => {
      const result = await removeMetaAdsAccountAction(adAccountId);
      if (!result.success) throw new Error(result.error);
      return result.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user"] });
    },
  });
};
