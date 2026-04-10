"""Entry point for python -m atlassian_mcp_guardrails.

Use this or the atlassian-mcp-guardrails CLI — do NOT use
python -m atlassian_mcp_guardrails.server, which causes a duplicate module
load and results in "No tools, prompts, or resources" in Cursor.
"""

from atlassian_mcp_guardrails.server import main

if __name__ == "__main__":
    main()
