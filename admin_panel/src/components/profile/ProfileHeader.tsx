import React from 'react';
import { ArrowLeft, LayoutDashboard } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import type { User } from '../../contexts/AuthContext';

interface ProfileHeaderProps {
    user: User | null;
}

const ProfileHeader: React.FC<ProfileHeaderProps> = ({ user }) => {
    const navigate = useNavigate();
    const initials = user?.full_name?.split(' ').map(n => n[0]).join('').toUpperCase() || 'E';

    return (
        <nav className="fixed top-0 left-0 right-0 z-100 border-b border-border/60 backdrop-blur-xl bg-background/80 px-6 py-4">
            <div className="max-w-[1400px] mx-auto flex items-center justify-between">
                <div className="flex items-center gap-6">
                    <button
                        onClick={() => navigate('/chat')}
                        className="group flex items-center gap-2.5 px-4 py-2 bg-muted hover:bg-accent border border-border rounded-full text-[11px] font-bold tracking-wider uppercase text-muted-foreground hover:text-foreground transition-all shadow-sm"
                    >
                        <ArrowLeft size={14} />
                        <span className="hidden sm:inline">Back to Chat</span>
                    </button>
                    <div className="w-px h-6 bg-border hidden sm:block" />
                    <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center shrink-0 shadow-lg shadow-primary/20">
                            <LayoutDashboard size={16} className="text-primary-foreground" />
                        </div>
                        <span className="font-display text-[14px] font-bold text-foreground tracking-tight hidden xs:block">
                            Settings
                        </span>
                    </div>
                </div>

                <div className="flex items-center gap-4">
                    <div className="text-right pr-4 border-r border-border hidden xs:block">
                        <div className="text-[13px] font-bold text-foreground font-body">{user?.full_name}</div>
                        <div className="text-[10px] font-bold text-muted-foreground tracking-wider uppercase font-body">{user?.role || 'User'}</div>
                    </div>
                    <div className="w-10 h-10 rounded-full border-2 border-background shadow-sm shrink-0 overflow-hidden bg-muted flex items-center justify-center text-[12px] font-bold text-muted-foreground">
                        {user?.profile_image ? (
                            <img src={user.profile_image} alt={user.full_name} className="w-full h-full object-cover" />
                        ) : initials}
                    </div>
                </div>
            </div>
        </nav>
    );
};

export default ProfileHeader;
