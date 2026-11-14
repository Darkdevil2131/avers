CREATE INDEX IF NOT EXISTS evidence_links_span_idx
ON evidence_links(source_id, start_offset, end_offset, id);
INSERT OR IGNORE INTO schema_versions VALUES(5);
