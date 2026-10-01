import { ChevronRight, Globe, ShieldCheck, User, Zap } from 'lucide-react';

interface ProfileSidebarProps {
  activeTab: 'profile' | 'ads';
  setActiveTab: (tab: 'profile' | 'ads') => void;
}

const ProfileSidebar: React.FC<ProfileSidebarProps> = ({
  activeTab,
  setActiveTab,
}) => {
  return (
    <div className="flex flex-col gap-1 px-2">
      {(['profile', 'ads'] as const).map((tab) => (
        <button
          key={tab}
          onClick={() => setActiveTab(tab)}
          className={`group relative flex items-center gap-3 w-full px-4 py-3.5 rounded-2xl text-[13px] font-bold tracking-tight transition-all
                        ${
                          activeTab === tab
                            ? 'bg-primary text-primary-foreground shadow-lg shadow-primary/20'
                            : 'text-muted-foreground hover:bg-muted hover:text-foreground border border-transparent hover:border-border'
                        }`}
        >
          {tab === 'profile' ? <User size={18} /> : <Globe size={18} />}
          {tab === 'profile' ? 'Personal Details' : 'Ad Platforms'}
          {activeTab === tab && (
            <ChevronRight size={14} className="ml-auto opacity-60" />
          )}
        </button>
      ))}

      {/* Status Cards */}
      <div className="mt-8 pt-8 border-t border-border/50 flex flex-col gap-4 px-2">
        <p className="text-[11px] font-bold text-muted-foreground tracking-wider uppercase font-body px-2 mb-1">
          Account Status
        </p>

        {/* Tier badge */}
        <div className="rounded-2xl border border-border/50 flex items-center bg-card shadow-sm p-4 gap-3 transition-all hover:border-primary/30">
          <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 bg-primary/10 border border-primary/20">
            <Zap size={16} className="text-primary" />
          </div>
          <div>
            <div className="text-[13px] font-bold text-foreground font-body leading-tight">
              Pro Plan
            </div>
            <div className="text-[10px] text-muted-foreground font-bold tracking-wide uppercase font-body mt-0.5">
              Active
            </div>
          </div>
        </div>

        {/* Security */}
        <div className="rounded-2xl bg-card border border-border/50 flex items-center shadow-sm p-4 gap-3 transition-all hover:border-emerald-500/30">
          <div className="w-9 h-9 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center shrink-0">
            <ShieldCheck size={18} className="text-emerald-500" />
          </div>
          <div>
            <div className="text-[13px] font-bold text-foreground font-body leading-tight">
              Verified
            </div>
            <div className="text-[10px] text-muted-foreground font-bold tracking-wide uppercase font-body mt-0.5">
              Secure
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ProfileSidebar;
