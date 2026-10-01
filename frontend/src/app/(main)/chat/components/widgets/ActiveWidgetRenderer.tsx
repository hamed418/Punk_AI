import type React from 'react'
import type { Block } from '@/types/chat'
import WidgetOauthConnect from './WidgetOauthConnect'
import WidgetOptionSelectionV2 from './WidgetOptionSelection'
import WidgetFileUploadV2 from './WidgetFileUpload'
import WidgetDateRangePickerV2 from './WidgetDateRnagePicker'
import WidgetCampaignIntakeForm from './WidgetCampaignIntakeForm'
import WidgetCampaignPreview from './WidgetCampaignPreview'
import CampaignEditor from '../editor/CampaignEditor'

interface ActiveWidgetRendererProps {
  block: Block
  onConfirm: (value: string | number) => void
  isFirstAiMessage: boolean
}

export const ActiveWidgetRenderer: React.FC<ActiveWidgetRendererProps> = ({
  block,
  onConfirm,
  isFirstAiMessage,
}) => {
  if (block.type !== 'pending_action') return null

  const { action_type } = block.content
  switch (action_type) {
    case 'option_selection':
      return (
        <WidgetOptionSelectionV2
          key={block.id}
          content={block.content}
          onConfirm={onConfirm}
          showLogo={isFirstAiMessage}
          isLatest={true}
          userResponse={null}
        />
      )
    case 'file_upload':
      return (
        <WidgetFileUploadV2
          key={block.id}
          content={block.content}
          onConfirm={onConfirm}
          showLogo={isFirstAiMessage}
          isLatest={true}
          userResponse={null}
        />
      )
    case 'oauth_connect':
      return (
        <WidgetOauthConnect
          key={block.id}
          content={block.content}
          onConfirm={onConfirm}
          isLatest={true}
        />
      )
    case 'date_range_picker':
      return (
        <WidgetDateRangePickerV2
          key={block.id}
          content={block.content}
          onConfirm={onConfirm}
          isLatest={true}
          userResponse={null}
        />
      )
    case 'campaign_intake_form':
      // The backend no longer emits this — the intake form now renders AS
      // the Campaign pane of campaign_plan_editor's "intake" phase (see
      // CampaignEditor.tsx). Kept so a thread paused on this exact interrupt
      // before that change (or a transcript persisted with it) still renders.
      return (
        <WidgetCampaignIntakeForm
          key={block.id}
          content={block.content}
          onConfirm={(v) => onConfirm(v)}
          showLogo={isFirstAiMessage}
          isLatest={true}
          userResponse={null}
        />
      )
    case 'campaign_plan_editor':
      // Keyed by identity, not by block: intake and plan arrive as two
      // different blocks (different step_key on the backend, so
      // upsertPendingAction can never merge them into one) and the post-turn
      // history refetch renumbers every block id again regardless. A constant
      // key makes React reconcile all of that into one persistent mount,
      // which is what lets the intake form build into the plan tree in place
      // instead of unmounting and remounting across the turn.
      return (
        <CampaignEditor
          key="campaign-plan-editor"
          content={block.content}
          onConfirm={(v) => onConfirm(v)}
          showLogo={isFirstAiMessage}
          isLatest={true}
        />
      )
    case 'campaign_preview':
      return (
        <WidgetCampaignPreview
          key={block.id}
          content={block.content}
          onConfirm={(v) => onConfirm(v)}
          showLogo={isFirstAiMessage}
          isLatest={true}
        />
      )
    default:
      return null
  }
}

export default ActiveWidgetRenderer
