export type Role = "user" | "assistant";

export interface SourceChunk {
  section: string;
  chunk_type: string;
  rerank_score: number;
  preview: string;
}

export interface Message {
  id: string;
  role: Role;
  content: string;
  /** Retrieved chunks shown alongside the assistant's reply. */
  sources?: SourceChunk[];
  /** True while the assistant is still streaming this message. */
  streaming?: boolean;
  /** Server-reported error attached to this turn, if any. */
  error?: string;
}

export type WsServerMsg =
  | { type: "start"; table: string | null }
  | { type: "sources"; chunks: SourceChunk[] }
  | { type: "token"; text: string }
  | { type: "end" }
  | { type: "error"; message: string };
