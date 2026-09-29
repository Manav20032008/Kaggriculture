from pathlib import Path
import ast

REQUIRED_FUNCTION = "agent"


class ValidationError(ValueError):
    pass


def validate_agent_file(path: Path) -> None:
    if not path.exists():
        raise ValidationError(f"Submission file does not exist: {path}")

    if path.name != "main.py":
        raise ValidationError("Submission file must be named main.py.")

    source = path.read_text(encoding="utf-8")

    if len(source.encode("utf-8")) > 100_000:
        raise ValidationError("Submission is larger than 100 KB.")

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise ValidationError(
            f"Python syntax error on line {exc.lineno}: {exc.msg}"
        ) from exc

    functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    if REQUIRED_FUNCTION not in functions:
        raise ValidationError(
            "main.py must define an agent(obs) function."
        )

    # Basic event rule: submissions should not try to create their own
    # Kaggriculture environment or submit through Kaggle.
    forbidden_strings = [
        "kaggle.com",
        "KAGGLE_API_TOKEN",
        "subprocess",
        "os.system",
        "socket",
    ]

    lowered = source.lower()
    for item in forbidden_strings:
        if item.lower() in lowered:
            raise ValidationError(
                f"Submission contains a forbidden pattern: {item}"
            )
