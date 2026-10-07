import ast


def validate_agent_source(source_text: str):
    """
    Validate agent code before saving:
    1. File size <= 100 KB
    2. Valid Python syntax (AST parsing)
    3. Defines agent(obs) function
    4. Applies a small preflight text check (not a security sandbox)
    """
    if len(source_text.encode("utf-8")) > 100_000:
        raise ValueError("Agent file exceeds 100 KB limit.")

    try:
        tree = ast.parse(source_text)
    except SyntaxError as e:
        raise ValueError(f"Python syntax error on line {e.lineno}: {e.msg}")

    has_agent_func = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "agent"
        for node in tree.body
    )
    if not has_agent_func:
        raise ValueError("Agent must define an 'agent(obs)' function.")

    forbidden = [
        "plt.show",
        "matplotlib",
        "os.system",
        "subprocess",
        "socket",
        "requests.get",
        "requests.post",
        "urllib.request",
        "input(",
    ]
    lowered = source_text.lower()
    for pattern in forbidden:
        if pattern in lowered:
            raise ValueError(
                f"Agent contains forbidden pattern: '{pattern}'. "
                "Agents must be non-blocking and isolated."
            )
