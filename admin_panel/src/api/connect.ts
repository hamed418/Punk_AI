import api from './client';

export interface MetaConnetionResponse {
    authorization_url: string;
}

export const connect = {
    metaAdsRegister: () =>
        api.post<MetaConnetionResponse>('/ads/connect/meta'),
};
export const disconnect = {
    metaAdsDisconnect: () =>
        api.delete<MetaConnetionResponse>('/ads/disconnect/meta'),
};
