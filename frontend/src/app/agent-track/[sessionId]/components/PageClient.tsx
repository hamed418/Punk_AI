'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams, useRouter } from 'next/navigation';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Activity,
  Bug,
  ChevronLeft,
  Cpu,
  Database,
  ExternalLink,
  Layers,
  RefreshCw,
  Terminal,
} from 'lucide-react';
import { useState } from 'react';
import { getStateAction, getDebugAction } from '@/actions/chat.actions';
import { JsonViewer, type JsonValue } from '@/components/JsonViewer';

type TabType = 'state' | 'debug';

export default function AgentTrackClient() {
  const params = useParams();
  const sessionId = params.sessionId as string;
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<TabType>('state');

  // Fetch State Data
  const {
    data: stateData,
    isLoading: isLoadingState,
    isFetching: isFetchingState,
    refetch: refetchState,
    error: stateError,
  } = useQuery({
    queryKey: ['agent-state', sessionId],
    queryFn: async () => {
      const result = await getStateAction(sessionId);
      if (!result.success) throw new Error(result.error);
      return result.data;
    },
    enabled: !!sessionId && activeTab === 'state',
  });

  // Fetch Debug Data
  const {
    data: debugData,
    isLoading: isLoadingDebug,
    isFetching: isFetchingDebug,
    refetch: refetchDebug,
    error: debugError,
  } = useQuery({
    queryKey: ['agent-debug', sessionId],
    queryFn: async () => {
      const result = await getDebugAction(sessionId);
      if (!result.success) throw new Error(result.error);
      return result.data;
    },
    enabled: !!sessionId && activeTab === 'debug',
  });

  const isLoading = activeTab === 'state' ? isLoadingState : isLoadingDebug;
  const isFetching = activeTab === 'state' ? isFetchingState : isFetchingDebug;
  const currentData = activeTab === 'state' ? stateData : debugData;
  const currentError = activeTab === 'state' ? stateError : debugError;

  const handleRefresh = () => {
    if (activeTab === 'state') refetchState();
    else refetchDebug();
  };

  return (
    <div className="font-body flex min-h-screen flex-col bg-[#F0F0E8] text-slate-900">
      {/* Header */}
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/70 px-6 py-4 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              type="button"
              onClick={() => router.back()}
              className="rounded-full p-2 text-slate-500 transition-colors hover:bg-slate-100"
            >
              <ChevronLeft size={20} />
            </button>
            <div>
              <h1 className="flex items-center gap-2 text-xl font-bold tracking-tight">
                <Activity size={20} className="text-amber-600" />
                Agent Tracker
              </h1>
              <p className="mt-0.5 font-mono text-xs text-slate-500">
                SID: <span className="text-amber-700">{sessionId}</span>
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleRefresh}
              disabled={isFetching}
              className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold shadow-sm transition-all hover:bg-slate-50 active:scale-95 disabled:opacity-50"
            >
              <RefreshCw
                size={14}
                className={isFetching ? 'animate-spin' : ''}
              />
              Refresh
            </button>
            <a
              href={`/chat/${sessionId}`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white shadow-md transition-all hover:bg-black active:scale-95"
            >
              <ExternalLink size={14} />
              Open Chat
            </a>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-6 p-6">
        {/* Tab Switcher */}
        <div className="flex w-fit items-center gap-1 self-center rounded-2xl border border-slate-200 bg-white/50 p-1 sm:self-start">
          <button
            type="button"
            onClick={() => setActiveTab('state')}
            className={`flex items-center gap-2 rounded-xl px-6 py-2.5 text-sm font-bold transition-all ${
              activeTab === 'state'
                ? 'border border-slate-100 bg-white text-amber-600 shadow-sm'
                : 'text-slate-500 hover:text-slate-800'
            }`}
          >
            <Database size={16} />
            State
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('debug')}
            className={`flex items-center gap-2 rounded-xl px-6 py-2.5 text-sm font-bold transition-all ${
              activeTab === 'debug'
                ? 'border border-slate-100 bg-white text-purple-600 shadow-sm'
                : 'text-slate-500 hover:text-slate-800'
            }`}
          >
            <Bug size={16} />
            Debug
          </button>
        </div>

        {/* Content Area */}
        <div className="flex min-h-125 flex-1 flex-col overflow-hidden rounded-4xl border border-slate-200 bg-white shadow-xl shadow-slate-200/50">
          {/* Internal Header */}
          <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/50 px-8 py-5">
            <div className="flex items-center gap-3">
              <div
                className={`rounded-lg p-2 ${activeTab === 'state' ? 'bg-amber-50 text-amber-600' : 'bg-purple-50 text-purple-600'}`}
              >
                {activeTab === 'state' ? (
                  <Layers size={18} />
                ) : (
                  <Terminal size={18} />
                )}
              </div>
              <div>
                <h3 className="font-bold text-slate-800 capitalize">
                  {activeTab} Snapshot
                </h3>
                <p className="text-xs text-slate-400">
                  Real-time graph {activeTab} inspection
                </p>
              </div>
            </div>
            {isFetching && (
              <div className="flex animate-pulse items-center gap-2 text-[10px] font-bold tracking-widest text-amber-600 uppercase">
                <Cpu size={12} className="animate-spin" />
                Updating State...
              </div>
            )}
          </div>

          <div className="custom-scrollbar flex-1 overflow-auto p-6">
            <AnimatePresence mode="wait">
              {isLoading ? (
                <motion.div
                  key="loading"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="flex h-full flex-col items-center justify-center gap-4 py-20"
                >
                  <div className="relative">
                    <div className="h-16 w-16 animate-spin rounded-full border-4 border-slate-100 border-t-amber-600"></div>
                    <Activity
                      className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 text-amber-600"
                      size={24}
                    />
                  </div>
                  <p className="animate-pulse font-medium text-slate-400">
                    Syncing with graph...
                  </p>
                </motion.div>
              ) : currentError ? (
                <motion.div
                  key="error"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="flex h-full flex-col items-center justify-center gap-4 py-20"
                >
                  <div className="flex h-16 w-16 items-center justify-center rounded-full bg-red-50 text-red-500">
                    <Bug size={32} />
                  </div>
                  <div className="text-center">
                    <h4 className="font-bold text-slate-800">
                      Connection Failed
                    </h4>
                    <p className="mt-1 max-w-xs text-sm text-slate-500">
                      Could not fetch {activeTab} for session {sessionId}. Make
                      sure the session exists and the agent is initialized.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={handleRefresh}
                    className="rounded-xl bg-red-500 px-6 py-2 text-sm font-bold text-white shadow-lg shadow-red-200 transition-all hover:bg-red-600"
                  >
                    Retry Connection
                  </button>
                </motion.div>
              ) : (
                <motion.div
                  key={activeTab}
                  initial={{ opacity: 0, x: activeTab === 'state' ? -20 : 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ type: 'spring', damping: 25, stiffness: 200 }}
                  className="rounded-2xl border border-slate-100/50 bg-slate-50/50 p-4"
                >
                  <JsonViewer data={(currentData || {}) as JsonValue} />
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Footer stats */}
          <div className="flex items-center justify-between border-t border-slate-100 bg-white px-8 py-3 text-[10px] font-bold tracking-widest text-slate-400 uppercase">
            <div className="flex items-center gap-4">
              <span>
                Status: <span className="text-emerald-500">Connected</span>
              </span>
              <span>
                Latency: <span className="text-slate-600">24ms</span>
              </span>
            </div>
            <span>v1.0.4-beta</span>
          </div>
        </div>
      </main>

      <style
        dangerouslySetInnerHTML={{
          __html: `
        .custom-scrollbar::-webkit-scrollbar {
          width: 8px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background-color: rgba(0, 0, 0, 0.05);
          border-radius: 20px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background-color: rgba(0, 0, 0, 0.1);
        }
      `,
        }}
      />
    </div>
  );
}
