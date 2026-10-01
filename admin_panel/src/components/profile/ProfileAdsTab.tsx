import React, { useEffect } from 'react';
import { ShieldCheck } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { useAds } from '../../contexts/AdsContext';
import PlatformCard from './PlatformCard';
import { useAuth } from '../../contexts/AuthContext';

const ProfileAdsTab: React.FC = () => {
    const { platforms, loading, connectPlatform, disconnectPlatform } = useAds();
    const { user } = useAuth();
    console.log(user, "---")
    const [searchParams, setSearchParams] = useSearchParams();

    useEffect(() => {
        const connectedPlatform = searchParams.get('connected');
        const token = searchParams.get('token');

        if (connectedPlatform && token) {
            // Store token in cookie professionally (Secure, SameSite, Max-Age 60 days)
            document.cookie = `${connectedPlatform}_ads_token=${encodeURIComponent(token)}; path=/; max-age=5184000; SameSite=Strict; ${window.location.protocol === 'https:' ? 'Secure;' : ''}`;

            // Clean the URL without causing a full reload
            searchParams.delete('connected');
            searchParams.delete('token');
            setSearchParams(searchParams, { replace: true });
        }
    }, [searchParams, setSearchParams]);

    return (
        <div className="flex flex-col gap-12 animate-in fade-in slide-in-from-bottom-4 duration-700">
            <div>
                <h2 className="text-4xl font-bold text-foreground tracking-tight font-display mb-4">
                    Ad Platforms
                </h2>
                <p className="text-muted-foreground text-base max-w-2xl leading-relaxed font-body">
                    Connect your advertising accounts to enable AI-powered campaign management and performance optimization across networks.
                </p>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <PlatformCard
                    name="Google Ads"
                    description="Sync Search, Performance Max, and Shopping campaigns for AI strategy synthesis."
                    accentColor="#4285F4"
                    logoUrl="https://www.vectorlogo.zone/logos/google_ads/google_ads-icon.svg"
                    connected={!!platforms.find(p => p.platform.toLowerCase() === 'google')?.connected}
                    accountName={platforms.find(p => p.platform.toLowerCase() === 'google')?.account_name}
                    onConnect={() => connectPlatform('google')}
                    onDisconnect={() => disconnectPlatform('google')}
                    disabled={loading}
                />
                <PlatformCard
                    name="Meta Ads"
                    description="Connect Facebook & Instagram for automated creative deployment and audience scaling."
                    accentColor="#0668E1"
                    logoUrl="https://upload.wikimedia.org/wikipedia/commons/thumb/b/b8/2021_Facebook_icon.svg/2048px-2021_Facebook_icon.svg.png"
                    connected={(user && user.oauth_tokens && user.oauth_tokens.length >= 1) ? true : false}
                    accountName={platforms.find(p => p.platform.toLowerCase() === 'meta')?.account_name}
                    onConnect={() => connectPlatform('meta')}
                    onDisconnect={() => disconnectPlatform('meta')}
                    disabled={loading}
                />
            </div>

            {/* Protection Banner */}
            <div className="group p-8 rounded-[32px] bg-white/40 backdrop-blur-md border border-border flex flex-col sm:flex-row items-center gap-8 relative overflow-hidden shadow-sm hover:shadow-md transition-shadow duration-500">
                <div className="absolute inset-0 bg-linear-to-r from-emerald-500/5 to-transparent pointer-events-none" />
                <div className="w-16 h-16 rounded-2xl shrink-0 bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center group-hover:scale-110 transition-transform duration-500">
                    <ShieldCheck size={28} className="text-emerald-500" />
                </div>
                <div className="relative z-10">
                    <div className="flex items-center gap-3 mb-2 justify-center sm:justify-start">
                        <span className="font-display text-xl font-bold text-foreground">Security & Privacy</span>
                        <div className="px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-[10px] font-bold text-emerald-500 uppercase tracking-widest font-body">
                            Enforced
                        </div>
                    </div>
                    <p className="text-[14px] text-muted-foreground font-body leading-relaxed max-w-3xl m-0 text-center sm:text-left">
                        Your advertising credentials and telemetry data are protected by bank-level encryption. We only access authorized endpoints to synthesize strategies, ensuring your proprietary data remains private and secure.
                    </p>
                </div>
            </div>
        </div>
    );
};

export default ProfileAdsTab;
