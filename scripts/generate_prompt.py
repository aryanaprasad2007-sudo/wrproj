#!/usr/bin/env python3
"""Generate system_prompt.md from personality.yaml."""

import pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "personality.yaml"
OUTPUT_PATH = ROOT / "system_prompt.md"


def render(config: dict) -> str:
    name = config["name"]
    lines = [f"# {name} — System Prompt", ""]
    lines.append(f"You are {name}. {config['description']}")
    lines.append("")
    lines.append("## Tone")
    lines.append(config["tone_detail"][config["tone"]].strip())
    lines.append("")
    lines.append("## Verbosity")
    lines.append(config["verbosity_detail"][config["verbosity"]].strip())
    lines.append("")
    lines.append("## Handling pushback")
    lines.append(config["pushback_detail"][config["pushback"]].strip())
    lines.append("")
    lines.append("## Traits")
    for trait in config.get("traits", []):
        lines.append(f"- {config['traits_detail'][trait].strip()}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text())
    OUTPUT_PATH.write_text(render(config))
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
