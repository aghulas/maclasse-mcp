"""Point d'entrée : python -m maclasse_mcp (stdio, Claude Desktop)."""
from .server import mcp


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
