import {
  Bell,
  LayoutDashboard,
  LogOut,
  MessageSquare,
  Search,
  Settings,
} from 'lucide-react';
import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';

const Navbar: React.FC = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const navItems = [
    { label: 'Dashboard', icon: LayoutDashboard, path: '/dashboard' },
    { label: 'Chatbot', icon: MessageSquare, path: '/chat' },
  ];

  return (
    <nav className="h-16 bg-background/80 backdrop-blur-md border-b border-border flex items-center justify-between px-8 shrink-0">
      <div className="flex items-center gap-10">
        <div
          className="flex items-center gap-2 cursor-pointer group"
          onClick={() => navigate('/dashboard')}
        >
          <div className="w-8 h-8 rounded-lg flex items-center justify-center transition-transform group-hover:scale-110">
            <img src="/logo.svg" alt="Logo" className="w-12 h-12" />
          </div>
          <span className="font-black text-xl tracking-tight text-white dark:text-black">
            Punk Ad
          </span>
        </div>

        <div className="hidden md:flex items-center gap-1">
          {navItems.map((item) => (
            <button
              key={item.path}
              onClick={() => navigate(item.path)}
              className={`px-4 py-2 rounded-lg text-sm font-semibold transition-all ${
                location.pathname.startsWith(item.path)
                  ? 'bg-primary-600/10 text-primary-500'
                  : 'text-slate-400 hover:bg-white/5 hover:text-white'
              }`}
            >
              <div className="flex items-center gap-2">
                <item.icon size={18} />
                {item.label}
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-6">
        <div className="relative hidden lg:block">
          <Search
            className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
            size={16}
          />
          <input
            type="text"
            placeholder="Search campaigns..."
            className="pl-10 pr-4 py-2 bg-white/5 border border-white/10 rounded-full text-xs text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 w-64"
          />
        </div>

        <div className="flex items-center gap-2">
          <button className="p-2 text-slate-400 hover:bg-white/5 rounded-full transition-colors relative">
            <Bell size={20} />
            <span className="absolute top-2 right-2 w-2 h-2 bg-red-500 rounded-full border-2 border-background"></span>
          </button>
          <button className="p-2 text-slate-400 hover:bg-white/5 rounded-full transition-colors uppercase">
            <Settings size={20} />
          </button>
        </div>

        <div className="h-8 w-px bg-slate-200"></div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <div className="w-9 h-9 bg-primary-100 text-primary-700 rounded-full flex items-center justify-center font-bold text-sm">
              {user?.full_name
                ?.split(' ')
                .map((n) => n[0])
                .join('') || 'U'}
            </div>
            <div className="hidden sm:block">
              <div className="text-xs font-bold text-white leading-none">
                {user?.full_name}
              </div>
              <div className="text-[10px] text-slate-500 mt-1 uppercase tracking-wider font-semibold">
                Pro Plan
              </div>
            </div>
          </div>

          <button
            onClick={handleLogout}
            className="p-2 text-slate-400 hover:text-red-600 transition-colors"
            title="Logout"
          >
            <LogOut size={20} />
          </button>
        </div>
      </div>
    </nav>
  );
};

export default Navbar;
