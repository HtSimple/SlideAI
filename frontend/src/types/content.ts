export interface SlideCitation {
  chunk_id: string;
  file_id: string;
  display_name: string;
  page_number: number | null;
  section_title: string | null;
  excerpt: string;
}

export interface SlideContent {
  id: string;
  task_id: string;
  page_number: number;
  section_id: string;
  outline_item_id: string;
  title: string;
  bullets: string[];
  speaker_notes: string | null;
  citations: SlideCitation[];
  verification_notes: string[];
}

export interface SlideProgress {
  total_pages: number;
  completed_pages: number;
  total_batches: number;
  completed_batches: number;
  current_section_id: string | null;
  current_batch_pages: number[];
}

export interface SlideListResponse {
  task_id: string;
  version: number;
  target_page_count: number;
  generation_progress: SlideProgress | null;
  items: SlideContent[];
}

export interface MarkdownResponse {
  task_id: string;
  version: number;
  markdown: string;
}
