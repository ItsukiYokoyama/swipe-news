from swipe_news import taste, taxonomy


def test_terms_extracts_quoted_katakana_and_latin():
    terms = taste._terms("「機動戦士ガンダム」の新作、Nintendo Switch 向けにウマ娘が登場")
    assert {"機動戦士ガンダム", "Nintendo", "Switch", "ウマ娘"} <= terms
    assert "ゲーム" not in taste._terms("ゲームの話")  # Common words are excluded


def test_taxonomy_is_consistent():
    names = taxonomy.genre_names()
    assert len(names) == len(set(names)) > 0
    assert all(taxonomy.category_of(n) in taxonomy.CATEGORIES for n in names)
    assert taxonomy.category_of("存在しない") is None
