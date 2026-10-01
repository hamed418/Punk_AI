import type { LangchainData } from './chat';

export interface ChatThread {
  id: string;
  thread_id: string;
  title: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  starred: boolean;
}

export interface ThreadsResponse {
  threads: ChatThread[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface ChatMessage {
  id: string;
  role: string;
  content: string;
  thinking: string | null;
  langchain_data: LangchainData | null;
  /**
   * Address of the checkpoint this turn ended on. A user message is rewindable
   * when the assistant message before it carries BOTH halves.
   *
   * checkpoint_ns null means a pre-namespace row whose checkpoint_id is the old
   * ambiguous parent stamp — not rewindable. '' is a REAL value (a pause in the
   * parent graph) and is falsy in JS, so test for null, never truthiness.
   */
  checkpoint_id: string | null;
  checkpoint_ns: string | null;
  created_at: string;
}

export interface HistoryResponse {
  messages: ChatMessage[];
}

/**
 * Live state of one chat thread, from GET /chat/{id}/status.
 *
 * `pending_action` and `map_data` are read off the LangGraph checkpoint's active
 * interrupt, so they are authoritative after a refresh — unlike the copy stored
 * on the last assistant message, which is only a fallback for older rows.
 */
export interface ChatStatus {
  session_id: string;
  /** A turn is executing server-side right now; attach to /stream to follow it. */
  running: boolean;
  run_id: string | null;
  /** Sequence number of the newest emitted frame, or -1 when nothing ran yet. */
  last_seq: number;
  /** The graph is paused waiting on user input. */
  interrupted: boolean;
  pending_action: LangchainData['pending_action'] | null;
  map_data: LangchainData['map_data'] | null;
  /** The last answer can still be rewound (false once published to Meta). */
  can_undo: boolean;
}

/** What pressing Stop actually did. Mirrors backend CancelOutcome. */
export type CancelOutcome =
  /** Nothing was in flight — the button was a no-op. */
  | 'not_running'
  /** The graph never consumed the answer, so it was withdrawn. */
  | 'unsent'
  /** The answer counted; the partial reply was saved. */
  | 'kept'
  /** Stopped inside the Meta publish pipeline — PAUSED objects exist. */
  | 'publish_interrupted';

/** Result of POST /chat/{id}/cancel. */
export interface CancelResult {
  outcome: CancelOutcome;
  /** The withdrawn answer, so a typed one can go back in the composer. Only for 'unsent'. */
  restored_value: string | null;
}
