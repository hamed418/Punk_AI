"use client";
import { useEffect, useRef, useState } from 'react'
import MetaConnect from '@/components/MetaConnect'
// Server action, not lib/api/connect directly — that module's fetcher pulls in
// next/headers, which cannot be bundled into a client component.
import { adsStatusAction } from '@/actions/connect.actions'
import type { PendingActionBlock } from '@/types/chat'
import WidgetLayout from './WidgetLayout'
import { trackEvent } from '@/lib/analytics'

interface WidgetOauthConnectProps {
  content: PendingActionBlock['content']
  onConfirm?: (value: string) => void
  isLatest?: boolean
}

const POLL_MS = 2000

export default function WidgetOauthConnect({
  content,
  onConfirm,
  isLatest = true,
}: WidgetOauthConnectProps) {
  const [connecting, setConnecting] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const connectStartTimeRef = useRef<number | null>(null)
  const hasPromptedRef = useRef(false)

  // Track Meta Connect Prompted when widget appears
  useEffect(() => {
    if (!hasPromptedRef.current) {
      hasPromptedRef.current = true
      trackEvent('Meta Connect Prompted', {
        source: 'chat_oauth_widget',
      })
      trackEvent('meta_connect_prompted', {
        source: 'chat_oauth_widget',
      })
    }
  }, [])

  // Never leave the poll running after the widget goes away (thread switch,
  // unmount mid-OAuth) — it would keep hitting /ads/status forever.
  useEffect(() => () => {
    if (timerRef.current) clearInterval(timerRef.current)
  }, [])

  const handleConnect = () => {
    if (!isLatest || connecting) return
    const url = content?.options?.[0]
    if (!url) return

    connectStartTimeRef.current = Date.now()
    trackEvent('Meta Connect Started', {
      source: 'chat_oauth_widget',
    })
    trackEvent('meta_connect_started', {
      source: 'chat_oauth_widget',
    })

    // Popup, not a top-level navigation: leaving the page would tear down the
    // SSE stream this interrupt is waiting on.
    const popup = window.open(url, 'meta-oauth', 'width=600,height=750')
    if (!popup) {
      // Popup blocked — fall back to a full redirect. The widget comes back on
      // return: pending_action is persisted with the assistant message and
      // ChatPage re-derives the active widget from the thread's blocks.
      window.location.href = url
      return
    }

    setConnecting(true)
    timerRef.current = setInterval(async () => {
      try {
        const result = await adsStatusAction()
        if (result.success && result.data?.some((p) => p.platform === 'meta' && p.connected)) {
          if (timerRef.current) clearInterval(timerRef.current)
          popup.close()
          
          trackEvent('Meta Connected', {
            source: 'chat_oauth_widget',
          })
          trackEvent('meta_connected', {
            source: 'chat_oauth_widget',
          })

          onConfirm?.('connected')
          return
        }
      } catch {
        // Transient status failure — keep polling; the popup-closed check below
        // is what ends this loop if the user walked away.
      }
      if (popup.closed) {
        if (timerRef.current) clearInterval(timerRef.current)
        setConnecting(false)

        const durationSec = connectStartTimeRef.current
          ? Math.round((Date.now() - connectStartTimeRef.current) / 1000)
          : undefined

        // User closed popup without completing connection -> Meta Connect Cancelled / Abandoned
        trackEvent('Meta Connect Cancelled', {
          source: 'chat_oauth_widget',
          duration_seconds: durationSec,
          reason: 'popup_closed_before_connect',
        })
        trackEvent('meta_connect_cancelled', {
          source: 'chat_oauth_widget',
          duration_seconds: durationSec,
          reason: 'popup_closed_before_connect',
        })
      }
    }, POLL_MS)
  }

  return (
    <WidgetLayout mode="single">
      <MetaConnect
        onConnect={handleConnect}
        disabled={!isLatest || connecting}
        connecting={connecting}
      />
    </WidgetLayout>
  )
}

