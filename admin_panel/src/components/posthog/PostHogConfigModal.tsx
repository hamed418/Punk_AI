import React, { useState } from 'react';
import { Modal, TextInput, PasswordInput, Button, Alert, Badge } from '@mantine/core';
import { Key, Info, CheckCircle2, AlertCircle, RefreshCw, ExternalLink } from 'lucide-react';
import postHogApi, { getPostHogConfig } from '@/api/posthog';
import { useUpdatePostHogConfig } from '@/hooks/api/usePostHogApi';

interface PostHogConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const PostHogConfigForm: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const currentConfig = getPostHogConfig();
  const [host, setHost] = useState(currentConfig.host);
  const [projectId, setProjectId] = useState(currentConfig.projectId);
  const [apiKey, setApiKey] = useState(currentConfig.apiKey);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);

  const updateMutation = useUpdatePostHogConfig();

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    const result = await postHogApi.testConnection({ host, projectId, apiKey });
    setTestResult(result);
    setTesting(false);
  };

  const handleSave = () => {
    updateMutation.mutate({ host, projectId, apiKey });
    onClose();
  };

  const handleResetToDefault = () => {
    setHost('https://us.i.posthog.com');
    setProjectId('');
    setApiKey('');
    updateMutation.mutate({ host: 'https://us.i.posthog.com', projectId: '', apiKey: '' });
    setTestResult(null);
  };

  const isConfigured = Boolean(apiKey && projectId);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between p-3.5 rounded-10 bg-surface-primary border border-border-default">
        <div>
          <p className="text-xs font-semibold text-text-dark">PostHog API Architecture</p>
          <p className="text-[11px] text-text-muted mt-0.5">
            {isConfigured
              ? 'Fetching directly from PostHog Cloud API (client-side)'
              : 'Using integrated high-fidelity taxonomy preview (direct client connection)'}
          </p>
        </div>
        <Badge
          size="md"
          variant="light"
          color={isConfigured ? 'teal' : 'blue'}
        >
          {isConfigured ? 'Direct Cloud API' : 'Taxonomy Preview'}
        </Badge>
      </div>

      <div className="space-y-3">
        <TextInput
          label="PostHog Host"
          description="US Cloud: https://us.i.posthog.com | EU Cloud: https://eu.i.posthog.com"
          value={host}
          onChange={(e) => setHost(e.target.value)}
          placeholder="https://us.i.posthog.com"
          size="xs"
        />

        <div>
          <TextInput
            label="Project ID"
            description={
              <span>
                Found in PostHog{' '}
                <a
                  href="https://us.posthog.com/settings/project"
                  target="_blank"
                  rel="noreferrer"
                  className="text-highlight-teal hover:underline inline-flex items-center gap-0.5"
                >
                  Project Settings <ExternalLink size={10} />
                </a>
              </span>
            }
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            placeholder="e.g. 108392"
            size="xs"
          />
        </div>

        <div>
          <PasswordInput
            label="Personal API Key"
            description={
              <span>
                Generate at PostHog{' '}
                <a
                  href="https://us.posthog.com/settings/user-api-keys"
                  target="_blank"
                  rel="noreferrer"
                  className="text-highlight-teal hover:underline inline-flex items-center gap-0.5"
                >
                  Personal API Keys <ExternalLink size={10} />
                </a>{' '}
                (requires scopes: <code className="text-[10px] font-mono">event:read</code>, <code className="text-[10px] font-mono">project:read</code>)
              </span>
            }
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="phx_..."
            size="xs"
          />
        </div>
      </div>

      {testResult && (
        <Alert
          icon={testResult.success ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
          color={testResult.success ? 'teal' : 'red'}
          title={testResult.success ? 'Connection Successful' : 'Connection Failed'}
          variant="light"
          className="text-xs"
        >
          {testResult.message}
        </Alert>
      )}

      {/* Docs link callout */}
      <div className="p-3.5 rounded-10 bg-surface-primary border border-border-default space-y-1.5 text-[11px] text-text-muted">
        <div className="flex items-center justify-between text-text-dark font-medium">
          <span className="flex items-center gap-1.5">
            <Info size={13} className="text-highlight-teal" />
            Direct API Reference
          </span>
          <a
            href="https://posthog.com/docs/api"
            target="_blank"
            rel="noreferrer"
            className="text-highlight-teal hover:underline inline-flex items-center gap-1 text-[11px]"
          >
            posthog.com/docs/api <ExternalLink size={11} />
          </a>
        </div>
        <p>
          Queries are executed directly from this admin panel to PostHog's Events API (
          <code className="px-1 py-0.2 rounded bg-surface-card text-text-dark font-mono text-[10px]">
            /api/projects/:id/events/
          </code>
          ) and HogQL Query API with zero intermediate backend hops.
        </p>
      </div>

      <div className="flex items-center justify-between pt-3 border-t border-border-default">
        <Button
          variant="subtle"
          color="gray"
          size="xs"
          onClick={handleResetToDefault}
          disabled={!apiKey && !projectId}
        >
          Reset to Defaults
        </Button>

        <div className="flex items-center gap-2">
          <Button
            variant="default"
            size="xs"
            onClick={handleTest}
            loading={testing}
            disabled={!apiKey || !projectId}
            leftSection={<RefreshCw size={13} />}
          >
            Test Connection
          </Button>

          <Button
            variant="filled"
            color="dark"
            size="xs"
            onClick={handleSave}
          >
            Save & Connect
          </Button>
        </div>
      </div>
    </div>
  );
};

export const PostHogConfigModal: React.FC<PostHogConfigModalProps> = ({
  isOpen,
  onClose,
}) => {
  return (
    <Modal
      opened={isOpen}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2">
          <Key size={18} className="text-text-dark" />
          <h3 className="text-base font-bold text-text-dark">Direct PostHog API Configuration</h3>
        </div>
      }
      size="lg"
      centered
      classNames={{
        content: 'bg-surface-card text-text-dark border border-border-default rounded-16',
        header: 'bg-surface-card border-b border-border-default px-6 py-4',
        body: 'p-6',
      }}
    >
      {isOpen && <PostHogConfigForm onClose={onClose} />}
    </Modal>
  );
};

export default PostHogConfigModal;
