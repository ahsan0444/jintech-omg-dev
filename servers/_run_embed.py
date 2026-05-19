#!/usr/bin/env python3
"""
Standalone embed runner — called by start-crg.py as a background subprocess.
Uses the venv's Python so imports resolve correctly without sys.path hacks.
Usage: python3 _run_embed.py <repo_root>
"""
import sys
import asyncio

def main():
    if len(sys.argv) < 2:
        print('[jintech-omg-dev] _run_embed.py: missing repo_root arg', file=sys.stderr)
        sys.exit(1)

    repo_root = sys.argv[1]

    try:
        from code_review_graph.main import embed_graph_tool
        # embed_graph_tool is a fastmcp FunctionTool — .fn is the actual callable
        fn = embed_graph_tool.fn if hasattr(embed_graph_tool, 'fn') else embed_graph_tool
        result = asyncio.run(fn(repo_root=repo_root))
        summary = result.get('summary', str(result)) if isinstance(result, dict) else str(result)
        print(f'[jintech-omg-dev] Auto-embed complete for {repo_root}: {summary}', file=sys.stderr)
    except ImportError as e:
        print(f'[jintech-omg-dev] Auto-embed skipped — sentence-transformers not installed: {e}', file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f'[jintech-omg-dev] Auto-embed failed for {repo_root}: {e}', file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
