import { Check, ChevronDown, ChevronRight, Copy } from 'lucide-react';
import type React from 'react';
import { useState } from 'react';

export type JsonPrimitive = string | number | boolean | null;
export interface JsonObject {
  [key: string]: JsonValue;
}
export type JsonArray = JsonValue[];
export type JsonValue = JsonPrimitive | JsonObject | JsonArray;
interface JsonViewerProps {
  data: JsonValue;
  level?: number;
  label?: string;
  isLast?: boolean;
}

export const JsonViewer: React.FC<JsonViewerProps> = ({
  data,
  level = 0,
  label,
  isLast = true,
}) => {
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

  const getBracket = (open: boolean) => {
    if (isArray) return open ? '[' : ']';
    return open ? '{' : '}';
  };

  const indentation = { paddingLeft: `${level * 20}px` };

  const renderValue = (val: JsonPrimitive) => {
    if (val === null) return <span className="text-gray-400 italic">null</span>;

    if (typeof val === 'string')
      return <span className="text-emerald-600">{val}</span>;

    if (typeof val === 'number')
      return <span className="text-amber-600">{val}</span>;

    if (typeof val === 'boolean')
      return <span className="text-purple-600">{val.toString()}</span>;

    return null;
  };

  if (!isObject) {
    const primitive = data as JsonPrimitive;
    return (
      <div
        className="flex items-start py-0.5 font-mono text-sm leading-relaxed"
        style={indentation}
      >
        {label && <span className="mr-2 text-slate-500">{label}:</span>}
        {renderValue(primitive)}
        {!isLast && <span className="text-slate-400">,</span>}
      </div>
    );
  }

  const keys = Object.keys(data);
  const isEmpty = keys.length === 0;

  const objectData = data as JsonObject;

  return (
    <div className="flex flex-col font-mono text-sm leading-relaxed">
      <div
        className="group flex items-center rounded px-1 py-0.5 transition-colors hover:bg-black/5"
        style={indentation}
      >
        <button
          type="button"
          onClick={toggleExpand}
          className="flex grow cursor-pointer items-center focus:outline-none"
        >
          {!isEmpty && (
            <span className="mr-1 text-slate-400">
              {isExpanded ? (
                <ChevronDown size={14} />
              ) : (
                <ChevronRight size={14} />
              )}
            </span>
          )}
          {label && <span className="mr-2 text-slate-500">{label}:</span>}
          <span className="text-slate-800">{getBracket(true)}</span>

          {!isExpanded && (
            <span className="mx-1 rounded bg-slate-200/50 px-1 text-[10px] text-slate-400">
              {isArray
                ? `${(data as JsonArray).length} items`
                : `${(keys as string[]).length} keys`}
            </span>
          )}

          {!isExpanded && (
            <span className="text-slate-800">{getBracket(false)}</span>
          )}
          {!isExpanded && !isLast && <span className="text-slate-400">,</span>}
        </button>

        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            handleCopy(e);
          }}
          className="ml-auto rounded p-1 text-slate-400 opacity-0 transition-all group-hover:opacity-100 hover:bg-white hover:text-slate-900"
          title="Copy JSON"
        >
          {copied ? (
            <Check size={12} className="text-emerald-500" />
          ) : (
            <Copy size={12} />
          )}
        </button>
      </div>

      {isExpanded && !isEmpty && (
        <div className="flex flex-col">
          {keys.map((key, index) => (
            <JsonViewer
              key={key}
              data={objectData[key]}
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
