-- Chunk provenance: the reviewed segment IDs each chunk was cut from.
-- Rows indexed before this migration keep '[]' and are backfilled on re-indexing.
ALTER TABLE chunks ADD COLUMN source_segment_ids_json TEXT NOT NULL DEFAULT '[]'
    CHECK(json_valid(source_segment_ids_json));
