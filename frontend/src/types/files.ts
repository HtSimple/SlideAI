export type SourceFileStatus =
  | "UPLOADED"
  | "PARSING"
  | "CHUNKING"
  | "EMBEDDING"
  | "READY"
  | "FAILED"
  | "DELETED";

export interface SourceFile {
  id: string;
  task_id: string;
  original_name: string;
  mime_type: string;
  extension: string;
  size_bytes: number;
  status: SourceFileStatus;
  error_code: string | null;
  error_message: string | null;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface FileLimits {
  max_file_size_bytes: number;
  max_files_per_task: number;
  allowed_extensions: string[];
}
