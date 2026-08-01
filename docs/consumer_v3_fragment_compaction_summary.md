# Summary

The consumer v3 serializer now groups bounded JSON subtrees into exact fragments, preventing structurally large but byte-bounded phase payloads from exhausting the 1,000-fragment ceiling. No analytical content or transport limit is relaxed.
