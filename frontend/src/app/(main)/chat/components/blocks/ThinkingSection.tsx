'use client';
import { ChevronRight } from 'lucide-react';
import { useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useChat } from '@/contexts/ChatContext';
import { AgentLogoStack, SingleAgentLogo } from './MessageBlockUI';
import { TextShimmer } from '../thinking/TextShimmer';

interface ThinkingSectionProps {
  thinking: string | null | undefined;
  isStreaming: boolean;
}

export const ThinkingSection: React.FC<ThinkingSectionProps> = ({
  thinking,
  isStreaming,
}) => {
  const { currentStepLabel } = useChat();
  const [open, setOpen] = useState(false);
  const { formattedThinking, agentCount, latestTitle } = useMemo(() => {
    const text = thinking ?? '';
    const agentRegex =
      /(?:Punk reasoning:\s*\*\*([^*]+)\*\*(?=\s*$))|(?:^\*\*([^*]+)\*\*(?=\s*$))|(?:Punk reasoning:)/gim;

    // Extract all titles first to find the latest one
    const matches = [...text.matchAll(agentRegex)];
    const titles = matches
      .map((m) => (m[1] || m[2] || '').trim())
      .filter(Boolean);
    const derivedTitle = titles.length > 0 ? titles[titles.length - 1] : '';

    // Format the text with agent headers
    let count = 0;
    const formatted = text.replace(agentRegex, (_match, title1, title2) => {
      const title = title1 || title2;
      count++;
      // Use &nbsp; to force an empty line in markdown, since multiple \n collapse
      const prefix = count > 1 ? '\n\n&nbsp;\n\n' : '';
      // Cycle through agents 1-4 deterministically
      const currentAgent = ((count - 1) % 4) + 1;

      if (title) {
        return `${prefix}###### Agent ${currentAgent}: ${title.trim()}`;
      }
      return `${prefix}###### Agent ${currentAgent}:`;
    });

    return {
      formattedThinking: formatted,
      agentCount: Math.max(1, Math.min(matches.length, 4)),
      latestTitle: derivedTitle,
    };
  }, [thinking]);

  const hasThinkingData = Boolean(thinking && thinking.trim().length > 0);

  if (!thinking && !isStreaming) return null;

  return (
    <div
      className={`mt-2 mb-4 overflow-hidden transition-all ease-in-out ${open ? 'w-full delay-0 duration-200' : 'w-full delay-150 duration-200'}`}
      style={{
        maxWidth:
          open || isStreaming ? '56rem' : `${120 + agentCount * 14}px`,
      }}
    >
      <button
        type="button"
        onClick={() => {
          if (hasThinkingData) {
            setOpen(!open);
          }
        }}
        disabled={!hasThinkingData}
        className={`font-ocrx! flex w-max items-center text-[17px]! leading-6! font-black tracking-[0.02em] uppercase transition-opacity ${
          hasThinkingData
            ? 'cursor-pointer hover:opacity-80'
            : 'cursor-default'
        }`}
      >
        <AgentLogoStack
          count={agentCount}
          animated={isStreaming}
          scale={0.3}
        />
        {isStreaming ? (
          <TextShimmer className="pl-2 font-black">
            {latestTitle || currentStepLabel || 'thinking something'}
          </TextShimmer>
        ) : (
          <span className="text-secondary-text pl-2 text-[18px]">Thoughts</span>
        )}
        {hasThinkingData && (
          <ChevronRight
            className="text-primary-text size-3 transition-transform duration-150"
            style={{ rotate: open ? '90deg' : '0deg' }}
          />
        )}
      </button>

      <div
        className={`grid transition-all ease-in-out ${
          open
            ? 'mt-2 grid-rows-[1fr] delay-0 duration-200'
            : 'grid-rows-[0fr] delay-150 duration-200'
        }`}
      >
        <div className="overflow-hidden">
          <div
            className={`chat-markdown thinking-markdown font-body text-secondary-text pl-6 text-[17px] leading-6 font-medium transition-opacity ${open ? 'opacity-100 delay-200 duration-200' : 'opacity-0 delay-0 duration-150'} ${isStreaming ? 'streaming-cursor' : ''}`}
          >
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                p: ({ children }) => (
                  <p className="m-0 text-[12px] leading-4 opacity-60 last:pb-0">
                    {children}
                  </p>
                ),
                h6: ({ children }) => {
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  const extractText = (node: any): string => {
                    if (typeof node === 'string') return node;
                    if (Array.isArray(node))
                      return node.map(extractText).join('');
                    if (node?.props?.children)
                      return extractText(node.props.children);
                    return '';
                  };
                  const textContent = extractText(children);
                  const match = textContent.match(/^Agent (\d+):?(.*)/);
                  if (match) {
                    const c = parseInt(match[1], 10);
                    const title = match[2];
                    return (
                      <div className="relative flex items-center not-italic">
                        <div className="absolute -left-6 flex w-6 items-center justify-center">
                          <SingleAgentLogo index={c} scale={0.3} />
                        </div>
                        <span className="text-primary-text text-[12px] font-medium ">
                          Agent {c}:{title}
                        </span>
                      </div>
                    );
                  }
                  return <h6>{children}</h6>;
                },
              }}
            >
              {formattedThinking}
            </ReactMarkdown>
            <div className="mt-2 flex w-full justify-end">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="text-primary-text cursor-pointer text-[12px]! font-semibold underline"
              >
                Hide thoughts
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
