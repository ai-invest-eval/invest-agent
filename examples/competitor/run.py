"""Explicit live runner. Calls Tavily up to 3 times and the LLM once."""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from src.agents.competitor import build_live_agent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--env", required=True, type=Path)
    parser.add_argument("--model", default="gpt-4o-mini")
    args = parser.parse_args()
    load_dotenv(args.env, override=True)
    state = json.loads(args.input.read_text(encoding="utf-8"))
    result = build_live_agent(args.model)(state)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Analysis format: v10 Markdown string")
    print("Saved:", args.output)


if __name__ == "__main__":
    main()
