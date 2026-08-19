from study_notes.vault_index import VaultIndex


def vault_search(index: VaultIndex, query: str, category: str, k: int = 5) -> list[dict]:
    return [
        {"path": path, "score": score}
        for path, score in index.find_related(query, category=category, k=k)
    ]


def list_categories(index: VaultIndex) -> list[dict]:
    return [{"name": c.name, "description": c.description} for c in index.list_categories()]
