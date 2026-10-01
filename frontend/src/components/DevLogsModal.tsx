'use client';

import { useEffect, useState } from 'react';
import { Modal, Button, ActionIcon, ScrollArea } from '@mantine/core';
import { Terminal } from 'lucide-react';

export function DevLogsModal() {
  const [opened, setOpened] = useState(false);
  const [logs, setLogs] = useState<Array<{ time: string; eventType?: string; data?: unknown; [key: string]: unknown }>>([]);

  useEffect(() => {
    if (process.env.NODE_ENV !== 'development') return;
    
    const handleLog = (e: CustomEvent) => {
      setLogs((prev) => [...prev, { time: new Date().toISOString(), ...e.detail }]);
    };
    
    window.addEventListener('dev-log', handleLog as EventListener);
    return () => window.removeEventListener('dev-log', handleLog as EventListener);
  }, []);

  if (process.env.NODE_ENV !== 'development') return null;

  return (
    <>
      <ActionIcon 
        pos="fixed" 
        top={15} 
        left="90%" 
        size="xl" 
        radius="xl" 
        color="dark" 
        variant="filled"
        onClick={() => setOpened(true)}
        style={{ zIndex: 10000, transform: 'translateX(-50%)' }}
      >
        <Terminal size={20} />
      </ActionIcon>

      <Modal opened={opened} onClose={() => setOpened(false)} title="Development Logs & EventStream" size="xl" zIndex={10000}>
        <ScrollArea h={500} className="bg-black text-green-400 p-4 rounded-md">
          {logs.map((log, i) => (
            <div key={i} className="mb-4 border-b border-gray-800 pb-3">
              <div className="flex items-center justify-between mb-2">
                <span className={`text-xs font-bold px-2 py-1 rounded ${
                  log.eventType === 'SSE_STREAM' ? 'bg-blue-900 text-blue-300' : 
                  log.eventType === 'API_FETCH' ? 'bg-purple-900 text-purple-300' : 
                  log.eventType === 'HISTORY_DATA' ? 'bg-orange-900 text-orange-300' :
                  'bg-green-900 text-green-300'
                }`}>
                  {log.eventType || 'LOG'}
                </span>
                <span className="text-[10px] text-gray-500">{new Date(log.time).toLocaleTimeString()}</span>
              </div>
              <pre className="text-xs font-mono whitespace-pre-wrap wrap-break-word text-gray-300">
                {JSON.stringify(log.data || log, null, 2)}
              </pre>
            </div>
          ))}
          {logs.length === 0 && <p className="text-sm text-gray-500 font-mono">Waiting for logs...</p>}
        </ScrollArea>
        <Button onClick={() => setLogs([])} mt="md" fullWidth color="red" variant="light">
          Clear Logs
        </Button>
      </Modal>
    </>
  );
}
