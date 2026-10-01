import React, { useState } from 'react';
import { ChevronDown, ChevronRight, Copy, Check } from 'lucide-react';

interface JsonViewerProps {
  data: any;
  level?: number;
  label?: string;
  isLast?: boolean;
}

export const JsonViewer: React.FC<JsonViewerProps> = ({ data, level = 0, label, isLast = true }) => {
  const [isExpanded, setIsExpanded] = useState(true);
  const [copied, setCopied] = useState(false);

  const type = typeof data;
  const isObject = data !== null && type === 'object';
  const isArray = Array.isArray(data);

  const toggleExpand = () => setIsExpanded(!isExpanded);

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(JSON.stringify(data, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const renderValue = (val: any) => {
    if (val === null) return <span className="text-gray-400 italic">null</span>;
    if (typeof val === 'string') return <span className="text-emerald-600">"{val}"</span>;
    if (typeof val === 'number') return <span className="text-amber-600">{val}</span>;
    if (typeof val === 'boolean') return <span className="text-purple-600">{val.toString()}</span>;
    return <span>{String(val)}</span>;
  };

  const getBracket = (open: boolean) => {
    if (isArray) return open ? '[' : ']';
    return open ? '{' : '}';
  };

  const indentation = { paddingLeft: `${level * 20}px` };

  if (!isObject) {
    return (
      <div className="flex items-start py-0.5 text-sm font-mono leading-relaxed" style={indentation}>
        {label && <span className="text-slate-500 mr-2">"{label}":</span>}
        {renderValue(data)}
        {!isLast && <span className="text-slate-400">,</span>}
      </div>
    );
  }

  const keys = Object.keys(data);
  const isEmpty = keys.length === 0;

  return (
    <div className="flex flex-col text-sm font-mono leading-relaxed">
      <div
        className="flex items-center py-0.5 group cursor-pointer hover:bg-black/5 transition-colors rounded px-1"
        style={indentation}
        onClick={toggleExpand}
      >
        {!isEmpty && (
          <span className="mr-1 text-slate-400">
            {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </span>
        )}
        {label && <span className="text-slate-500 mr-2">"{label}":</span>}
        <span className="text-slate-800">{getBracket(true)}</span>

        {!isExpanded && (
          <span className="text-slate-400 mx-1 bg-slate-200/50 px-1 rounded text-[10px]">
            {isArray ? `${data.length} items` : `${keys.length} keys`}
          </span>
        )}

        {!isExpanded && <span className="text-slate-800">{getBracket(false)}</span>}
        {!isExpanded && !isLast && <span className="text-slate-400">,</span>}

        <button
          onClick={handleCopy}
          className="ml-auto opacity-0 group-hover:opacity-100 p-1 hover:bg-white rounded transition-all text-slate-400 hover:text-slate-900"
          title="Copy JSON"
        >
          {copied ? <Check size={12} className="text-emerald-500" /> : <Copy size={12} />}
        </button>
      </div>

      {isExpanded && !isEmpty && (
        <div className="flex flex-col">
          {keys.map((key, index) => (
            <JsonViewer
              key={key}
              data={data[key]}
              level={level + 1}
              label={isArray ? undefined : key}
              isLast={index === keys.length - 1}
            />
          ))}
        </div>
      )}

      {isExpanded && (
        <div className="flex items-center py-0.5" style={indentation}>
          {!isEmpty && <span className="w-[18px]" />}
          <span className="text-slate-800">{getBracket(false)}</span>
          {!isLast && <span className="text-slate-400">,</span>}
        </div>
      )}
    </div>
  );
};
