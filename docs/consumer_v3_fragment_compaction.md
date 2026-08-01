# Consumer v3 fragment compaction

Consumer v3 now retains any JSON object or array whose canonical fragment is at most 9 KiB as one exact subtree fragment. Oversized containers continue through the established leaf projection. Reconstruction remains lossless and deterministic.

The existing limits remain unchanged: 1,000 combined fragments per phase, eight phase parts, 32 detail parts, and 128 KiB combined phase/detail bytes. Limit failures now identify the payload kind, phase number, observed count, and configured maximum.
