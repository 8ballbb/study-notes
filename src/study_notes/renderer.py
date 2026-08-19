def _yaml_scalar(value: str) -> str:
    """Quote a YAML scalar only when needed, so normal values stay unquoted."""
    needs_quote = (
        value == ""
        or value != value.strip()
        or value[0] in "!&*?|>%@`\"'#[]{},"
        or ": " in value
        or value.endswith(":")
        or "#" in value
        or '"' in value
        or "\n" in value
    )
    if not needs_quote:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
