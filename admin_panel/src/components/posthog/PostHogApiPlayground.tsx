import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Play,
  Copy,
  Check,
  Download,
  Trash2,
  Plus,
  RefreshCw,
  Code2,
  Table as TableIcon,
  FileText,
  History,
  Key,
  Search,
  AlertCircle,
  CheckCircle2,
  Sparkles,
} from 'lucide-react';
import {
  postHogApi,
  getPostHogConfig,
  getPostHogApiPresets,
  normalizePostHogHost,
} from '@/api/posthog';
import type {
  PostHogApiTestResult,
  PostHogApiPreset,
  PostHogConfig,
} from '@/api/posthog';
import PostHogConfigModal from './PostHogConfigModal';

interface QueryHistoryItem {
  id: string;
  timestamp: string;
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  endpoint: string;
  status: number;
  timeMs: number;
  ok: boolean;
  body?: string;
}

const HISTORY_STORAGE_KEY = 'posthog_api_playground_history';

export const PostHogApiPlayground: React.FC = () => {
  const [config, setConfig] = useState<PostHogConfig>(() => getPostHogConfig());
  const [isConfigModalOpen, setIsConfigModalOpen] = useState(false);

  // Request State
  const [method, setMethod] = useState<'GET' | 'POST' | 'PATCH' | 'DELETE'>('GET');
  const [endpoint, setEndpoint] = useState('/api/projects/:id/events/?limit=25');
  const [queryParams, setQueryParams] = useState<Array<{ id: string; key: string; value: string; enabled: boolean }>>([]);
  const [requestBody, setRequestBody] = useState('');
  const [activeReqTab, setActiveReqTab] = useState<'params' | 'body' | 'headers' | 'auth'>('params');

  // Execution & Response State
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<PostHogApiTestResult | null>(null);
  const [activeResTab, setActiveResTab] = useState<'json' | 'table' | 'raw' | 'headers'>('json');
  const [copiedResponse, setCopiedResponse] = useState(false);
  const [jsonSearchTerm, setJsonSearchTerm] = useState('');

  // History State
  const [history, setHistory] = useState<QueryHistoryItem[]>(() => {
    try {
      const stored = localStorage.getItem(HISTORY_STORAGE_KEY);
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  });
  const [showHistory, setShowHistory] = useState(false);

  const presets = useMemo(() => getPostHogApiPresets(), []);

  // Sync config when modal closes or updates
  const refreshConfig = useCallback(() => {
    setConfig(getPostHogConfig());
  }, []);

  // Save history to localStorage
  const saveToHistory = useCallback((item: QueryHistoryItem) => {
    setHistory((prev) => {
      const updated = [item, ...prev.filter((h) => h.id !== item.id)].slice(0, 15);
      try {
        localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(updated));
      } catch {
        // ignore
      }
      return updated;
    });
  }, []);

  const handleClearHistory = () => {
    setHistory([]);
    try {
      localStorage.removeItem(HISTORY_STORAGE_KEY);
    } catch {
      // ignore
    }
  };

  // Load a Preset
  const handleSelectPreset = (preset: PostHogApiPreset) => {
    setMethod(preset.method);
    setEndpoint(preset.endpoint);
    if (preset.body) {
      setRequestBody(preset.body);
      setActiveReqTab('body');
    } else {
      setRequestBody('');
      setActiveReqTab('params');
    }
  };

  // Execute Query
  const handleExecute = useCallback(async () => {
    if (isLoading) return;
    setIsLoading(true);

    // Build extra params dictionary from enabled key-value rows
    const extraParams: Record<string, string> = {};
    queryParams.forEach((p) => {
      if (p.enabled && p.key.trim()) {
        extraParams[p.key.trim()] = p.value;
      }
    });

    const res = await postHogApi.executeQueryEndpoint({
      endpoint,
      method,
      params: extraParams,
      body: method !== 'GET' && requestBody.trim() ? requestBody : undefined,
    });

    setResult(res);
    setIsLoading(false);

    // Auto-select best response view tab
    if (res.data && typeof res.data === 'object' && Array.isArray((res.data as Record<string, unknown>).results)) {
      setActiveResTab('json');
    } else {
      setActiveResTab('json');
    }

    // Save to history
    saveToHistory({
      id: `${Date.now()}_${Math.random().toString(36).substring(2, 6)}`,
      timestamp: new Date().toISOString(),
      method,
      endpoint,
      status: res.status,
      timeMs: res.timeMs,
      ok: res.ok,
      body: method !== 'GET' ? requestBody : undefined,
    });
  }, [isLoading, queryParams, endpoint, method, requestBody, saveToHistory]);

  // Shortcut Cmd+Enter / Ctrl+Enter
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        handleExecute();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleExecute]);

  // Copy JSON response
  const handleCopyJson = () => {
    if (!result) return;
    navigator.clipboard.writeText(result.rawText || JSON.stringify(result.data, null, 2));
    setCopiedResponse(true);
    setTimeout(() => setCopiedResponse(false), 2000);
  };

  // Download response as .json file
  const handleDownloadJson = () => {
    if (!result) return;
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(result.rawText || JSON.stringify(result.data, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', dataStr);
    downloadAnchor.setAttribute('download', `posthog_api_result_${Date.now()}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  // Pretty format request JSON body
  const handleFormatRequestBody = () => {
    try {
      const parsed = JSON.parse(requestBody);
      setRequestBody(JSON.stringify(parsed, null, 2));
    } catch {
      // ignore
    }
  };

  // Table rows extraction from response data
  const tableData = useMemo(() => {
    if (!result || !result.data || typeof result.data !== 'object') return null;
    const dataObj = result.data as Record<string, unknown>;

    let rows: unknown[] = [];
    if (Array.isArray(dataObj.results)) {
      rows = dataObj.results;
    } else if (Array.isArray(result.data)) {
      rows = result.data;
    }

    if (rows.length === 0) return null;

    // Check if rows are objects or arrays (HogQL returns array of arrays)
    const first = rows[0];
    if (first && typeof first === 'object' && !Array.isArray(first)) {
      const headers = Object.keys(first as Record<string, unknown>).slice(0, 8);
      return {
        isObject: true,
        headers,
        rows: rows as Array<Record<string, unknown>>,
      };
    } else if (Array.isArray(first)) {
      const columns = Array.isArray(dataObj.columns) ? (dataObj.columns as string[]) : [];
      return {
        isObject: false,
        headers: columns.length > 0 ? columns : Array.from({ length: first.length }).map((_, i) => `Col ${i + 1}`),
        rows: rows as unknown[][],
      };
    }

    return null;
  }, [result]);

  // Method Badge Colors
  const getMethodBadgeClass = (m: string) => {
    switch (m) {
      case 'GET':
        return 'bg-highlight-teal/15 text-highlight-teal border-highlight-teal/30';
      case 'POST':
        return 'bg-blue-500/15 text-blue-500 border-blue-500/30';
      case 'PATCH':
        return 'bg-highlight-orange/15 text-highlight-orange border-highlight-orange/30';
      case 'DELETE':
        return 'bg-state-warning/15 text-state-warning border-state-warning/30';
      default:
        return 'bg-text-muted/15 text-text-muted border-border-default';
    }
  };

  return (
    <div className="space-y-4">
      {/* Playground Header Banner */}
      <div className="rounded-12 border border-border-default bg-surface-card p-4 sm:p-5 shadow-xs">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-border-default">
          <div>
            <div className="flex items-center gap-2">
              <span className="p-1 rounded bg-highlight-teal/10 text-highlight-teal">
                <Code2 size={16} />
              </span>
              <h2 className="text-sm font-bold text-text-dark tracking-tight">
                PostHog API Test Lab & Query Playground
              </h2>
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-surface-primary border border-border-default text-text-muted">
                Direct Browser Ingestion
              </span>
            </div>
            <p className="text-xs text-text-muted mt-0.5">
              Enter any PostHog REST endpoint or HogQL query to inspect live API schemas, test cursors, and verify ingestion.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowHistory((h) => !h)}
              className={`px-3 py-1.5 rounded-[8px] border text-xs font-medium transition-colors flex items-center gap-1.5 cursor-pointer ${
                showHistory
                  ? 'bg-text-dark text-surface-card border-text-dark'
                  : 'bg-surface-primary border-border-default text-text-dark hover:bg-border-default'
              }`}
            >
              <History size={13} />
              <span>History ({history.length})</span>
            </button>

            <button
              type="button"
              onClick={() => setIsConfigModalOpen(true)}
              className="px-3 py-1.5 rounded-[8px] border border-border-default bg-surface-primary hover:bg-border-default text-text-dark text-xs font-medium transition-colors flex items-center gap-1.5 cursor-pointer"
            >
              <Key size={13} />
              <span>API Settings</span>
            </button>
          </div>
        </div>

        {/* Credentials Context Bar */}
        <div className="pt-3 flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5">
              <span className="text-text-muted font-normal">Host:</span>
              <span className="font-mono text-text-dark font-medium px-1.5 py-0.5 rounded bg-surface-primary border border-border-default text-[11px]">
                {normalizePostHogHost(config.host)}
              </span>
            </div>

            <div className="flex items-center gap-1.5">
              <span className="text-text-muted font-normal">Project ID:</span>
              <span className="font-mono text-text-dark font-medium px-1.5 py-0.5 rounded bg-surface-primary border border-border-default text-[11px]">
                {config.projectId || 'Not Configured'}
              </span>
            </div>

            <div className="flex items-center gap-1.5">
              <span className="text-text-muted font-normal">API Key:</span>
              {config.apiKey ? (
                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-highlight-teal/10 text-highlight-teal text-[11px] font-mono font-medium">
                  <CheckCircle2 size={11} />
                  <span>phx_••••••••{config.apiKey.slice(-4)}</span>
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-state-warning/10 text-state-warning text-[11px] font-medium">
                  <AlertCircle size={11} />
                  <span>Missing Personal API Key</span>
                </span>
              )}
            </div>
          </div>

          <div className="text-[11px] text-text-muted flex items-center gap-1">
            <Sparkles size={12} className="text-highlight-teal" />
            <span>Placeholder <code className="text-text-dark font-mono font-bold">:id</code> resolves to project {config.projectId || '{project_id}'}</span>
          </div>
        </div>
      </div>

      {/* Quick Preset Pills Bar */}
      <div className="rounded-12 border border-border-default bg-surface-card p-3 shadow-xs space-y-2">
        <div className="flex items-center justify-between text-xs">
          <span className="font-bold text-text-dark text-[11px] uppercase tracking-wider">
            Quick Query Presets
          </span>
          <span className="text-[11px] text-text-muted">Click any preset to load its endpoint & payload</span>
        </div>

        <div className="flex items-center gap-2 overflow-x-auto custom-scrollbar pb-1">
          {presets.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => handleSelectPreset(p)}
              className={`shrink-0 px-2.5 py-1.5 rounded-[8px] border text-xs font-medium transition-all cursor-pointer flex items-center gap-1.5 ${
                endpoint === p.endpoint && method === p.method
                  ? 'border-text-dark bg-surface-primary font-semibold shadow-xs'
                  : 'border-border-default bg-surface-card hover:bg-surface-primary hover:border-text-muted text-text-dark'
              }`}
              title={p.description}
            >
              <span
                className={`text-[10px] font-bold px-1 py-0.2 rounded uppercase border ${getMethodBadgeClass(
                  p.method
                )}`}
              >
                {p.method}
              </span>
              <span>{p.name}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Main Interactive Request & Endpoint Bar */}
      <div className="rounded-12 border border-border-default bg-surface-card shadow-xs overflow-hidden">
        {/* URL Bar */}
        <div className="p-3.5 border-b border-border-default bg-surface-primary/30 flex flex-col sm:flex-row items-stretch sm:items-center gap-2.5">
          {/* Method Selector */}
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value as 'GET' | 'POST' | 'PATCH' | 'DELETE')}
            className={`px-3 py-2 text-xs font-bold rounded-[8px] border bg-surface-card cursor-pointer focus:outline-none transition-colors shrink-0 uppercase tracking-wide ${getMethodBadgeClass(
              method
            )}`}
          >
            <option value="GET">GET</option>
            <option value="POST">POST</option>
            <option value="PATCH">PATCH</option>
            <option value="DELETE">DELETE</option>
          </select>

          {/* Endpoint Input */}
          <div className="relative flex-1">
            <input
              type="text"
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              placeholder="/api/projects/:id/events/?limit=20"
              className="w-full pl-3 pr-8 py-2 text-xs font-mono rounded-[8px] border border-border-default bg-surface-card text-text-dark placeholder:text-text-muted focus:outline-none focus:border-text-dark transition-colors"
            />
            {endpoint && (
              <button
                type="button"
                onClick={() => setEndpoint('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-dark text-xs cursor-pointer"
                title="Clear endpoint"
              >
                ✕
              </button>
            )}
          </div>

          {/* Execute Button */}
          <button
            type="button"
            onClick={handleExecute}
            disabled={isLoading || !endpoint.trim()}
            className="px-4 py-2 rounded-[8px] bg-text-dark hover:opacity-90 disabled:opacity-50 text-surface-card text-xs font-bold transition-all flex items-center justify-center gap-2 cursor-pointer shadow-xs shrink-0"
          >
            {isLoading ? (
              <RefreshCw size={14} className="animate-spin" />
            ) : (
              <Play size={14} className="fill-current" />
            )}
            <span>Send Request</span>
            <span className="hidden md:inline-block text-[10px] opacity-70 border border-white/20 px-1 py-0.2 rounded font-mono">
              ⌘↵
            </span>
          </button>
        </div>

        {/* Request Options Tabs */}
        <div className="border-b border-border-default px-4 pt-2 bg-surface-card flex items-center gap-4 text-xs font-medium">
          <button
            type="button"
            onClick={() => setActiveReqTab('params')}
            className={`pb-2.5 border-b-2 transition-colors cursor-pointer flex items-center gap-1.5 ${
              activeReqTab === 'params'
                ? 'border-text-dark text-text-dark font-bold'
                : 'border-transparent text-text-muted hover:text-text-dark'
            }`}
          >
            <span>Query Params</span>
            {queryParams.filter((p) => p.enabled && p.key).length > 0 && (
              <span className="w-4 h-4 rounded-full bg-highlight-teal/15 text-highlight-teal text-[10px] flex items-center justify-center font-bold">
                {queryParams.filter((p) => p.enabled && p.key).length}
              </span>
            )}
          </button>

          <button
            type="button"
            onClick={() => setActiveReqTab('body')}
            className={`pb-2.5 border-b-2 transition-colors cursor-pointer flex items-center gap-1.5 ${
              activeReqTab === 'body'
                ? 'border-text-dark text-text-dark font-bold'
                : 'border-transparent text-text-muted hover:text-text-dark'
            }`}
          >
            <span>Body (JSON / HogQL)</span>
            {requestBody.trim() && (
              <span className="w-2 h-2 rounded-full bg-blue-500" />
            )}
          </button>

          <button
            type="button"
            onClick={() => setActiveReqTab('headers')}
            className={`pb-2.5 border-b-2 transition-colors cursor-pointer ${
              activeReqTab === 'headers'
                ? 'border-text-dark text-text-dark font-bold'
                : 'border-transparent text-text-muted hover:text-text-dark'
            }`}
          >
            Headers
          </button>
        </div>

        {/* Request Options Content */}
        <div className="p-4 bg-surface-primary/10">
          {activeReqTab === 'params' && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs text-text-muted pb-1">
                <span>Extra URL Query Parameters</span>
                <button
                  type="button"
                  onClick={() =>
                    setQueryParams((prev) => [
                      ...prev,
                      { id: String(Date.now()), key: '', value: '', enabled: true },
                    ])
                  }
                  className="px-2 py-1 rounded border border-border-default bg-surface-card hover:bg-surface-primary text-text-dark font-medium flex items-center gap-1 cursor-pointer"
                >
                  <Plus size={12} />
                  <span>Add Parameter</span>
                </button>
              </div>

              {queryParams.length === 0 ? (
                <div className="py-4 text-center text-xs text-text-muted border border-dashed border-border-default rounded-8">
                  No extra query parameters. Click <strong>Add Parameter</strong> or append query params directly to the URL bar above.
                </div>
              ) : (
                <div className="space-y-1.5">
                  {queryParams.map((p, idx) => (
                    <div key={p.id} className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={p.enabled}
                        onChange={(e) => {
                          const val = e.target.checked;
                          setQueryParams((prev) =>
                            prev.map((item, i) => (i === idx ? { ...item, enabled: val } : item))
                          );
                        }}
                        className="rounded cursor-pointer"
                      />
                      <input
                        type="text"
                        placeholder="Key (e.g. limit, distinct_id)"
                        value={p.key}
                        onChange={(e) => {
                          const val = e.target.value;
                          setQueryParams((prev) =>
                            prev.map((item, i) => (i === idx ? { ...item, key: val } : item))
                          );
                        }}
                        className="flex-1 px-2.5 py-1.5 text-xs font-mono rounded-[6px] border border-border-default bg-surface-card text-text-dark"
                      />
                      <input
                        type="text"
                        placeholder="Value"
                        value={p.value}
                        onChange={(e) => {
                          const val = e.target.value;
                          setQueryParams((prev) =>
                            prev.map((item, i) => (i === idx ? { ...item, value: val } : item))
                          );
                        }}
                        className="flex-1 px-2.5 py-1.5 text-xs font-mono rounded-[6px] border border-border-default bg-surface-card text-text-dark"
                      />
                      <button
                        type="button"
                        onClick={() =>
                          setQueryParams((prev) => prev.filter((_, i) => i !== idx))
                        }
                        className="p-1.5 text-text-muted hover:text-state-warning transition-colors cursor-pointer"
                        title="Remove param"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeReqTab === 'body' && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="text-text-muted">Request Body Payload (JSON or HogQL string)</span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setRequestBody(
                        JSON.stringify(
                          {
                            query: {
                              kind: 'HogQLQuery',
                              query: 'SELECT event, count() FROM events GROUP BY event ORDER BY count() DESC LIMIT 25',
                            },
                          },
                          null,
                          2
                        )
                      );
                      setMethod('POST');
                      setEndpoint('/api/projects/:id/query/');
                    }}
                    className="text-[11px] text-highlight-teal hover:underline cursor-pointer"
                  >
                    + Insert HogQL Template
                  </button>
                  <button
                    type="button"
                    onClick={handleFormatRequestBody}
                    disabled={!requestBody.trim()}
                    className="px-2 py-0.5 rounded border border-border-default bg-surface-card hover:bg-surface-primary text-[11px] font-medium text-text-dark cursor-pointer disabled:opacity-40"
                  >
                    Beautify JSON
                  </button>
                  <button
                    type="button"
                    onClick={() => setRequestBody('')}
                    disabled={!requestBody.trim()}
                    className="px-2 py-0.5 rounded border border-border-default bg-surface-card hover:bg-surface-primary text-[11px] font-medium text-text-muted hover:text-state-warning cursor-pointer disabled:opacity-40"
                  >
                    Clear
                  </button>
                </div>
              </div>

              <textarea
                value={requestBody}
                onChange={(e) => setRequestBody(e.target.value)}
                placeholder={'{\n  "query": {\n    "kind": "HogQLQuery",\n    "query": "SELECT event, count() FROM events GROUP BY event ORDER BY count() DESC"\n  }\n}'}
                rows={6}
                className="w-full p-3 font-mono text-xs rounded-[8px] border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark transition-colors custom-scrollbar leading-relaxed"
              />
            </div>
          )}

          {activeReqTab === 'headers' && (
            <div className="space-y-2 text-xs">
              <span className="text-text-muted">Outbound Request Headers</span>
              <div className="rounded-[8px] border border-border-default bg-surface-card p-3 font-mono space-y-1.5">
                <div className="flex items-center justify-between text-text-dark">
                  <span className="font-semibold text-text-muted">Authorization:</span>
                  <span>{config.apiKey ? `Bearer phx_••••••••${config.apiKey.slice(-4)}` : '(None configured)'}</span>
                </div>
                <div className="flex items-center justify-between text-text-dark">
                  <span className="font-semibold text-text-muted">Content-Type:</span>
                  <span>application/json</span>
                </div>
                <div className="flex items-center justify-between text-text-dark">
                  <span className="font-semibold text-text-muted">Target Host:</span>
                  <span>{normalizePostHogHost(config.host)}</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* History Drawer if open */}
      {showHistory && (
        <div className="rounded-12 border border-border-default bg-surface-card p-4 shadow-xs space-y-3">
          <div className="flex items-center justify-between border-b border-border-default pb-2 text-xs">
            <div className="flex items-center gap-1.5 font-bold text-text-dark">
              <History size={14} />
              <span>Recent Query History</span>
            </div>
            <button
              type="button"
              onClick={handleClearHistory}
              className="text-text-muted hover:text-state-warning transition-colors cursor-pointer"
            >
              Clear History
            </button>
          </div>

          {history.length === 0 ? (
            <div className="py-6 text-center text-xs text-text-muted">
              No queries run yet in this session.
            </div>
          ) : (
            <div className="space-y-1.5 max-h-56 overflow-y-auto custom-scrollbar">
              {history.map((h) => (
                <div
                  key={h.id}
                  onClick={() => {
                    setMethod(h.method);
                    setEndpoint(h.endpoint);
                    if (h.body) setRequestBody(h.body);
                  }}
                  className="p-2 rounded-[6px] border border-border-default bg-surface-primary/40 hover:bg-surface-primary flex items-center justify-between gap-3 text-xs cursor-pointer transition-colors"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span
                      className={`text-[10px] font-bold px-1.5 py-0.2 rounded uppercase border ${getMethodBadgeClass(
                        h.method
                      )}`}
                    >
                      {h.method}
                    </span>
                    <span className="font-mono text-text-dark truncate text-[11px]">
                      {h.endpoint}
                    </span>
                  </div>

                  <div className="flex items-center gap-2 shrink-0 text-[11px]">
                    <span
                      className={`font-semibold px-1.5 py-0.2 rounded ${
                        h.ok ? 'bg-highlight-teal/10 text-highlight-teal' : 'bg-state-warning/10 text-state-warning'
                      }`}
                    >
                      {h.status || 'ERR'}
                    </span>
                    <span className="text-text-muted font-mono">{h.timeMs}ms</span>
                    <span className="text-[10px] text-text-muted">
                      {new Date(h.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Response Display Section */}
      <div className="rounded-12 border border-border-default bg-surface-card shadow-xs overflow-hidden">
        {/* Response Top Bar: Status, Timing, Item Count & Export Actions */}
        <div className="p-3.5 border-b border-border-default bg-surface-card flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="text-xs font-bold text-text-dark uppercase tracking-wider">
              Response
            </span>

            {result ? (
              <div className="flex items-center gap-2">
                {/* Status Badge */}
                <span
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold ${
                    result.ok
                      ? 'bg-highlight-teal/15 text-highlight-teal border border-highlight-teal/30'
                      : 'bg-state-warning/15 text-state-warning border border-state-warning/30'
                  }`}
                >
                  {result.ok ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
                  <span>
                    {result.status} {result.statusText}
                  </span>
                </span>

                {/* Duration */}
                <span className="px-2 py-0.5 rounded bg-surface-primary border border-border-default text-text-muted text-xs font-mono">
                  ⚡️ {result.timeMs} ms
                </span>

                {/* Count */}
                {result.count !== undefined && (
                  <span className="px-2 py-0.5 rounded bg-surface-primary border border-border-default text-text-dark text-xs font-medium">
                    {result.count.toLocaleString()} items
                  </span>
                )}
              </div>
            ) : (
              <span className="text-xs text-text-muted">
                (No request sent yet. Click <strong>Send Request</strong> above)
              </span>
            )}
          </div>

          {result && (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleCopyJson}
                className="px-2.5 py-1 rounded-[6px] border border-border-default bg-surface-primary hover:bg-border-default text-text-dark text-xs font-medium transition-colors flex items-center gap-1 cursor-pointer"
              >
                {copiedResponse ? <Check size={13} className="text-highlight-teal" /> : <Copy size={13} />}
                <span>{copiedResponse ? 'Copied' : 'Copy JSON'}</span>
              </button>

              <button
                type="button"
                onClick={handleDownloadJson}
                className="px-2.5 py-1 rounded-[6px] border border-border-default bg-surface-primary hover:bg-border-default text-text-dark text-xs font-medium transition-colors flex items-center gap-1 cursor-pointer"
              >
                <Download size={13} />
                <span>Export JSON</span>
              </button>
            </div>
          )}
        </div>

        {/* View Mode Tabs (JSON, Table, Raw, Headers) */}
        {result && (
          <div className="px-4 py-2 border-b border-border-default bg-surface-primary/30 flex items-center justify-between gap-3 text-xs">
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setActiveResTab('json')}
                className={`px-2.5 py-1 rounded-[6px] transition-colors cursor-pointer flex items-center gap-1.5 ${
                  activeResTab === 'json'
                    ? 'bg-text-dark text-surface-card font-bold shadow-xs'
                    : 'text-text-muted hover:text-text-dark'
                }`}
              >
                <Code2 size={13} />
                <span>Formatted JSON</span>
              </button>

              {tableData && (
                <button
                  type="button"
                  onClick={() => setActiveResTab('table')}
                  className={`px-2.5 py-1 rounded-[6px] transition-colors cursor-pointer flex items-center gap-1.5 ${
                    activeResTab === 'table'
                      ? 'bg-text-dark text-surface-card font-bold shadow-xs'
                      : 'text-text-muted hover:text-text-dark'
                  }`}
                >
                  <TableIcon size={13} />
                  <span>Table View</span>
                </button>
              )}

              <button
                type="button"
                onClick={() => setActiveResTab('raw')}
                className={`px-2.5 py-1 rounded-[6px] transition-colors cursor-pointer flex items-center gap-1.5 ${
                  activeResTab === 'raw'
                    ? 'bg-text-dark text-surface-card font-bold shadow-xs'
                    : 'text-text-muted hover:text-text-dark'
                }`}
              >
                <FileText size={13} />
                <span>Raw Text</span>
              </button>

              <button
                type="button"
                onClick={() => setActiveResTab('headers')}
                className={`px-2.5 py-1 rounded-[6px] transition-colors cursor-pointer ${
                  activeResTab === 'headers'
                    ? 'bg-text-dark text-surface-card font-bold shadow-xs'
                    : 'text-text-muted hover:text-text-dark'
                }`}
              >
                Headers ({Object.keys(result.headers || {}).length})
              </button>
            </div>

            {/* In-Response Search Filter */}
            {activeResTab === 'json' && (
              <div className="relative w-48">
                <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none" />
                <input
                  type="text"
                  placeholder="Filter response keys..."
                  value={jsonSearchTerm}
                  onChange={(e) => setJsonSearchTerm(e.target.value)}
                  className="w-full pl-7 pr-2 py-0.5 text-[11px] rounded-[6px] border border-border-default bg-surface-card text-text-dark placeholder:text-text-muted focus:outline-none"
                />
              </div>
            )}
          </div>
        )}

        {/* Response Body Contents */}
        <div className="p-4">
          {!result ? (
            <div className="py-16 text-center space-y-2">
              <div className="w-12 h-12 rounded-full bg-surface-primary border border-border-default mx-auto flex items-center justify-center text-text-muted">
                <Code2 size={24} />
              </div>
              <h3 className="text-sm font-bold text-text-dark">Ready to Query PostHog</h3>
              <p className="text-xs text-text-muted max-w-sm mx-auto">
                Pick one of the quick presets above or enter a custom endpoint to test PostHog queries, view raw schemas, and verify integration.
              </p>
            </div>
          ) : result.error && !result.data ? (
            <div className="p-4 rounded-8 border border-state-warning/30 bg-state-warning/5 text-xs text-state-warning space-y-1">
              <p className="font-bold flex items-center gap-1.5">
                <AlertCircle size={14} />
                <span>Request Failed</span>
              </p>
              <p className="font-mono">{result.error}</p>
              <p className="text-[11px] text-text-muted mt-2">
                Target URL: <code className="text-text-dark">{result.url}</code>
              </p>
            </div>
          ) : (
            <div>
              {/* Tab 1: Formatted JSON */}
              {activeResTab === 'json' && (
                <pre className="p-4 rounded-8 bg-surface-primary/50 border border-border-default text-xs font-mono text-text-dark overflow-x-auto custom-scrollbar max-h-125 leading-relaxed whitespace-pre-wrap">
                  {JSON.stringify(result.data, null, 2)}
                </pre>
              )}

              {/* Tab 2: Table View */}
              {activeResTab === 'table' && tableData && (
                <div className="border border-border-default rounded-8 overflow-hidden">
                  <div className="overflow-x-auto custom-scrollbar max-h-125">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead className="bg-surface-primary text-text-muted font-bold text-[11px] uppercase tracking-wider sticky top-0 border-b border-border-default z-10">
                        <tr>
                          {tableData.headers.map((h, i) => (
                            <th key={i} className="py-2.5 px-3 border-r border-border-default/60 last:border-r-0">
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border-default bg-surface-card">
                        {tableData.isObject
                          ? (tableData.rows as Array<Record<string, unknown>>).map((row, idx) => (
                              <tr key={idx} className="hover:bg-surface-primary/40 font-mono text-[11px]">
                                {tableData.headers.map((h, i) => {
                                  const val = row[h];
                                  const strVal = typeof val === 'object' ? JSON.stringify(val) : String(val ?? '—');
                                  return (
                                    <td
                                      key={i}
                                      className="py-2 px-3 truncate max-w-48 text-text-dark border-r border-border-default/40 last:border-r-0"
                                      title={strVal}
                                    >
                                      {strVal}
                                    </td>
                                  );
                                })}
                              </tr>
                            ))
                          : (tableData.rows as unknown[][]).map((row, idx) => (
                              <tr key={idx} className="hover:bg-surface-primary/40 font-mono text-[11px]">
                                {row.map((cell, i) => {
                                  const strVal = typeof cell === 'object' ? JSON.stringify(cell) : String(cell ?? '—');
                                  return (
                                    <td
                                      key={i}
                                      className="py-2 px-3 truncate max-w-48 text-text-dark border-r border-border-default/40 last:border-r-0"
                                      title={strVal}
                                    >
                                      {strVal}
                                    </td>
                                  );
                                })}
                              </tr>
                            ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Tab 3: Raw Text */}
              {activeResTab === 'raw' && (
                <textarea
                  readOnly
                  value={result.rawText}
                  rows={16}
                  className="w-full p-4 font-mono text-xs rounded-8 border border-border-default bg-surface-primary/50 text-text-dark focus:outline-none custom-scrollbar"
                />
              )}

              {/* Tab 4: Headers */}
              {activeResTab === 'headers' && (
                <div className="border border-border-default rounded-8 overflow-hidden text-xs">
                  <table className="w-full text-left font-mono">
                    <thead className="bg-surface-primary text-text-muted font-semibold text-[11px]">
                      <tr>
                        <th className="py-2 px-3 border-b border-border-default">Header</th>
                        <th className="py-2 px-3 border-b border-border-default">Value</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-default bg-surface-card text-[11px]">
                      {Object.entries(result.headers || {}).map(([k, v], i) => (
                        <tr key={i} className="hover:bg-surface-primary/30">
                          <td className="py-2 px-3 font-semibold text-text-dark">{k}</td>
                          <td className="py-2 px-3 text-text-muted break-all">{v}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* PostHog Configuration Modal */}
      <PostHogConfigModal
        isOpen={isConfigModalOpen}
        onClose={() => {
          setIsConfigModalOpen(false);
          refreshConfig();
        }}
      />
    </div>
  );
};

export default PostHogApiPlayground;
