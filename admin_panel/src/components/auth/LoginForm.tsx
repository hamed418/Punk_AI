import { Loader2, Lock, Mail } from 'lucide-react';
import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import AuthLayout from '../layouts/AuthLayout';
import { useAuth } from '@/context/AuthContext';

const LoginForm: React.FC = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setIsSubmitting(true);
    try {
      await login(email, password);
      navigate('/chat');
    } catch (err: any) {
      setError(
        err.data?.detail ||
        err.message ||
        'Failed to login. Please check your credentials.',
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthLayout>
      <div className="relative">
        {/* Decorative Stacked Cards Effect (to the right) */}
        <div className="absolute inset-y-8 -right-4 w-full bg-white/5 border border-white/10 rounded-[2.5rem] -z-10 translate-x-2 scale-[0.98] blur-[1px]"></div>
        <div className="absolute inset-y-16 -right-8 w-full bg-white/5 border border-white/10 rounded-[2.5rem] -z-20 translate-x-4 scale-[0.96] blur-[2px]"></div>

        {/* Main Card */}
        <div className="bg-[#14141b] border border-white/10 p-10 md:p-14 shadow-2xl relative overflow-hidden">
          <div className="flex flex-col items-center">
            {/* Monkey Logo */}
            <div className="mb-10 scale-125">
              <img
                src="/logo.svg"
                alt="Punk Monkey"
                className="w-28 h-28 object-contain pixelated"
              />
            </div>

            {error && (
              <div className="w-full mb-6 p-4 bg-red-500/10 border border-red-500/20 text-red-400 rounded-xl text-xs text-center">
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="w-full space-y-6">
              <div className="space-y-4">
                <div className="relative">
                  <div className="absolute inset-y-0 left-4 flex items-center pointer-events-none text-slate-500">
                    <Mail size={18} />
                  </div>
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full bg-[#1c1c26] border border-white/10 rounded-xl py-4 pl-12 pr-4 text-white placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-white/20 transition-all text-sm"
                    placeholder="Enter your email"
                  />
                </div>

                <div className="relative">
                  <div className="absolute inset-y-0 left-4 flex items-center pointer-events-none text-slate-500">
                    <Lock size={18} />
                  </div>
                  <input
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full bg-[#1c1c26] border border-white/10 rounded-xl py-4 pl-12 pr-4 text-white placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-white/20 transition-all text-sm"
                    placeholder="Password"
                  />
                </div>
              </div>

              <div className="flex justify-end pr-2">
                <a
                  href="#"
                  className="text-[10px] uppercase font-mono text-slate-500 hover:text-white transition-colors tracking-wider"
                >
                  Forgot Password?
                </a>
              </div>

              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full bg-white text-black font-mono font-bold py-4 rounded-xl hover:bg-slate-200 transition-all flex items-center justify-center uppercase tracking-[0.15em] text-[11px]"
              >
                {isSubmitting ? (
                  <Loader2 className="animate-spin" size={18} />
                ) : (
                  'CONTINUE WITH EMAIL'
                )}
              </button>

              <div className="text-center">
                <span className="text-slate-500 text-xs font-mono uppercase tracking-widest">
                  Or
                </span>
              </div>

              <button
                type="button"
                className="w-full bg-transparent border border-white/10 text-white font-medium py-4 rounded-xl hover:bg-white/5 transition-all flex items-center justify-center gap-3 text-[13px]"
              >
                <svg className="w-5 h-5" viewBox="0 0 24 24">
                  <path
                    fill="#4285F4"
                    d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                  />
                  <path
                    fill="#34A853"
                    d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                  />
                  <path
                    fill="#FBBC05"
                    d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                  />
                  <path
                    fill="#EA4335"
                    d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                  />
                </svg>
                Continue with Google
              </button>

              <p className="text-[10px] text-slate-500 text-center mt-10 leading-relaxed opacity-60">
                Don't have an account?{' '}
                <Link
                  to="/register"
                  className="font-bold text-white hover:underline transition-colors uppercase font-mono tracking-wider ml-1"
                >
                  Sign Up
                </Link>
              </p>
            </form>
          </div>
        </div>
      </div>
    </AuthLayout>
  );
};

export default LoginForm;
