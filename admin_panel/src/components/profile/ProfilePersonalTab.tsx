import React, { useState } from 'react';
import { User, Mail, Lock, CheckCircle2, XCircle, Loader2, Save } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';

const ProfilePersonalTab: React.FC = () => {
    const { user, updateProfile } = useAuth();
    const [fullName, setFullName] = useState(user?.full_name || '');
    const [email, setEmail] = useState(user?.email || '');
    const [password, setPassword] = useState('');
    const [isUpdating, setIsUpdating] = useState(false);
    const [message, setMessage] = useState({ type: '', text: '' });

    const handleUpdateProfile = async (e: React.FormEvent) => {
        e.preventDefault();
        setIsUpdating(true);
        setMessage({ type: '', text: '' });
        try {
            const data: any = { full_name: fullName, email };
            if (password) data.password = password;
            await updateProfile(data);
            setMessage({ type: 'success', text: 'Identity updated successfully.' });
            setPassword('');
        } catch (error: any) {
            setMessage({ type: 'error', text: error.data?.detail || error.message || 'Update failed. Check your data.' });
        } finally {
            setIsUpdating(false);
        }
    };

    return (
        <div className="flex flex-col gap-12 max-w-2xl animate-in fade-in slide-in-from-bottom-4 duration-700">
            <div>
                <h2 className="text-4xl font-bold text-foreground tracking-tight font-display mb-4">
                    Personal Details
                </h2>
                <p className="text-muted-foreground text-base leading-relaxed font-body">
                    Manage your account information and security credentials to keep your profile accurate and protected.
                </p>
            </div>

            <form
                onSubmit={handleUpdateProfile}
                className="bg-white/40 backdrop-blur-md border border-border rounded-[32px] p-10 shadow-sm relative overflow-hidden"
            >
                <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-8">
                    <div className="flex flex-col gap-2.5">
                        <label className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider font-body ml-1">
                            Full Name
                        </label>
                        <div className="relative group">
                            <div className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground group-focus-within:text-foreground transition-colors">
                                <User size={18} />
                            </div>
                            <input
                                type="text"
                                value={fullName}
                                onChange={e => setFullName(e.target.value)}
                                className="w-full h-14 pl-12 pr-6 bg-muted/50 border border-border rounded-2xl text-foreground font-medium font-body placeholder:text-muted-foreground/50 focus:bg-background focus:border-primary focus:ring-4 focus:ring-primary/5 transition-all outline-none"
                                placeholder="Beck"
                            />
                        </div>
                    </div>

                    <div className="flex flex-col gap-2.5">
                        <label className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider font-body ml-1">
                            Email Address
                        </label>
                        <div className="relative group">
                            <div className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground group-focus-within:text-foreground transition-colors">
                                <Mail size={18} />
                            </div>
                            <input
                                type="email"
                                value={email}
                                onChange={e => setEmail(e.target.value)}
                                className="w-full h-14 pl-12 pr-6 bg-muted/50 border border-border rounded-2xl text-foreground font-medium font-body placeholder:text-muted-foreground/50 focus:bg-background focus:border-primary focus:ring-4 focus:ring-primary/5 transition-all outline-none"
                                placeholder="beck@gmail.com"
                            />
                        </div>
                    </div>
                </div>

                <div className="flex flex-col gap-2.5 mb-10">
                    <div className="flex justify-between items-center ml-1">
                        <label className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider font-body">
                            New Password
                        </label>
                        <span className="text-[10px] text-muted-foreground/60 font-medium font-body italic">
                            Leave blank to keep current
                        </span>
                    </div>
                    <div className="relative group">
                        <div className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground group-focus-within:text-foreground transition-colors">
                            <Lock size={18} />
                        </div>
                        <input
                            type="password"
                            value={password}
                            onChange={e => setPassword(e.target.value)}
                            className="w-full h-14 pl-12 pr-6 bg-muted/50 border border-border rounded-2xl text-foreground font-medium font-body placeholder:text-muted-foreground/50 focus:bg-background focus:border-primary focus:ring-4 focus:ring-primary/5 transition-all outline-none"
                            placeholder="••••••••••••"
                        />
                    </div>
                </div>

                {message.text && (
                    <div className={`mb-8 p-4 px-5 rounded-2xl flex items-center gap-3 text-[12px] font-bold transition-all animate-in fade-in slide-in-from-top-2
                        ${message.type === 'success'
                            ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-500'
                            : 'bg-rose-500/10 border border-rose-500/20 text-rose-500'}`}>
                        {message.type === 'success' ? <CheckCircle2 size={18} /> : <XCircle size={18} />}
                        {message.text}
                    </div>
                )}

                <button
                    type="submit"
                    disabled={isUpdating}
                    className="w-full h-14 bg-primary hover:opacity-90 text-primary-foreground rounded-2xl font-bold flex items-center justify-center gap-3 transition-all active:scale-[0.98] disabled:opacity-50 shadow-lg shadow-primary/20"
                >
                    {isUpdating ? <Loader2 size={18} className="animate-spin" /> : <Save size={18} />}
                    Update Profile
                </button>
            </form>
        </div>
    );
};

export default ProfilePersonalTab;
